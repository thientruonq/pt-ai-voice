@echo off
chcp 65001 >nul
title PT AI Voice — Cài đặt

echo ================================================
echo   PT AI Voice — Windows Installer
echo ================================================
echo.

:: Kiểm tra Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Không tìm thấy Python!
    echo Tải Python tại: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Đã tìm thấy Python:
python --version
echo.

:: Cài đặt thư viện
echo Đang cài đặt thư viện...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Cài đặt thất bại!
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Cài đặt hoàn tất!
echo   Chạy tool bằng: run_windows.bat
echo ================================================
pause
