@echo off
chcp 65001 >nul
title PT AI Voice

:: Chạy từ thư mục chứa file này
cd /d "%~dp0"

python main.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Khởi chạy thất bại. Hãy chạy install_windows.bat trước.
    pause
)
