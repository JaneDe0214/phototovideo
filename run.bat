@echo off
chcp 65001 >nul
title 相簿轉 8K/4K YouTube 極致備份影片合成工具

set PYTHON_CMD=python
where python >nul 2>nul
if %errorlevel% neq 0 (
    if exist "%LOCALAPPDATA%\Python\pythoncore-3.11-64\python.exe" (
        set PYTHON_CMD="%LOCALAPPDATA%\Python\pythoncore-3.11-64\python.exe"
    ) else if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
        set PYTHON_CMD="%LOCALAPPDATA%\Python\bin\python.exe"
    )
)

echo [資訊] 正在啟動 8K/4K 極致備份影片合成工具...
%PYTHON_CMD% app.py

if %errorlevel% neq 0 (
    echo [錯誤] 程式執行出現異常，請檢查上方訊息。
    pause
)
