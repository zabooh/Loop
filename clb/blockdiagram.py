#!/usr/bin/env python3
"""Draw a block diagram of the implemented timer+CLC half-bridge -> clb_blockdiagram.png"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "clb_blockdiagram.png")

fig, ax = plt.subplots(figsize=(11.5, 6))
ax.set_xlim(0, 116); ax.set_ylim(0, 64); ax.axis("off")

def box(x, y, w, h, title, lines, fc):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=2",
                                linewidth=1.5, edgecolor="#1f2328", facecolor=fc))
    ax.text(x + w/2, y + h - 4.5, title, ha="center", va="top", fontsize=10, fontweight="bold")
    ax.text(x + w/2, y + h - 11, "\n".join(lines), ha="center", va="top", fontsize=8,
            color="#30363d")

def arrow(x1, y1, x2, y2, label="", lc="#0969da", off=1.6):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=14,
                                 linewidth=1.6, color=lc, shrinkA=0, shrinkB=0))
    if label:
        ax.text((x1+x2)/2, (y1+y2)/2 + off, label, ha="center", va="bottom",
                fontsize=8, color=lc, fontweight="bold")

# --- blocks ---
box(2, 40, 26, 18, "CLB (Configurable Logic Block)",
    ["free-running counter", "taps cnt[7] / cnt[8]", "clb freq -> 125 / 62.5 kHz",
     "BLE_clk = FOSC 32 MHz"], "#ddf4ff")
box(44, 44, 30, 16, "TMR2  (HLT monostable)",
    ["edge-triggered, any edge", "T2RST = pwm,  T2PR = dt", "clk = FOSC (31.25 ns)",
     "-> pulse dt ticks after edge"], "#fff1e5")
box(44, 22, 30, 14, "CLC1  ->  HS",
    ["2-input D flip-flop", "D=pwm  CLK=postscaled", "R=~pwm"], "#dafbe1")
box(44, 2, 30, 14, "CLC2  ->  LS",
    ["2-input D flip-flop", "D=~pwm CLK=postscaled", "R=pwm"], "#ffebe9")
box(90, 40, 24, 18, "PPS pins",
    ["RC2 = pwm (loopback)", "RC0 = HS  (CLC1OUT)", "RC1 = LS  (CLC2OUT)",
     "RC2 -> TMR2 & CLC in"], "#f6f8fa")

# --- pwm node ---
ax.add_patch(plt.Circle((36, 49), 1.2, color="#0969da"))
ax.text(36, 52.5, "pwm\n(RC2)", ha="center", va="bottom", fontsize=8, color="#0969da")

# --- arrows ---
arrow(28, 49, 34.8, 49, "pwm")                       # CLB -> node
arrow(36, 50.2, 44, 52, "")                          # node -> TMR2 (reset)
arrow(36, 47.8, 44, 30, "edge")                      # node -> CLC1 D
arrow(36, 47.8, 44, 9,  "")                          # node -> CLC2 D
arrow(59, 44, 59, 36, "postscaled", "#bc4c00", 0.5)  # TMR2 -> CLC1 CLK
arrow(74, 30, 74, 16, "", "#bc4c00")                 # CLC1 -> CLC2 region (postscaled shared)
arrow(74, 30, 90, 50, "HS", "#1a7f37")               # CLC1 -> pins
arrow(74, 9,  90, 46, "LS", "#cf222e")               # CLC2 -> pins
arrow(74, 52, 90, 52, "")                            # TMR2 area -> pins (pwm to RC2 shown)

# postscaled also to CLC2
ax.add_patch(FancyArrowPatch((57, 44), (57, 16), arrowstyle="-|>", mutation_scale=12,
                             linewidth=1.4, color="#bc4c00", shrinkA=0, shrinkB=0,
                             connectionstyle="arc3,rad=-0.25"))

ax.text(58, 62, "PIC16F13145 half-bridge: CLB makes the PWM, TMR2+CLC make the runtime "
        "dead-time", ha="center", fontsize=12, fontweight="bold")
ax.text(58, 0.5, "dead-time = dt x 31.25 ns (clb dt 0..255, live)   |   "
        "HS needs pwm=1, LS needs pwm=0  ->  non-overlap by construction",
        ha="center", fontsize=8.5, color="#57606a")

fig.tight_layout()
fig.savefig(OUT, dpi=120, bbox_inches="tight")
print(f"wrote {OUT}")
