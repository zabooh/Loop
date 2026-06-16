#!/usr/bin/env python3
r"""
setup_compiler.py — select the XC8 compiler version used by build.bat.

Scans C:\Program Files\Microchip\xc8\ for installed versions, lets you pick one,
patches cmake\Loop\default\.generated\toolchain.cmake so build.bat needs no
overrides, and records the choice in setup_compiler.config.

Run this once after cloning on a machine whose XC8 version/location differs from
the one baked into the committed toolchain.cmake.

Usage:
  python setup_compiler.py            # interactive
  python setup_compiler.py --auto     # pick the newest installed version
"""
import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "setup_compiler.config")
TOOLCHAIN_CMAKE = os.path.join(
    SCRIPT_DIR, "cmake", "Loop", "default", ".generated", "toolchain.cmake")

XC8_BASE = r"C:\Program Files\Microchip\xc8"


def _ver_key(name):
    """'v3.10' -> (3, 10) for proper numeric ordering."""
    nums = re.findall(r"\d+", name)
    return tuple(int(n) for n in nums) if nums else (0,)


def find_xc8_versions(base_dir):
    """Every installed XC8 version under base_dir (has bin/xc8-cc.exe)."""
    versions = []
    if not os.path.isdir(base_dir):
        return versions
    for name in sorted(os.listdir(base_dir), key=_ver_key):
        compiler = os.path.join(base_dir, name, "bin", "xc8-cc.exe")
        if os.path.isfile(compiler):
            versions.append({
                "version": name,                              # e.g. "v3.10"
                "bin_dir": os.path.join(base_dir, name, "bin"),
                "compiler": compiler,
            })
    return versions


def load_current_config():
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return None


def patch_toolchain_cmake(new_version):
    """Swap the XC8 version inside toolchain.cmake (forward-slash and double-
    backslash path forms both appear). Assumes the standard install base."""
    if not os.path.isfile(TOOLCHAIN_CMAKE):
        print(f"WARNING: toolchain.cmake not found — skipping patch:\n  {TOOLCHAIN_CMAKE}")
        return
    with open(TOOLCHAIN_CMAKE, "r", encoding="utf-8") as f:
        content = f.read()

    m = re.search(r"(?i)Microchip/xc8/(v[\d.]+)/", content)
    if not m:
        print("WARNING: could not detect current XC8 version in toolchain.cmake — no patch applied.")
        return
    old = m.group(1)
    if old == new_version:
        print(f"toolchain.cmake already uses XC8 {new_version} — no change needed.")
        return

    old_esc = re.escape(old)
    content = re.sub(r"(?i)(Microchip/xc8/)" + old_esc + r"(/bin)",
                     lambda mo: mo.group(1) + new_version + mo.group(2), content)
    content = re.sub(r"(?i)(Microchip\\\\xc8\\\\)" + old_esc + r"(\\\\bin)",
                     lambda mo: mo.group(1) + new_version + mo.group(2), content)

    with open(TOOLCHAIN_CMAKE, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Patched toolchain.cmake: XC8 {old} -> {new_version}")


def save_config(entry):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
    print(f"Saved: {CONFIG_FILE}")


def main():
    ap = argparse.ArgumentParser(description="Select the XC8 compiler for build.bat")
    ap.add_argument("--auto", action="store_true",
                    help="pick the newest installed version without prompting")
    args = ap.parse_args()

    print("=" * 60)
    print("  XC8 Compiler Setup for build.bat")
    print("=" * 60)

    versions = find_xc8_versions(XC8_BASE)
    if not versions:
        print(f"\nERROR: no XC8 installations found under:\n  {XC8_BASE}")
        print("Install MPLAB XC8 and run this script again.")
        return 1

    current = load_current_config()
    print(f"\nCurrent selection: {current.get('version')}" if current
          else "\nNo compiler configured yet.")

    print(f"\nInstalled XC8 versions ({len(versions)} found):\n")
    for i, v in enumerate(versions, 1):
        mark = "  <-- current" if current and current.get("version") == v["version"] else ""
        print(f"  [{i}] {v['version']:10s} {v['compiler']}{mark}")

    if args.auto:
        chosen = versions[-1]                 # newest (list is version-sorted)
        print(f"\n[auto] selecting newest: {chosen['version']}")
    else:
        print("\n  [0] Abort / keep current")
        while True:
            try:
                raw = input("\nSelect version number: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                return 0
            if raw == "0":
                print("No changes made.")
                return 0
            if raw.isdigit() and 1 <= int(raw) <= len(versions):
                chosen = versions[int(raw) - 1]
                break
            print(f"  Invalid input. Enter 0..{len(versions)}.")

    save_config(chosen)
    patch_toolchain_cmake(chosen["version"])
    print(f"\nDone. build.bat will use XC8 {chosen['version']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
