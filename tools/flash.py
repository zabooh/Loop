#!/usr/bin/env python3
"""
flash.py
--------
Flash the Loop firmware onto the PIC16F13145 Curiosity Nano via the MPLAB MDB
(Microchip Debugger Backend). The target runs the new firmware once the tool
is released on 'quit'.

This drives mdb.bat as a subprocess and sends commands (device / hwtool /
program) over stdin. The approach is adapted from:
  C:\\work\\ptp\\check4\\net_10base_t1s\\mdb_flash.py

Two robustness changes versus that reference, needed for MPLAB X v6.25 which
emits a lot of asynchronous Java logging on stdout:
  * A background reader thread collects MDB output; a command is considered
    done when the stream ends in a '>' prompt AND has been quiet briefly.
    (The naive "read until the next '>'" desyncs against the async logs and
    blocks for minutes.)
  * quit() kills the whole process tree. mdb.bat launches a java.exe child;
    killing only the .bat orphans java, which keeps the debugger *reserved*
    and makes the next run fail with a tool-reservation error.

Unlike SWD parts (e.g. SAM), the PIC16F13145 is programmed over ICSP, so no
SWD interface/speed is configured here.

Usage:
  python flash.py                     # program out\\Loop\\default.hex, then run
  python flash.py --hex <path.hex>    # program a specific HEX
  python flash.py --serial <SN>       # pick a specific on-board debugger
  python flash.py --list              # just list detected tools (no programming)
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import threading
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEX_DEFAULT = os.path.join(_HERE, "out", "Loop", "default.hex")
MCU_DEFAULT = "PIC16F13145"
# Curiosity Nano on-board debugger type as reported by MDB's 'hwtool' listing.
TOOL_DEFAULT = "pkobnano"


def _find_mdb():
    """Return the path to mdb.bat from the newest MPLABX install, or None."""
    hits = glob.glob(
        r"C:\Program Files\Microchip\MPLABX\*\mplab_platform\bin\mdb.bat")
    hits.sort()                       # v6.20 < v6.25 ... newest last
    return hits[-1] if hits else None


class MdbSession:
    """Drive an mdb.bat subprocess with prompt-idle synchronisation."""

    def __init__(self, mdb_path):
        self.proc = subprocess.Popen(
            [mdb_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._buf = bytearray()
        self._last = time.time()
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        while True:
            ch = self.proc.stdout.read(1)
            if not ch:
                break
            with self._lock:
                self._buf += ch
                self._last = time.time()

    def _wait_prompt(self, timeout, idle=0.4):
        """Return collected text once MDB sits idle at a '>' prompt."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                text = bytes(self._buf).decode("utf-8", errors="ignore")
                quiet = time.time() - self._last
            if text.rstrip().endswith(">") and quiet >= idle:
                return text
            time.sleep(0.05)
        with self._lock:
            return bytes(self._buf).decode("utf-8", errors="ignore")

    def cmd(self, command, label="", timeout=120):
        """Send one command, wait for the prompt, echo the I/O, return output."""
        with self._lock:
            self._buf.clear()
        self.proc.stdin.write((command + "\n").encode("utf-8"))
        self.proc.stdin.flush()
        prefix = f"[{label}] " if label else ""
        print(f"{prefix}MDB << {command.strip()}")
        out = self._wait_prompt(timeout)
        for line in out.splitlines():
            s = line.strip()
            if s and s != ">":
                print(f"{prefix}MDB >> {s}")
        return out

    def wait_banner(self, timeout=30):
        self._wait_prompt(timeout)

    def quit(self, label=""):
        try:
            self.cmd("quit", label=label, timeout=10)
            self.proc.wait(timeout=15)
            return
        except Exception:
            pass
        # mdb.bat -> java.exe child: kill the whole tree or the orphan keeps
        # the debugger reserved and the next run fails.
        try:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True)
        except Exception:
            self.proc.kill()


def _list_tools(mdb, hwtool, label=""):
    """
    Return [(index, type, serial), ...] from MDB's 'hwtool' listing.
    Anchored at line start so MDB's timestamped log lines
    (e.g. "...10:48:32 PM com.microchip...") don't produce false matches.
    Row format:  <index>  <ToolType>  <Serial>  <IP>  <Description>
    """
    pat = re.compile(r"^\s*(\d+)\s+(\w+)\s+(\w+)", re.MULTILINE)
    raw = mdb.cmd("hwtool", label=label, timeout=30)
    tools = pat.findall(raw)
    if not tools and hwtool:
        raw = mdb.cmd(f"hwtool {hwtool}", label=label, timeout=30)
        tools = pat.findall(raw)
    return tools


def _select_tool(tools, serial, label=""):
    """Pick (type, index) from the tool list, matching *serial* if given."""
    if not tools:
        return None, None
    if serial:
        for idx, tool_type, sn in tools:
            if sn == serial:
                return tool_type, idx
        print(f"[{label}] ERROR: serial {serial} not found among detected tools.")
        return None, None
    if len(tools) > 1:
        print(f"[{label}] WARNING: {len(tools)} tools detected; using the first. "
              f"Use --serial to pick a specific one.")
    idx, tool_type, _ = tools[0]
    return tool_type, idx


def list_tools(mcu=MCU_DEFAULT, mdb_path=None, hwtool=TOOL_DEFAULT):
    """Print all debuggers MDB can see for *mcu*. Returns 0/1."""
    mdb_path = mdb_path or _find_mdb()
    if not mdb_path or not os.path.isfile(mdb_path):
        print(f"[ERROR] mdb.bat not found ({mdb_path}). Is MPLAB X installed?")
        return 1

    mdb = MdbSession(mdb_path)
    mdb.wait_banner()
    mdb.cmd(f"device {mcu}", label="list")
    tools = _list_tools(mdb, hwtool, label="list")
    mdb.quit(label="list")

    if not tools:
        print("\nNo debuggers detected. Is the Curiosity Nano connected?")
        return 1
    print("\nDetected tools:")
    for idx, tool_type, sn in tools:
        print(f"  index={idx}  type={tool_type}  serial={sn}")
    return 0


def flash(hex_file, serial=None, mdb_path=None, mcu=MCU_DEFAULT,
          hwtool=TOOL_DEFAULT, label=""):
    """
    Program *hex_file* onto the PIC. The target runs after the tool is released.
    Returns 0 on success, 1 on error.
    """
    hex_file = os.path.abspath(hex_file)
    mdb_path = mdb_path or _find_mdb()

    if not os.path.isfile(hex_file):
        print(f"[{label}] ERROR: HEX file not found: {hex_file}")
        print("        Run build.bat first.")
        return 1
    if not mdb_path or not os.path.isfile(mdb_path):
        print(f"[{label}] ERROR: mdb.bat not found ({mdb_path}). Is MPLAB X installed?")
        return 1

    print(f"\n{'='*60}")
    print(f"  Flash{' ' + label if label else ''}: {mcu}")
    print(f"  HEX : {hex_file}")
    print(f"  MDB : {mdb_path}")
    print(f"{'='*60}")

    mdb = MdbSession(mdb_path)
    mdb.wait_banner()

    mdb.cmd(f"device {mcu}", label=label)
    mdb.cmd("set AutoSelectMemRanges auto", label=label)

    # Find and select the on-board debugger (ICSP; no SWD interface for PIC).
    tools = _list_tools(mdb, hwtool, label=label)
    tool_type, idx = _select_tool(tools, serial, label=label)
    if idx is None:
        print(f"[{label}] ERROR: no matching debugger found — is it connected?")
        mdb.quit(label=label)
        return 1

    mdb.cmd(f"hwtool {tool_type} -p {idx}", label=label, timeout=30)

    result = mdb.cmd(f'program "{hex_file}"', label=label, timeout=180)
    if "program succeeded" not in result.lower():
        print(f"[{label}] FLASH FAILED — aborting")
        mdb.quit(label=label)
        return 1

    # NOTE: no debug 'reset'/'run' here. Those start a *debug* session, which a
    # production-programmed PIC rejects ("Unable to communicate with DE"). The
    # nEDBG releases the target on 'quit', after which it runs the new firmware.
    mdb.quit(label=label)
    print(f"[{label}] SUCCESS: Device programmed; target released and running.")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Flash the Loop firmware onto the PIC16F13145 via MPLAB MDB")
    ap.add_argument("--hex", default=HEX_DEFAULT,
                    help=f"Path to .hex file (default: {HEX_DEFAULT})")
    ap.add_argument("--serial", default=None,
                    help="On-board debugger serial (default: use the only one found)")
    ap.add_argument("--mcu", default=MCU_DEFAULT, help="Target MCU")
    ap.add_argument("--mdb", default=None, help="Path to mdb.bat (default: auto-detect)")
    ap.add_argument("--hwtool", default=TOOL_DEFAULT, help="Fallback programmer tool type")
    ap.add_argument("--label", default="LOOP", help="Log label")
    ap.add_argument("--list", action="store_true",
                    help="List detected debuggers and exit (no programming)")
    args = ap.parse_args()

    if args.list:
        return list_tools(mcu=args.mcu, mdb_path=args.mdb, hwtool=args.hwtool)

    return flash(args.hex, serial=args.serial, mdb_path=args.mdb, mcu=args.mcu,
                 hwtool=args.hwtool, label=args.label)


if __name__ == "__main__":
    sys.exit(main())
