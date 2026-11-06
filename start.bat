@echo off
title DeLector - 德语欧标沉浸阅读工作台
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" start.py
pause
