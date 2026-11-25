@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import webview, uvicorn, fastapi" >nul 2>nul
if errorlevel 1 (
  echo Installing Planline desktop requirements...
  py -3 -m pip install -r requirements-desktop.txt
  if errorlevel 1 exit /b 1
)
py -3 -m planline.desktop
