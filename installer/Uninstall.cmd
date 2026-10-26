@echo off
rem Call Copilot uninstaller launcher. The uninstaller deletes the app folder together with this file,
rem so the work continues from a copy in %TEMP% (a batch started without CALL never returns to the original).
if "%~1"=="--from-temp" goto run
copy /y "%~dp0uninstall.ps1" "%TEMP%\CallCopilot-uninstall.ps1" >nul
copy /y "%~f0" "%TEMP%\CallCopilot-Uninstall.cmd" >nul
cd /d "%TEMP%"
"%TEMP%\CallCopilot-Uninstall.cmd" --from-temp "%~dp0." %*
:run
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\CallCopilot-uninstall.ps1" -Dest "%~2" -Relocated %3 %4 %5 %6
