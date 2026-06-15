#!/usr/bin/env python3
"""
Cycle-accurate Python model of clb_halfbridge.v, to validate the dead-time LOGIC
independently of the CLB synthesizer (which is non-deterministic on hardware).

Models exactly:
    reg pwm_d; reg [2:0] cnt;
    wire edge_seen = pwm_in ^ pwm_d;
    always @(posedge CLK) begin
        pwm_d <= pwm_in;
        if (edge_seen)      cnt <= 0;
        else if (cnt != dt) cnt <= cnt + 1;
    end
    wire settled = (cnt == dt);
    assign hs =  pwm_in & settled;
    assign ls = ~pwm_in & settled;

Usage:  python clb/sim_halfbridge.py [dt] [pwm_period_cycles]
Checks: HS and LS never both high (non-overlap); dead-time = #cycles both low
        after each input edge; prints a per-cycle trace and a verdict.
"""
import sys


def simulate(dt, pwm_period=20, cycles=80):
    half = pwm_period // 2
    pwm_d = 0
    cnt = 0
    trace = []
    for t in range(cycles):
        pwm_in = 1 if (t % pwm_period) < half else 0
        edge_seen = pwm_in ^ pwm_d
        settled = 1 if cnt == dt else 0
        hs = pwm_in & settled
        ls = (1 - pwm_in) & settled
        trace.append((t, pwm_in, cnt, settled, hs, ls))
        # registered next-state
        pwm_d_next = pwm_in
        if edge_seen:
            cnt_next = 0
        elif cnt != dt:
            cnt_next = (cnt + 1) & 0x7
        else:
            cnt_next = cnt
        pwm_d, cnt = pwm_d_next, cnt_next
    return trace


def analyze(trace):
    overlap = sum(1 for (_, _, _, _, hs, ls) in trace if hs and ls)
    both_low = sum(1 for (_, _, _, _, hs, ls) in trace if not hs and not ls)
    # dead-time = length of each both-low run that follows an input transition
    runs, run = [], 0
    for (_, _, _, _, hs, ls) in trace:
        if not hs and not ls:
            run += 1
        elif run:
            runs.append(run); run = 0
    if run:
        runs.append(run)
    return overlap, both_low, runs


def main():
    dt = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    period = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    trace = simulate(dt, period)
    print(f"dt={dt}, pwm_period={period} cycles\n t pwm cnt set hs ls")
    for (t, p, c, s, hs, ls) in trace[:period * 2 + 4]:
        mark = "  <- BOTH HIGH!" if (hs and ls) else ("  dead-time" if not hs and not ls else "")
        print(f"{t:2d}  {p}  {c}   {s}  {hs}  {ls}{mark}")
    overlap, both_low, runs = analyze(trace)
    print(f"\noverlap (both high) cycles: {overlap}")
    print(f"dead-time runs (both-low lengths): {runs}")
    inner = [r for r in runs if r <= period]    # ignore startup
    print(f"VERDICT: non-overlap={'OK' if overlap == 0 else 'FAIL'}; "
          f"dead-time per transition ~= {max(set(inner), key=inner.count) if inner else 0} cycles "
          f"(expected {dt})")


if __name__ == "__main__":
    main()
