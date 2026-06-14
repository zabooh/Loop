@echo off
rem One-shot installer for the Loop project (Python deps + toolchain check + setup).
rem Usage:  install.bat            full install + per-machine setup
rem         install.bat --no-setup only install packages and check the toolchain
python "%~dp0install.py" %*
