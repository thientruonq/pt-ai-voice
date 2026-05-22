#!/bin/bash
# PT AI Voice — macOS Installer

echo "================================================"
echo "  PT AI Voice — macOS Installer"
echo "================================================"
echo ""

# Kiểm tra Python 3
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Không tìm thấy Python 3!"
    echo "Cài đặt bằng Homebrew: brew install python3"
    echo "Hoặc tải tại: https://www.python.org/downloads/"
    exit 1
fi

echo "[OK] Python: $(python3 --version)"
echo ""

# Kiểm tra ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "[WARNING] Không tìm thấy ffmpeg!"
    echo "Cài đặt: brew install ffmpeg"
    echo ""
    read -p "Tự động cài ffmpeg qua Homebrew? (y/n): " ans
    if [ "$ans" = "y" ]; then
        if command -v brew &> /dev/null; then
            brew install ffmpeg
        else
            echo "Homebrew chưa cài. Tải tại: https://brew.sh"
        fi
    fi
fi

# Cài Python packages
echo "Đang cài đặt thư viện Python..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "[ERROR] Cài đặt thất bại!"
    exit 1
fi

echo ""
echo "================================================"
echo "  Cài đặt hoàn tất!"
echo "  Chạy tool bằng: ./run_mac.sh"
echo "================================================"
