#!/bin/bash
# PT AI Voice — macOS Launcher

# Chạy từ thư mục chứa script
cd "$(dirname "$0")"

python3 main.py

if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Khởi chạy thất bại. Hãy chạy install_mac.sh trước."
    read -p "Nhấn Enter để thoát..."
fi
