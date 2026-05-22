@echo off
chcp 65001 >nul
title PT AI Voice — Build Executable
cd /d "%~dp0"

echo ════════════════════════════════════════════════════
echo   🎙 PT AI Voice — Đóng gói ứng dụng Windows
echo ════════════════════════════════════════════════════
echo.

:: ── Kiểm tra Python ──────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Không tìm thấy Python! Cần Python 3.10+
    pause
    exit /b 1
)
echo [OK] Python:
python --version
echo.

:: ── Kiểm tra PyInstaller ─────────────────────────────────────────────────
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Đang cài PyInstaller...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [ERROR] Không cài được PyInstaller!
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller:
python -m PyInstaller --version
echo.

:: ── Cài dependencies ─────────────────────────────────────────────────────
echo [1/3] Đang cài thư viện cần thiết...
pip install -r requirements.txt --quiet
echo [OK] Dependencies installed
echo.

:: ── Xoá build cũ ─────────────────────────────────────────────────────────
echo [2/3] Dọn build cũ...
if exist "dist\PT AI Voice" rmdir /s /q "dist\PT AI Voice"
if exist "build" rmdir /s /q "build"
echo [OK] Clean
echo.

:: ── Build ─────────────────────────────────────────────────────────────────
echo [3/3] Đang build executable... (có thể mất 2-5 phút)
echo.
python -m PyInstaller build_windows.spec --noconfirm

if %errorlevel% neq 0 (
    echo.
    echo ════════════════════════════════════════════════════
    echo   [ERROR] Build thất bại!
    echo ════════════════════════════════════════════════════
    pause
    exit /b 1
)

:: ── Tạo config mẫu cho user ──────────────────────────────────────────────
echo.
echo Đang tạo file config mẫu cho user...

:: Tạo voice_config.json mặc định (không chứa path cá nhân)
python -c "import json; c={'tts_engine':'edge','voice_id':'vi-VN-HoaiMyNeural','speed':'+0%%','volume':'+0%%','pitch':'+0Hz','output_format':'mp3','output_dir':'','theme':'dark','azure_credentials':{'subscription_key':'','region':'eastasia','style':''},'google_credentials':{'type':'service_account','project_id':'','private_key_id':'','private_key':'','client_email':'','client_id':'','auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','client_x509_cert_url':'','universe_domain':'googleapis.com'},'advanced':{'silence_between_segments':True,'silence_duration_ms':300,'use_srt_timing':True,'trim_silence':True,'remove_special_chars':True,'max_chars_per_segment':500,'max_workers':5,'ffmpeg_path':'','rate_limit':1.0}}; open(r'dist\PT AI Voice\voice_config.json','w',encoding='utf-8').write(json.dumps(c,indent=2,ensure_ascii=False))"

echo.
echo ════════════════════════════════════════════════════
echo   ✅ BUILD THÀNH CÔNG!
echo.
echo   📁 Output: dist\PT AI Voice\
echo   🚀 Chạy thử: dist\PT AI Voice\PT AI Voice.exe
echo.
echo   ⚠ Lưu ý: Nếu dùng tính năng ghép audio,
echo     cần đặt ffmpeg.exe vào thư mục "dist\PT AI Voice\"
echo     Tải ffmpeg: https://www.gyan.dev/ffmpeg/builds/
echo ════════════════════════════════════════════════════
echo.
pause
