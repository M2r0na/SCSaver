@echo off
setlocal
cd /d "%~dp0"

py -3.12 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.12 is required.
  pause
  exit /b 1
)

py -3.12 -m pip install -r requirements-setup.txt
if errorlevel 1 goto :error

if exist build rmdir /s /q build
if exist "dist\SCSaver" rmdir /s /q "dist\SCSaver"
if exist SCSaver.spec del /q SCSaver.spec

set ICON_ARGS=
if exist SCSaver.ico set ICON_ARGS=--icon "SCSaver.ico" --add-data "SCSaver.ico;."

py -3.12 -m PyInstaller --noconfirm --clean --onedir --windowed ^
  --name SCSaver ^
  %ICON_ARGS% ^
  SCSaverLauncher_v0.10.1_auto_login_logging.py
if errorlevel 1 goto :error

echo Application build complete: dist\SCSaver\SCSaver.exe
exit /b 0

:error
echo Application build failed.
pause
exit /b 1
