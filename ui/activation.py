"""
PT AI Voice — Activation Screen
Hiện khi chưa có license hoặc key không hợp lệ.

Ported từ Auto-YTB — adapt app name + font (PT-AI-Voice không có ui.constants).
"""

import threading

import customtkinter as ctk

_FONT = "Segoe UI"


class ActivationWindow(ctk.CTk):
    """Cửa sổ kích hoạt license — hiện trước khi vào app chính.

    Sau khi kích hoạt thành công: self.should_launch = True → main.py sẽ
    launch App(). Nếu user đóng window không activate: should_launch = False
    → main.py exit.
    """

    def __init__(self, initial_status: str = "no_key", user_name: str = ""):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.should_launch = False
        self._initial_status = initial_status
        self._user_name = user_name

        self.title("PT AI Voice — Kích hoạt")
        self.geometry("480x520")
        self.resizable(False, False)
        self._center_window()
        self._build_ui()
        self._show_initial_message()

    # ── Căn giữa màn hình ────────────────────────────────────────────────────

    def _center_window(self):
        self.update_idletasks()
        w, h = 480, 520
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = (sw - w) // 2, (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, height=60, corner_radius=0,
                              fg_color=("#1565c0", "#0d2137"))
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text="  🎙 PT AI Voice",
            font=(_FONT, 17, "bold"), text_color="white",
        ).pack(side="left", padx=16, pady=12)

        # Body
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=30, pady=24)

        # Icon + Title
        ctk.CTkLabel(body, text="🔑", font=(_FONT, 36)).pack(pady=(0, 8))

        ctk.CTkLabel(
            body, text="Kích hoạt phần mềm",
            font=(_FONT, 17, "bold"),
        ).pack()

        ctk.CTkLabel(
            body,
            text="Nhập License Key được cấp để sử dụng PT AI Voice.",
            font=(_FONT, 12),
            text_color=("gray50", "gray60"),
            wraplength=380,
        ).pack(pady=(4, 20))

        # Status message (thay đổi tùy lỗi)
        self._status_label = ctk.CTkLabel(
            body, text="",
            font=(_FONT, 12, "bold"),
            text_color="#ef4444",
            wraplength=380,
        )
        self._status_label.pack(pady=(0, 8))

        # Key input
        ctk.CTkLabel(body, text="License Key:", font=(_FONT, 13),
                     anchor="w").pack(fill="x")
        self._key_entry = ctk.CTkEntry(
            body,
            placeholder_text="Ví dụ: PTAV-XXXX-XXXX-XXXX",
            font=(_FONT, 13),
            height=44,
            justify="center",
        )
        self._key_entry.pack(fill="x", pady=(4, 16))
        self._key_entry.bind("<Return>", lambda e: self._do_activate())

        # Nút kích hoạt
        self._activate_btn = ctk.CTkButton(
            body,
            text="🔓  Kích hoạt",
            font=(_FONT, 13, "bold"),
            height=46,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._do_activate,
        )
        self._activate_btn.pack(fill="x")

        # Spinner label (hiện khi đang verify)
        self._loading_label = ctk.CTkLabel(
            body, text="",
            font=(_FONT, 11),
            text_color=("gray50", "gray60"),
        )
        self._loading_label.pack(pady=(8, 0))

        # Đường kẻ + liên hệ
        ctk.CTkFrame(body, height=1, fg_color=("gray75", "gray30")).pack(
            fill="x", pady=(20, 12)
        )
        ctk.CTkLabel(
            body,
            text="Chưa có key? Liên hệ để được cấp quyền sử dụng.",
            font=(_FONT, 11),
            text_color=("gray50", "gray60"),
            wraplength=380,
        ).pack()

    # ── Hiện thông báo ban đầu tùy trạng thái ────────────────────────────────

    def _show_initial_message(self):
        msgs = {
            "revoked": (
                "⛔ Tài khoản của bạn đã bị vô hiệu hóa.\n"
                "Liên hệ để được hỗ trợ."
            ),
            "not_found": "❌ Key không hợp lệ. Vui lòng kiểm tra lại.",
            "offline": (
                "📵 Không có kết nối mạng và cache đã hết hạn.\n"
                "Vui lòng kết nối internet để xác thực."
            ),
        }
        msg = msgs.get(self._initial_status, "")
        if msg:
            self._status_label.configure(text=msg, text_color="#ef4444")

    # ── Xử lý kích hoạt ──────────────────────────────────────────────────────

    def _do_activate(self):
        key = self._key_entry.get().strip()
        if not key:
            self._set_status("⚠️ Vui lòng nhập License Key.", "#f59e0b")
            return

        # Disable UI, hiện loading
        self._activate_btn.configure(state="disabled", text="⏳  Đang xác thực...")
        self._loading_label.configure(text="Đang kiểm tra với máy chủ...")
        self._set_status("", "#ef4444")

        threading.Thread(target=self._verify_worker, args=(key,), daemon=True).start()

    def _verify_worker(self, key: str):
        from core.license import activate
        status, name = activate(key)
        self.after(0, self._on_verify_result, status, name)

    def _on_verify_result(self, status: str, name: str):
        self._activate_btn.configure(state="normal", text="🔓  Kích hoạt")
        self._loading_label.configure(text="")

        if status == "active":
            self._user_name = name
            self._set_status(
                f"✅ Kích hoạt thành công! Xin chào {name}." if name else
                "✅ Kích hoạt thành công!",
                "#22c55e",
            )
            self.after(1200, self._launch_app)

        elif status == "revoked":
            self._set_status(
                "⛔ Tài khoản này đã bị vô hiệu hóa.\nVui lòng liên hệ để được hỗ trợ.",
                "#ef4444",
            )

        elif status == "not_found":
            self._set_status("❌ Key không tồn tại. Kiểm tra lại.", "#ef4444")

        elif status == "max_devices":
            self._set_status(
                "🚫 Key này đã dùng trên tối đa số thiết bị cho phép.\n"
                "Liên hệ để nâng giới hạn hoặc gỡ thiết bị cũ.",
                "#ef4444",
            )

        elif status == "error":
            self._set_status(
                "📵 Không thể kết nối máy chủ.\nKiểm tra kết nối internet và thử lại.",
                "#f59e0b",
            )

        else:
            self._set_status("❌ Key không hợp lệ.", "#ef4444")

    def _set_status(self, text: str, color: str):
        self._status_label.configure(text=text, text_color=color)

    def _launch_app(self):
        self.should_launch = True
        self.quit()
        self.destroy()
