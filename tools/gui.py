#!/usr/bin/env python3
"""
gui.py - Tkinter control panel for the Loop / PIC16F13145 firmware.

Opens the Curiosity Nano serial console (115200 8N1, DTR/RTS asserted - the same
convention the test tools use) and exposes the firmware's commands as graphical
controls:

  * PWM         - shared frequency, per-channel duty (slider) and on/off
  * Half-bridge - on/off, live dead-time slider (dt x 31.25 ns), carrier 125/62.5 kHz
  * Device      - version, reset, pinid, refresh status
  * Console     - live log of everything the firmware prints + a raw command line

A background reader thread streams all console output into the log and scrapes the
`pulse status` / `clb status` lines so the controls track the device state.

Run:      python gui.py                 (port auto-detected via setup_flasher.config)
          python gui.py --port COM7      (override)
Requires: pyserial (already in requirements.txt). tkinter ships with CPython.
"""
import argparse
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk

try:
    import serial
    import serial.tools.list_ports as list_ports
except ImportError:  # pragma: no cover - clearer message than a raw traceback
    raise SystemExit("pyserial is required: pip install pyserial")

try:
    from project_config import flasher_port
except Exception:                                    # noqa: BLE001 - optional helper
    def flasher_port(default="COM12"):
        return default

BAUD = 115200


# ----------------------------------------------------------------------------- reader
class SerialReader(threading.Thread):
    """Read bytes from the port and push decoded text chunks onto a queue."""

    def __init__(self, ser, rx_queue, on_error):
        super().__init__(daemon=True)
        self.ser = ser
        self.rx = rx_queue
        self.on_error = on_error
        self._running = True

    def run(self):
        while self._running:
            try:
                n = self.ser.in_waiting
                data = self.ser.read(n or 1)          # blocks up to the port timeout
            except (OSError, serial.SerialException):
                if self._running:
                    self.on_error()
                return
            if data:
                self.rx.put(data.decode("ascii", "ignore"))

    def stop(self):
        self._running = False


# -------------------------------------------------------------------------------- app
class App(tk.Tk):
    def __init__(self, default_port):
        super().__init__()
        self.title("Loop - PIC16F13145 Control Panel")
        self.geometry("780x740")
        self.minsize(700, 620)

        self.ser = None
        self.reader = None
        self.rx = queue.Queue()
        self._line_buf = ""
        self._syncing = False          # True while we set controls from scraped status
        self._controls = []            # widgets enabled only while connected

        self._build_ui(default_port)
        self.after(50, self._poll_rx)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI construction ----------------------------------------------------
    def _build_ui(self, default_port):
        pad = dict(padx=6, pady=4)
        self.columnconfigure(0, weight=1)

        # --- Connection -------------------------------------------------------
        conn = ttk.LabelFrame(self, text="Connection")
        conn.grid(row=0, column=0, sticky="ew", **pad)
        for c in range(6):
            conn.columnconfigure(c, weight=1 if c == 1 else 0)
        ttk.Label(conn, text="Port:").grid(row=0, column=0, sticky="w", padx=4)
        self.port_var = tk.StringVar(value=default_port)
        self.port_box = ttk.Combobox(conn, textvariable=self.port_var, width=14)
        self.port_box.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(conn, text="Refresh", command=self._refresh_ports)\
            .grid(row=0, column=2, padx=2)
        self.btn_conn = ttk.Button(conn, text="Connect", command=self._toggle_connect)
        self.btn_conn.grid(row=0, column=3, padx=2)
        self.conn_dot = ttk.Label(conn, text="● disconnected", foreground="#b00")
        self.conn_dot.grid(row=0, column=4, sticky="e", padx=8)
        self._refresh_ports()

        # --- PWM --------------------------------------------------------------
        pwm = ttk.LabelFrame(self, text="PWM  (RC0 = A, RC1 = B; shared frequency)")
        pwm.grid(row=1, column=0, sticky="ew", **pad)
        pwm.columnconfigure(2, weight=1)

        ttk.Label(pwm, text="Frequency [Hz]:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.freq_var = tk.StringVar(value="1000")
        e = ttk.Entry(pwm, textvariable=self.freq_var, width=12)
        e.grid(row=0, column=1, sticky="w")
        e.bind("<Return>", lambda _ev: self._set_freq())
        self._controls.append(e)
        b = ttk.Button(pwm, text="Set", command=self._set_freq)
        b.grid(row=0, column=2, sticky="w", padx=4)
        self._controls.append(b)
        preset = ttk.Frame(pwm)
        preset.grid(row=0, column=3, columnspan=2, sticky="e")
        for hz, txt in [(1000, "1k"), (10000, "10k"), (50000, "50k"), (100000, "100k")]:
            pb = ttk.Button(preset, text=txt, width=4,
                            command=lambda h=hz: self._set_freq(h))
            pb.pack(side="left", padx=1)
            self._controls.append(pb)
        self.lbl_freq_act = ttk.Label(pwm, text="actual: -", foreground="#06c")
        self.lbl_freq_act.grid(row=1, column=0, columnspan=5, sticky="w", padx=4)

        self.a_on_var = tk.BooleanVar()
        self.a_duty_var = tk.DoubleVar(value=50.0)
        self._build_channel(pwm, 2, "A (RC0)", "a", self.a_on_var, self.a_duty_var)
        self.lbl_a_act = ttk.Label(pwm, text="actual: -", foreground="#06c")
        self.lbl_a_act.grid(row=3, column=0, columnspan=5, sticky="w", padx=4)

        self.b_on_var = tk.BooleanVar()
        self.b_duty_var = tk.DoubleVar(value=50.0)
        self._build_channel(pwm, 4, "B (RC1)", "b", self.b_on_var, self.b_duty_var)
        self.lbl_b_act = ttk.Label(pwm, text="actual: -", foreground="#06c")
        self.lbl_b_act.grid(row=5, column=0, columnspan=5, sticky="w", padx=4)

        # --- Half-bridge ------------------------------------------------------
        hb = ttk.LabelFrame(self, text="CLB half-bridge  (RC0 = HS, RC1 = LS)")
        hb.grid(row=2, column=0, sticky="ew", **pad)
        hb.columnconfigure(2, weight=1)

        self.clb_on_var = tk.BooleanVar()
        cb = ttk.Checkbutton(hb, text="Half-bridge ON", variable=self.clb_on_var,
                             command=self._on_clb_toggle)
        cb.grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self._controls.append(cb)
        self.lbl_clb_act = ttk.Label(hb, text="actual: -", foreground="#06c")
        self.lbl_clb_act.grid(row=0, column=1, columnspan=3, sticky="w", padx=8)

        ttk.Label(hb, text="Dead-time [dt]:").grid(row=1, column=0, sticky="w", padx=4)
        self.dt_var = tk.IntVar(value=3)
        sc = ttk.Scale(hb, from_=0, to=255, variable=self.dt_var, orient="horizontal",
                       command=self._on_dt_slide)
        sc.grid(row=1, column=1, columnspan=2, sticky="ew", padx=4)
        sc.bind("<ButtonRelease-1>", lambda _ev: self._set_dt())
        self._controls.append(sc)
        self.lbl_dt = ttk.Label(hb, text="3  (~93 ns)", width=16)
        self.lbl_dt.grid(row=1, column=3, sticky="w", padx=4)

        ttk.Label(hb, text="Carrier:").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.freq_sel_var = tk.IntVar(value=1)
        cf = ttk.Frame(hb)
        cf.grid(row=2, column=1, sticky="w")
        for val, txt in [(0, "~125 kHz"), (1, "~62.5 kHz")]:
            rb = ttk.Radiobutton(cf, text=txt, value=val, variable=self.freq_sel_var,
                                 command=self._on_carrier)
            rb.pack(side="left", padx=6)
            self._controls.append(rb)

        # --- Device ------------------------------------------------------------
        dev = ttk.LabelFrame(self, text="Device")
        dev.grid(row=3, column=0, sticky="ew", **pad)
        for txt, cmd in [("Version", lambda: self.send("version")),
                         ("Refresh status", self.refresh_status),
                         ("pinid", lambda: self.send("pinid")),
                         ("Reset", self._reset),
                         ("Help", lambda: self.send("help"))]:
            b = ttk.Button(dev, text=txt, command=cmd)
            b.pack(side="left", padx=4, pady=4)
            self._controls.append(b)

        # --- Console -----------------------------------------------------------
        con = ttk.LabelFrame(self, text="Console")
        con.grid(row=4, column=0, sticky="nsew", **pad)
        self.rowconfigure(4, weight=1)
        con.columnconfigure(0, weight=1)
        con.rowconfigure(0, weight=1)
        self.log = tk.Text(con, height=12, wrap="none", state="disabled",
                           bg="#101418", fg="#d6e2ea", insertbackground="#d6e2ea",
                           font=("Consolas", 10))
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(con, orient="vertical", command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=sb.set)

        raw = ttk.Frame(con)
        raw.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 2))
        raw.columnconfigure(0, weight=1)
        self.raw_var = tk.StringVar()
        re_ = ttk.Entry(raw, textvariable=self.raw_var)
        re_.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        re_.bind("<Return>", self._send_raw)
        self._controls.append(re_)
        bs = ttk.Button(raw, text="Send", command=self._send_raw)
        bs.grid(row=0, column=1)
        self._controls.append(bs)
        ttk.Button(raw, text="Clear log", command=self._clear_log)\
            .grid(row=0, column=2, padx=4)

        self._set_connected(False)

    def _build_channel(self, parent, row, label, ch, on_var, duty_var):
        cb = ttk.Checkbutton(parent, text=label + "  ON", variable=on_var,
                             command=lambda: self._on_ch_toggle(ch, on_var))
        cb.grid(row=row, column=0, sticky="w", padx=4)
        self._controls.append(cb)
        sc = ttk.Scale(parent, from_=0, to=100, variable=duty_var, orient="horizontal",
                       command=lambda _v, c=ch: self._on_duty_slide(c))
        sc.grid(row=row, column=1, columnspan=2, sticky="ew", padx=4)
        sc.bind("<ButtonRelease-1>", lambda _ev, c=ch: self._set_duty(c))
        self._controls.append(sc)
        lbl = ttk.Label(parent, text="50.0 %", width=8)
        lbl.grid(row=row, column=3, sticky="w", padx=4)
        setattr(self, f"lbl_{ch}_duty", lbl)

    # ---- connection ----------------------------------------------------------
    def _refresh_ports(self):
        ports = [p.device for p in list_ports.comports()] if list_ports else []
        cur = self.port_var.get()
        if cur and cur not in ports:
            ports = [cur] + ports
        self.port_box["values"] = ports
        if not self.port_var.get() and ports:
            self.port_var.set(ports[0])

    def _toggle_connect(self):
        self._disconnect() if self.ser else self._connect()

    def _connect(self):
        port = self.port_var.get().strip()
        if not port:
            self._append("** pick a COM port first\n")
            return
        try:
            s = serial.Serial(port, BAUD, timeout=0.1)
            s.dtr = True             # CDC data path needs DTR/RTS asserted
            s.rts = True
        except (OSError, serial.SerialException) as exc:
            self._append(f"** cannot open {port}: {exc}\n")
            return
        time.sleep(0.3)
        try:
            s.reset_input_buffer()
        except (OSError, serial.SerialException):
            pass
        self.ser = s
        self.reader = SerialReader(s, self.rx, lambda: self.after(0, self._handle_lost))
        self.reader.start()
        self._set_connected(True)
        self._append(f"** connected to {port} @ {BAUD} 8N1\n")
        self.after(300, lambda: (self.send("version"), self.refresh_status()))

    def _disconnect(self):
        if self.reader:
            self.reader.stop()
            self.reader = None
        if self.ser:
            try:
                self.ser.close()
            except (OSError, serial.SerialException):
                pass
            self.ser = None
        self._set_connected(False)
        self._append("** disconnected\n")

    def _handle_lost(self):
        if self.ser:
            self._append("** serial connection lost\n")
        self._disconnect()

    def _set_connected(self, connected):
        state = "normal" if connected else "disabled"
        for w in self._controls:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        self.btn_conn.configure(text="Disconnect" if connected else "Connect")
        self.conn_dot.configure(
            text="● connected" if connected else "● disconnected",
            foreground="#0a0" if connected else "#b00")

    # ---- command senders -----------------------------------------------------
    def send(self, line, echo=True):
        if not self.ser:
            self._append("** not connected\n")
            return
        try:
            self.ser.write((line + "\r").encode())
        except (OSError, serial.SerialException):
            self._handle_lost()
            return
        if echo:
            self._append(f"<< {line}\n")

    def _set_freq(self, hz=None):
        if hz is None:
            try:
                hz = int(float(self.freq_var.get()))
            except ValueError:
                self._append("** frequency must be a number (Hz)\n")
                return
        self.freq_var.set(str(hz))
        self.send(f"pulse freq {hz}")

    def _on_ch_toggle(self, ch, var):
        if self._syncing:
            return
        self.send(f"pulse {ch} {'on' if var.get() else 'off'}")

    def _on_duty_slide(self, ch):
        getattr(self, f"lbl_{ch}_duty").config(
            text=f"{getattr(self, f'{ch}_duty_var').get():.1f} %")

    def _set_duty(self, ch):
        if self._syncing:
            return
        val = getattr(self, f"{ch}_duty_var").get()
        self.send(f"pulse {ch} duty {val:.1f}")

    def _on_clb_toggle(self):
        if self._syncing:
            return
        self.send(f"clb {'on' if self.clb_on_var.get() else 'off'}")

    def _on_dt_slide(self, _v=None):
        dt = self.dt_var.get()
        self.lbl_dt.config(text=f"{dt}  (~{dt * 3125 // 100} ns)")

    def _set_dt(self):
        if self._syncing:
            return
        self.send(f"clb dt {self.dt_var.get()}")

    def _on_carrier(self):
        if self._syncing:
            return
        self.send(f"clb freq {self.freq_sel_var.get()}")

    def _reset(self):
        self.send("reset")
        self.after(400, self.refresh_status)

    def refresh_status(self):
        self.send("pulse status", echo=False)
        self.after(200, lambda: self.send("clb status", echo=False))

    def _send_raw(self, _ev=None):
        line = self.raw_var.get().strip()
        if line:
            self.send(line)
            self.raw_var.set("")

    # ---- incoming text -------------------------------------------------------
    def _poll_rx(self):
        try:
            while True:
                chunk = self.rx.get_nowait()
                self._append(chunk)
                self._scrape(chunk)
        except queue.Empty:
            pass
        self.after(50, self._poll_rx)

    def _scrape(self, chunk):
        self._line_buf += chunk
        while "\n" in self._line_buf:
            line, self._line_buf = self._line_buf.split("\n", 1)
            self._update_from_line(line.strip())

    def _update_from_line(self, line):
        m = re.search(r"Frequency\s*(?:=|->)\s*([\d.]+)\s*Hz", line)
        if m:
            self.lbl_freq_act.config(text=f"actual: {float(m.group(1)):.3f} Hz")
        for ch, lbl, on_var in (("A", "lbl_a_act", self.a_on_var),
                                ("B", "lbl_b_act", self.b_on_var)):
            m = re.search(rf"{ch}\s*\(RC\d\):\s*(ON|OFF),\s*duty\s*([\d.]+)", line)
            if m:
                getattr(self, lbl).config(
                    text=f"actual: {m.group(1)}, {float(m.group(2)):.2f} %")
                self._sync(lambda v=m.group(1), o=on_var: o.set(v == "ON"))
        m = re.search(r"CLB:\s*(ON|OFF),\s*dead-time\s*(\d+)\s*ticks\s*"
                      r"\(~(\d+)\s*ns\),\s*PWM\s*~(\d+)", line)
        if m:
            on, ticks, ns, hz = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            self.lbl_clb_act.config(
                text=f"actual: {on}, dt {ticks} (~{ns} ns), {hz} Hz")

            def _apply():
                self.clb_on_var.set(on == "ON")
                self.dt_var.set(ticks)
                self._on_dt_slide()
                self.freq_sel_var.set(0 if hz >= 100000 else 1)
            self._sync(_apply)

    def _sync(self, fn):
        self._syncing = True
        try:
            fn()
        finally:
            self._syncing = False

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self):
        self._disconnect()
        self.destroy()


def main():
    ap = argparse.ArgumentParser(description="Tkinter control panel for the Loop firmware")
    ap.add_argument("--port", default=flasher_port(),
                    help="serial port of the Curiosity Nano (default: from setup_flasher.config)")
    args = ap.parse_args()
    App(args.port).mainloop()


if __name__ == "__main__":
    main()
