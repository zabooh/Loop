#!/usr/bin/env python3
"""
synth.py - headless CLB synthesis for the half-bridge design.

Turns clb_halfbridge.v + clb_halfbridge.xdc into a flashable CLB bitstream
(clbBitstream.S) with no GUI and no manual step, using Microchip's
`pyclbsynthesizer` command-line frontend talking to the CLB backend.

This is the step that makes the CLB toolchain fully automatable, so the
half-bridge can be regenerated -> built -> flashed -> Saleae-tested in a loop.

Prerequisites (one-time):
    pip install -i https://artifacts.microchip.com/artifactory/api/pypi/pypi/simple pyclbsynthesizer

Backend (pick one, see --host):
    cont  (default) : http://dev.logic.microchip.com/continuous   (internal, reachable on the MCHP network)
    prod            : https://logic.microchip.com                 (public; may be blocked from CI shells)
    local           : http://localhost:8001                       (offline Docker backend, fully autonomous:
                      docker run --rm -p 8001:8001 \\
                        artifacts.microchip.com:7999/microchip/logic/clb-backend:25.3.1 )

Usage:
    python synth.py                       # synthesize -> ../clbBitstream.S, print word count
    python synth.py --host local          # use the local Docker backend
    python synth.py -o build_clb          # also keep all synthesis artifacts (clb1.c/.h, svgs, logs)
    python synth.py --check               # backend reachability check only (prints API versions)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEVICE = "131"                 # pyclbsynthesizer alias for pic16f13145
DEFAULT_DEST = HERE.parent / "clbBitstream.S"
DEFAULT_DEFS = HERE.parent / "clb1_defs.h"         # generated defines header (.S + main.c need it)
DESIGN_V = HERE / "clb_halfbridge.v"               # default design source


def _run(args, **kw):
    return subprocess.run([sys.executable, "-m", "pyclbsynthesizer", *args],
                          text=True, capture_output=True, **kw)


def set_mux(code, verilog=DESIGN_V):
    """Patch the IN0 input-mux code in the Verilog: (* pincfg.IN0.mux = 7'dN *).
    Used by the hardware-in-the-loop search to select the CLB input source."""
    import re
    txt = verilog.read_text()
    new, n = re.subn(r"(pincfg\.IN0\.mux\s*=\s*7'd)\d+", rf"\g<1>{int(code)}", txt)
    if n == 0:
        raise ValueError(f"no 'pincfg.IN0.mux = 7'dN' attribute found in {verilog}")
    verilog.write_text(new)
    return code


def check(host):
    r = _run(["--host", host, "version"])
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        print(f"[synth] backend '{host}' NOT reachable", file=sys.stderr)
        return 1
    print(f"[synth] backend '{host}' reachable")
    return 0


def synth(host, dest, keep_artifacts, indir=HERE):
    # pyclbsynthesizer needs exactly one .xdc and >=1 .v in the input folder.
    # Default sources are clb_halfbridge.{v,xdc}; --indir points at a catalog design
    # folder instead (used by the CLB capability suite). The backend infers the .v as top.
    indir = Path(indir)
    out_dir = Path(keep_artifacts) if keep_artifacts else (HERE / ".clb_build")
    if out_dir.exists():
        shutil.rmtree(out_dir)

    r = _run(["--host", host, "--loglevel", "ERROR",
              "synthesize", "-d", DEVICE, str(indir), "-o", str(out_dir), "-b"])
    if r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        print("[synth] synthesis FAILED", file=sys.stderr)
        return 1

    words = [ln for ln in r.stdout.splitlines() if ln.strip().startswith("0x")]
    bitstream_s = out_dir / "bitstream.S"
    if not bitstream_s.exists():
        print("[synth] backend returned no bitstream.S", file=sys.stderr)
        return 1

    shutil.copyfile(bitstream_s, dest)
    defs = out_dir / "clb1_defs.h"          # bitstream.S #includes this; main.c uses CLB_BITSTREAM_LENGTH
    if defs.exists():
        shutil.copyfile(defs, DEFAULT_DEFS)
    print(f"[synth] OK: {len(words)} bitstream words -> {dest}")
    print(f"[synth]     defines header -> {DEFAULT_DEFS} (CLB_BITSTREAM_LENGTH {len(words)})")
    if not keep_artifacts:
        shutil.rmtree(out_dir, ignore_errors=True)
    else:
        print(f"[synth] artifacts kept in {out_dir} (clb1.c/.h, routed.svg, logs)")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="cont",
                   help="backend: cont (default), prod, dev, local, or host:port")
    p.add_argument("-o", "--keep-artifacts", metavar="DIR", default=None,
                   help="keep all synthesis artifacts in DIR (clb1.c/.h, svgs, logs)")
    p.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                   help=f"output .S path (default: {DEFAULT_DEST})")
    p.add_argument("--check", action="store_true",
                   help="only check backend reachability")
    p.add_argument("--mux", type=int, default=None,
                   help="set the IN0 input-mux code in clb_halfbridge.v before synthesis")
    p.add_argument("--indir", default=None,
                   help="input folder with the design .v/.xdc (default: the clb/ half-bridge)")
    args = p.parse_args()

    if args.check:
        return check(args.host)
    if args.mux is not None:
        set_mux(args.mux)
        print(f"[synth] set IN0 mux = 7'd{args.mux} in {DESIGN_V.name}")
    return synth(args.host, args.dest, args.keep_artifacts,
                 indir=args.indir if args.indir else HERE)


if __name__ == "__main__":
    sys.exit(main())
