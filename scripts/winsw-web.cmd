@echo off
setlocal
cd /d "%~dp0\.."
if not exist "logs" mkdir "logs"

set PYTHONUNBUFFERED=1
set THEOOS_SERVICE=1

if not defined THEOOS_PYTHON (
  set "THEOOS_PYTHON=C:\Users\Leand\AppData\Local\Programs\Python\Python313\python.exe"
)

if not exist "%THEOOS_PYTHON%" (
  echo [%date% %time%] Python nao encontrado: %THEOOS_PYTHON%>>logs\service-error.log
  exit /b 1
)

"%THEOOS_PYTHON%" -u app.py
exit /b %ERRORLEVEL%
