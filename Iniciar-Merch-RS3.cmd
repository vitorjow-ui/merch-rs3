@echo off
setlocal
set "MERCH_OPEN_BROWSER=1"
python "%~dp0server.py"
if errorlevel 1 pause

