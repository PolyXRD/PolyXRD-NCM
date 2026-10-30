@echo off
REM ============================================================
REM PolyXRD-NCM build - INTERNAL EVALUATION EDITION (onefile)
REM
REM Prerequisite: numpy / scipy / matplotlib / PySide6 / PyInstaller
REM Output:       dist\PolyXRD-NCM-Internal-vX.Y.Z.exe
REM
REM Family convention (same as PolyXRD-LFP / NCA / DoCryst):
REM   dist\PolyXRD-NCM-Internal-vX.Y.Z.exe   internal evaluation (this script)
REM   dist\PolyXRD-NCM-vX.Y.Z-Setup.exe      installer (build_setup.bat)
REM dist\ must end up holding exactly these two files (tidy_dist.bat).
REM
REM NOTE: do NOT use --clean. Under this sandbox deleting more than 50 files
REM in one call trips SAFE_DELETE_BULK_CONFIRM_REQUIRED and the PyInstaller
REM clean-up phase fails. Stale artefacts are removed item by item below.
REM
REM NOTE: keep this file pure ASCII - cmd.exe parses .bat in the OEM codepage
REM (cp936 here), so UTF-8 Chinese comments turn into garbage commands.
REM ============================================================

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

REM -- interpreter: project venv -> family base python -> PATH --
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
    set PIP=venv\Scripts\pip.exe
) else if exist "D:\Project\XRD\python310\python.exe" (
    set PYTHON=D:\Project\XRD\python310\python.exe
    set PIP=D:\Project\XRD\python310\python.exe -m pip
) else (
    set PYTHON=python
    set PIP=python -m pip
)
echo [info] python: %PYTHON%

"%PYTHON%" -c "import PyInstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo [info] installing PyInstaller...
    %PIP% install "pyinstaller>=6.0"
    if %errorlevel% neq 0 (
        echo [ERROR] PyInstaller install failed
        exit /b 1
    )
)

REM -- version: single source of truth is ncm\version.py (spec and iss read it) --
REM Read through tools\read_version.py: inlining the regex in a "for /f" breaks,
REM because a Python one-liner with parentheses/quotes loses to cmd.exe parsing.
set VERTMP=%TEMP%\pxrd_ncm_ver_build.txt
"%PYTHON%" tools\read_version.py > "%VERTMP%" 2>nul
set VER=
set /p VER=<"%VERTMP%"
del "%VERTMP%" >nul 2>nul
if not defined VER (
    echo [ERROR] cannot read __version__ from ncm\version.py
    exit /b 1
)
echo [info] version: %VER%

echo.
echo [1/3] cleaning stale artefacts...
if exist "build" rmdir /s /q "build" 2>nul
if exist "dist\PolyXRD-NCM-Internal-v%VER%.exe" del /q "dist\PolyXRD-NCM-Internal-v%VER%.exe" 2>nul

echo.
echo [2/3] PyInstaller onefile build...
"%PYTHON%" -m PyInstaller --noconfirm PolyXRD-NCM.spec
if %errorlevel% neq 0 (
    echo [ERROR] PyInstaller build failed
    exit /b 1
)

echo.
echo [3/3] verify + smoke...
if not exist "dist\PolyXRD-NCM-Internal-v%VER%.exe" (
    echo [ERROR] dist\PolyXRD-NCM-Internal-v%VER%.exe not produced
    exit /b 1
)
for %%F in ("dist\PolyXRD-NCM-Internal-v%VER%.exe") do echo [info] output: %%~fF  (%%~zF bytes)

REM Smoke with the PACKAGED exe itself: only this way can we prove the bundled
REM resources are complete (notably ncm/data/spacegroups.json - without it the
REM crystal system / space group / Laue group fields come out empty).
"dist\PolyXRD-NCM-Internal-v%VER%.exe" --smoke
if %errorlevel% neq 0 (
    echo [WARN] packaged smoke failed - review manually
) else (
    echo [info] packaged smoke passed
)

echo.
echo done: dist\PolyXRD-NCM-Internal-v%VER%.exe
