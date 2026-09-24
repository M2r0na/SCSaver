@echo off
setlocal
cd /d "%~dp0"

call build_app.bat
if errorlevel 1 exit /b 1

set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
  echo Inno Setup 6 was not found.
  echo Install Inno Setup 6, then run this file again.
  pause
  exit /b 1
)

if exist SCSaver.ico (
  "%ISCC%" /DSetupIconFile="SCSaver.ico" SCSaverInstaller.iss
) else (
  "%ISCC%" SCSaverInstaller.iss
)
if errorlevel 1 goto :error

echo.
echo Setup build complete:
echo installer_output\SCSaver_Setup_v0.10.0.exe
pause
exit /b 0

:error
echo Setup build failed.
pause
exit /b 1
