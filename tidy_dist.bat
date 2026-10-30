@echo off
REM Keep exactly TWO deliverables in dist\ :
REM   dist\PolyXRD-NCM-Internal-vX.Y.Z.exe   internal evaluation edition (onefile)
REM   dist\PolyXRD-NCM-vX.Y.Z-Setup.exe      installer (payload = the exe above)
REM Everything else is deleted: older versions and any fixed-name copy.
REM
REM Usage:  tidy_dist.bat            keep the current version, delete the rest
REM         tidy_dist.bat dry        only list what would be deleted
REM         (use "dry", not "/dry": Git-Bash rewrites a single-slash argument
REM          into a Windows path, so "/dry" would silently mean "delete".)
REM
REM NOTE: keep this file pure ASCII (cmd.exe reads .bat in OEM cp936 here).
setlocal
cd /d %~dp0

set DRY=0
if /i "%~1"=="dry" set DRY=1
if /i "%~1"=="--dry" set DRY=1

set PYTHONUNBUFFERED=1
set PY=D:\Project\XRD\python310\python.exe
if not exist "%PY%" set PY=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe
if not exist "%PY%" set PY=python

REM Version is read through tools\read_version.py, NOT by importing ncm.version:
REM importing the package pulls numpy/scipy/Qt. Inlining the regex in a
REM "for /f" also breaks - cmd.exe chokes on the parentheses and quotes.
set VERTMP=%TEMP%\pxrd_ncm_ver.txt
"%PY%" tools\read_version.py > "%VERTMP%" 2>nul
set RAW=
set /p RAW=<"%VERTMP%"
del "%VERTMP%" >nul 2>nul

if "%RAW%"=="" (
    echo [ERROR] cannot read version from ncm/version.py - nothing deleted.
    endlocal
    exit /b 1
)

set "KEEP1=PolyXRD-NCM-Internal-v%RAW%.exe"
set "KEEP2=PolyXRD-NCM-v%RAW%-Setup.exe"

if not exist "dist\%KEEP1%" (
    echo [ERROR] dist\%KEEP1% is missing - nothing deleted.
    echo         Build it first ^(build_exe.bat^).
    endlocal
    exit /b 1
)
if not exist "dist\%KEEP2%" (
    echo [ERROR] dist\%KEEP2% is missing - nothing deleted.
    echo         Build the installer first ^(build_setup.bat^).
    endlocal
    exit /b 1
)

if "%DRY%"=="1" (
    echo [dry] version %RAW% - these would be deleted:
) else (
    echo Tidying dist\ for version %RAW% ...
)

set RM=0
for %%F in ("dist\*.exe") do (
    if /i not "%%~nxF"=="%KEEP1%" if /i not "%%~nxF"=="%KEEP2%" (
        echo   - %%~nxF
        if "%DRY%"=="0" del /f /q "%%~fF" >nul 2>nul
        set /a RM+=1
    )
)

if "%DRY%"=="1" (
    echo [dry] %RM% file^(s^) would be removed.
    endlocal
    exit /b 0
)

echo.
echo dist\ now holds:
for %%F in ("dist\*.exe") do echo   %%F
echo Removed %RM% file^(s^).
endlocal
exit /b 0
