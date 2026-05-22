#!/bin/bash
# PT AI Voice — Run with Virtual Environment

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "[ERROR] Virtual environment chưa tạo!"
    echo "Chạy: /opt/homebrew/opt/python@3.12/bin/python3.12 -m venv venv"
    exit 1
fi

source venv/bin/activate
python main.py
