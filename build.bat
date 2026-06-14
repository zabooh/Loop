@echo off
rem ============================================================================
rem  build.bat - command-line build for the Loop project (PIC16F13145 / XC8)
rem
rem  Usage:
rem     build.bat            configure (if needed) and build
rem     build.bat rebuild    clean, then configure and build
rem     build.bat clean      remove the build tree and output artifacts
rem
rem  Requires CMake and Ninja on PATH. The XC8 compiler is referenced with an
rem  absolute path by the generated toolchain file, so it need not be on PATH.
rem ============================================================================
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
set "PRESET_DIR=%ROOT%cmake\Loop\default"
set "PRESET=Loop_default_conf"
set "BUILD_DIR=%ROOT%_build\Loop\default"
set "OUT_ELF=%ROOT%out\Loop\default.elf"

rem --- locate cmake (PATH first, then the default install location) ----------
set "CMAKE=cmake"
where cmake >nul 2>nul || set "CMAKE=C:\Program Files\CMake\bin\cmake.exe"
if not exist "%CMAKE%" if "%CMAKE%"=="C:\Program Files\CMake\bin\cmake.exe" (
    echo [ERROR] cmake not found on PATH or in "C:\Program Files\CMake\bin".
    exit /b 1
)

rem --- handle clean / rebuild -------------------------------------------------
if /i "%~1"=="clean"   goto :clean
if /i "%~1"=="rebuild" call :clean

rem --- configure (CMake preset) ----------------------------------------------
echo === Configuring (%PRESET%) ===
pushd "%PRESET_DIR%" || (echo [ERROR] preset dir not found: "%PRESET_DIR%" & exit /b 1)
"%CMAKE%" --preset %PRESET%
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" (
    echo [ERROR] configure failed ^(exit %RC%^).
    exit /b %RC%
)

rem --- build (Ninja via CMake) ------------------------------------------------
echo === Building ===
"%CMAKE%" --build "%BUILD_DIR%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo [ERROR] build failed ^(exit %RC%^).
    exit /b %RC%
)

echo === Build finished ===
if exist "%OUT_ELF%" echo Output: %OUT_ELF%
exit /b 0

rem ---------------------------------------------------------------------------
:clean
echo === Cleaning ===
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%ROOT%out"   rmdir /s /q "%ROOT%out"
if /i "%~1"=="clean" exit /b 0
goto :eof
