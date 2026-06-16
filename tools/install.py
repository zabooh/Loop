#!/usr/bin/env python3
r"""
install.py — one-shot setup for the Loop project after cloning.

Steps:
  1. install the required Python packages (requirements.txt)
  2. verify the imports
  3. check the external toolchain (XC8 / CMake / Ninja / MPLAB MDB)
  4. run the per-machine setup helpers (setup_compiler.py, setup_flasher.py)

After this, build.bat / flash.py / run_ci.py work without extra arguments.

Usage:
  python install.py             # full install + setup
  python install.py --no-setup  # only install packages and check the toolchain
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))        # tools/ (siblings: setup_*.py)
ROOT = os.path.dirname(HERE)                             # repo root (build.bat, requirements.txt)
REQ = os.path.join(ROOT, "requirements.txt")


def _run(cmd):
    print("  $ " + " ".join(cmd))
    sys.stdout.flush()                     # keep our prints ahead of subprocess output
    return subprocess.run(cmd).returncode


def pip_install():
    print("\n== 1. Python packages ==")
    return _run([sys.executable, "-m", "pip", "install", "-r", REQ]) == 0


def check_imports():
    print("\n== 2. Verifying imports ==")
    ok = True
    for mod, pkg in (("serial", "pyserial"), ("numpy", "numpy"),
                     ("matplotlib", "matplotlib"),
                     ("saleae.automation", "logic2-automation")):
        try:
            __import__(mod)
            print(f"  [OK]   {pkg}")
        except Exception as e:
            print(f"  [MISS] {pkg}  ({e})")
            ok = False
    return ok


def check_tools():
    print("\n== 3. External toolchain (not pip-installable) ==")
    xc8 = sorted(glob.glob(r"C:\Program Files\Microchip\xc8\*\bin\xc8-cc.exe"))
    mdb = sorted(glob.glob(
        r"C:\Program Files\Microchip\MPLABX\*\mplab_platform\bin\mdb.bat"))
    cmake = shutil.which("cmake") or next(
        (p for p in [r"C:\Program Files\CMake\bin\cmake.exe"] if os.path.isfile(p)), None)
    found = {
        "XC8 compiler": xc8[-1] if xc8 else None,
        "CMake":        cmake,
        "Ninja":        shutil.which("ninja"),
        "MPLAB MDB":    mdb[-1] if mdb else None,
    }
    hints = {
        "XC8 compiler": "install MPLAB XC8 (microchip.com/xc8)",
        "CMake":        "install CMake or add it to PATH",
        "Ninja":        "install Ninja or add it to PATH",
        "MPLAB MDB":    "install MPLAB X IDE (provides mdb.bat)",
    }
    ok = True
    for name, path in found.items():
        if path:
            print(f"  [OK]   {name}: {path}")
        else:
            print(f"  [MISS] {name} — {hints[name]}")
            ok = False
    return ok


def run_setup():
    print("\n== 4. Per-machine setup ==")
    # Compiler: patch toolchain.cmake to the local XC8 (idempotent/safe).
    _run([sys.executable, os.path.join(HERE, "setup_compiler.py"), "--auto"])
    # Flasher: needs the board connected — best effort.
    if _run([sys.executable, os.path.join(HERE, "setup_flasher.py"), "--auto"]) != 0:
        print("  NOTE: no Curiosity Nano detected — connect it and run "
              "'python setup_flasher.py' later.")


def main():
    ap = argparse.ArgumentParser(description="Install deps and set up the Loop project")
    ap.add_argument("--no-setup", action="store_true",
                    help="only install packages and check the toolchain")
    args = ap.parse_args()

    print("=" * 60)
    print("  Loop project installer")
    print("=" * 60)

    if not pip_install():
        print("\nERROR: 'pip install' failed. Fix the error above and re-run.")
        return 1

    imports_ok = check_imports()
    tools_ok = check_tools()
    if not args.no_setup:
        run_setup()

    print("\n" + "=" * 60)
    print(f"  Python packages : {'OK' if imports_ok else 'INCOMPLETE'}")
    print(f"  Toolchain       : {'OK' if tools_ok else 'see [MISS] above'}")
    print("  Next steps      : build.bat  ->  python flash.py  ->  python run_ci.py")
    print("=" * 60)
    return 0 if imports_ok else 1


if __name__ == "__main__":
    sys.exit(main())
