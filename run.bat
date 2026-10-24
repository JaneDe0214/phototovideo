@echo off
cd /d "%~dp0"

set "PY="

if exist "%LOCALAPPDATA%\Python\pythoncore-3.11-64\python.exe" (
    set "PY=%LOCALAPPDATA%\Python\pythoncore-3.11-64\python.exe"
    goto :FOUND
)

if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    set "PY=%LOCALAPPDATA%\Python\bin\python.exe"
    goto :FOUND
)

where py.exe >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=py"
    goto :FOUND
)

where python.exe >nul 2>&1
if %errorlevel% equ 0 (
    set "PY=python"
    goto :FOUND
)

:NOTFOUND
echo [ERROR] Python not found. Please install Python 3.11 or check your path.
pause
exit /b 1

:FOUND
echo [INFO] Starting PhotoToVideo GUI with: %PY%
"%PY%" app.py %*
if %errorlevel% neq 0 (
    echo [ERROR] Application exited with error code %errorlevel%.
    pause
)
