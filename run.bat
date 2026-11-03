@echo off
rem Aetherion OmniForge - local bootstrap for Windows.
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3.11+ is required. Install it from https://www.python.org/downloads/ and retry.
    exit /b 1
  )
  set "PY=python"
) else (
  set "PY=py -3"
)

if not exist .venv (
  echo Creating local virtual environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --disable-pip-version-check --quiet -e .
if errorlevel 1 exit /b 1
python aetherion.py %*
