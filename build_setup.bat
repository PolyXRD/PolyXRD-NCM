@echo off
REM ============================================================
REM PolyXRD-NCM build - INSTALLER
REM
REM Prerequisite: run build_exe.bat first, producing
REM               dist\PolyXRD-NCM-Internal-vX.Y.Z.exe
REM Output:       dist\PolyXRD-NCM-vX.Y.Z-Setup.exe
REM
REM The payload is that single onefile exe; it is installed as
REM PolyXRD-NCM.exe (no version in the name the user sees).
REM
REM NOTE: keep this file pure ASCII - cmd.exe parses .bat in the OEM codepage.
REM ============================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else if exist "D:\Project\XRD\python310\python.exe" (
    set PYTHON=D:\Project\XRD\python310\python.exe
) else (
    set PYTHON=python
)

REM Read through tools\read_version.py - inlining the regex breaks cmd parsing.
set VERTMP=%TEMP%\pxrd_ncm_ver_setup.txt
"%PYTHON%" tools\read_version.py > "%VERTMP%" 2>nul
set VER=
set /p VER=<"%VERTMP%"
del "%VERTMP%" >nul 2>nul
if not defined VER (
    echo [ERROR] cannot read __version__ from ncm\version.py
    exit /b 1
)
echo [info] version: %VER%

if not exist "dist\PolyXRD-NCM-Internal-v%VER%.exe" (
    echo [ERROR] missing dist\PolyXRD-NCM-Internal-v%VER%.exe - run build_exe.bat first
    exit /b 1
)

REM Locate ISCC.exe. Some shells/sandboxes do not export %ProgramFiles(x86)%
REM (it is empty here), so the literal path is probed as well - same order as the
REM family build_setup.bat.
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=D:\Program Files (x86)\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" for /f "delims=" %%i in ('where ISCC.exe 2^>nul') do set ISCC=%%i
if not exist "%ISCC%" (
    echo [ERROR] Inno Setup 6 ISCC.exe not found
    exit /b 1
)
echo [info] iscc: %ISCC%

if not exist "installer_output" mkdir "installer_output"
"%ISCC%" /DAppVersion=%VER% /O"installer_output" /F"PolyXRD-NCM-v%VER%-Setup" scripts\PolyXRD-NCM-Setup.iss
if %errorlevel% neq 0 (
    echo [ERROR] Inno Setup compile failed
    exit /b 1
)

if not exist "installer_output\PolyXRD-NCM-v%VER%-Setup.exe" (
    echo [ERROR] installer_output\PolyXRD-NCM-v%VER%-Setup.exe not produced
    exit /b 1
)
if not exist "dist" mkdir "dist"
copy /Y "installer_output\PolyXRD-NCM-v%VER%-Setup.exe" "dist\" >nul
for %%F in ("dist\PolyXRD-NCM-v%VER%-Setup.exe") do echo [info] setup: %%~fF  (%%~zF bytes)

call tidy_dist.bat

echo.
echo done: dist\PolyXRD-NCM-Internal-v%VER%.exe
echo       dist\PolyXRD-NCM-v%VER%-Setup.exe
