@echo off
cd /d "%~dp0"
py -m pip install -r requirements.txt pytest
if errorlevel 1 exit /b %errorlevel%
py -m pytest -q
