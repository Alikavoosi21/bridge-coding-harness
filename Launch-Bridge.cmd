@echo off
cd /d "%~dp0"
set "PATH=E:\DockerDesktop\resources\bin;%PATH%"
node scripts/desktop.cjs run
if errorlevel 1 pause
