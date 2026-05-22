"""
PT AI Voice — Entry point
Cross-platform: Windows & macOS
"""
import sys
import os

# Thêm thư mục gốc vào sys.path để import hoạt động đúng
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def check_dependencies() -> list[str]:
    """Kiểm tra các thư viện cần thiết"""
    missing = []
    required = {
        "customtkinter": "customtkinter",
        "edge_tts": "edge-tts",
    }
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


def main():
    # Kiểm tra thư viện
    missing = check_dependencies()
    if missing:
        print(f"[Error] Thiếu thư viện: {', '.join(missing)}")
        print(f"Chạy lệnh: pip install {' '.join(missing)}")

        # Hỏi auto-install nếu chạy trực tiếp
        import subprocess
        ans = input("Tự động cài đặt bây giờ? (y/n): ").strip().lower()
        if ans == "y":
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        else:
            sys.exit(1)

    # Khởi chạy GUI
    from ui.app import App
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
