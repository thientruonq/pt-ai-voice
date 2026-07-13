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
        "cryptography": "cryptography",
    }
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


def _license_gate() -> tuple:
    """Kiểm tra license trước khi vào app.

    Trả về (should_launch: bool, user_name: str, license_status: str).
    should_launch = False → main() thoát (user đóng activation window).
    """
    from core.license import check_license_fast, check_license

    # Fast path: chỉ đọc cache local (~5ms, không mạng)
    status, name = check_license_fast()

    if status == "active":
        # Cache còn hạn → vào app ngay. Verify online chạy background trong app.
        return (True, name, status)

    if status == "expired":
        # Cache hết hạn → blocking online verify
        status, name = check_license()

    if status in ("no_key", "revoked", "not_found", "offline"):
        # Chưa activate hoặc bị chặn → mở activation window
        from ui.activation import ActivationWindow
        win = ActivationWindow(initial_status=status, user_name=name)
        win.mainloop()
        if not win.should_launch:
            return (False, "", status)  # user đóng, không activate
        name = getattr(win, "_user_name", name)
        status = "active"

    return (True, name, status)


def main():
    # Kiểm tra thư viện
    missing = check_dependencies()
    if missing:
        print(f"[Error] Thiếu thư viện: {', '.join(missing)}")
        print(f"Chạy lệnh: pip install {' '.join(missing)}")

        import subprocess
        ans = input("Tự động cài đặt bây giờ? (y/n): ").strip().lower()
        if ans == "y":
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        else:
            sys.exit(1)

    # License gate — chặn app nếu chưa activate / bị revoke / offline hết hạn
    should_launch, user_name, license_status = _license_gate()
    if not should_launch:
        sys.exit(0)

    # Khởi chạy GUI
    from ui.app import App
    app = App(user_name=user_name, license_status=license_status)
    app.mainloop()


if __name__ == "__main__":
    main()
