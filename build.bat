@echo off
REM ============================================================
REM PolyXRD-NCM one-click build (family convention: one exe + one Setup)
REM
REM   [1/2] build_exe.bat    -> dist\PolyXRD-NCM-Internal-vX.Y.Z.exe
REM   [2/2] build_setup.bat  -> dist\PolyXRD-NCM-vX.Y.Z-Setup.exe
REM
REM This file only chains the two steps; it duplicates no logic.
REM NOTE: keep this file pure ASCII - cmd.exe parses .bat in the OEM codepage.
REM ============================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

echo ============================================================
echo   [1/2] onefile exe
echo ============================================================
call build_exe.bat
if %errorlevel% neq 0 (
    echo [ERROR] exe build failed, aborting.
    exit /b 1
)

echo.
echo ============================================================
echo   [2/2] installer
echo ============================================================
call build_setup.bat
if %errorlevel% neq 0 (
    echo [ERROR] installer build failed.
    exit /b 1
)

echo.
echo ============================================================
echo   done. dist\ should hold exactly two files:
echo     PolyXRD-NCM-Internal-vX.Y.Z.exe
echo     PolyXRD-NCM-vX.Y.Z-Setup.exe
echo ============================================================
