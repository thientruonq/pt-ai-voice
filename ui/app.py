"""
Main App Window — Cửa sổ chính với tab navigation
"""
import customtkinter as ctk

from core.config_manager import ConfigManager
from ui.tabs.tab_srt import SRTTab
from ui.tabs.tab_settings import SettingsTab

APP_TITLE = "PT AI Voice"
APP_VERSION = "2.0.0"
WIN_SIZE = "900x620"
MIN_SIZE = (780, 540)


class App(ctk.CTk):
    def __init__(self, user_name: str = "", license_status: str = "active"):
        self.config = ConfigManager()
        self._user_name = user_name
        self._license_status = license_status

        # Áp dụng theme trước khi tạo window
        ctk.set_appearance_mode(self.config.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        super().__init__()
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry(WIN_SIZE)
        self.minsize(*MIN_SIZE)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Nếu vào app với cache active → verify online background (không block UI)
        if license_status == "active":
            import threading
            threading.Thread(target=self._bg_license_verify, daemon=True).start()
        # Sau 24h → recheck license (revoke phát hiện tối đa 24h delay)
        self.after(24 * 3600 * 1000, self._periodic_license_check)

    def _build_ui(self):
        # ── Header ─────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, height=50, corner_radius=0,
                              fg_color=("#1565c0", "#0d2137"))
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text=f"  🎙 {APP_TITLE}",
            font=("Segoe UI", 16, "bold"),
            text_color="white",
        ).pack(side="left", padx=12)

        # Engine badge
        self.engine_badge = ctk.CTkLabel(
            header,
            text=f"  Engine: {self.config.get('tts_engine','edge').upper()}  ",
            font=("Segoe UI", 11),
            fg_color=("#0d47a1", "#1a3a5c"),
            corner_radius=6,
            text_color="#90caf9",
        )
        self.engine_badge.pack(side="left", padx=8)

        # ── Tab view ───────────────────────────────────────────────────────
        self.tabs = ctk.CTkTabview(self, anchor="nw")
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        self.tabs.add("📄 Tạo Audio từ File")
        self.tabs.add("⚙ Cài đặt")

        # Khởi tạo từng tab
        SRTTab(
            self.tabs.tab("📄 Tạo Audio từ File"),
            config=self.config,
            status_cb=self._set_status,
        ).pack(fill="both", expand=True)

        SettingsTab(
            self.tabs.tab("⚙ Cài đặt"),
            config=self.config,
            status_cb=self._set_status,
        ).pack(fill="both", expand=True)

        # ── Status bar ─────────────────────────────────────────────────────
        sb = ctk.CTkFrame(self, height=28, corner_radius=0,
                          fg_color=("#e3e3e3", "#1a1a1a"))
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            sb, text="Sẵn sàng",
            font=("Segoe UI", 11),
            text_color=("#333", "#aaa"),
        )
        self.status_label.pack(side="left", padx=10)

        ctk.CTkLabel(
            sb,
            text=f"v{APP_VERSION}  |  Windows & macOS",
            font=("Segoe UI", 10),
            text_color="gray",
        ).pack(side="right", padx=10)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _set_status(self, message: str, color: str = "white"):
        color_map = {
            "green": "#4caf50",
            "yellow": "#ffc107",
            "red": "#f44336",
            "white": ("#333", "#ccc"),
        }
        self.status_label.configure(
            text=f"  {message}",
            text_color=color_map.get(color, color),
        )
        # Refresh engine badge
        engine = self.config.get("tts_engine", "edge").upper()
        self.engine_badge.configure(text=f"  Engine: {engine}  ")

    # ── License checks ─────────────────────────────────────────────────────

    def _bg_license_verify(self):
        """Background verify online sau khi app đã start (không block UI).
        Nếu key bị revoke → close app ngay."""
        try:
            from core.license import check_license
            status, _ = check_license()
            if status in ("revoked", "not_found"):
                self.after(0, self._handle_license_lost, status)
        except Exception as e:
            print(f"[License] bg verify fail: {e}")

    def _periodic_license_check(self):
        """Recheck 24h/lần trong background thread."""
        import threading
        threading.Thread(target=self._bg_license_verify, daemon=True).start()
        # Schedule tiếp check sau 24h nữa
        self.after(24 * 3600 * 1000, self._periodic_license_check)

    def _handle_license_lost(self, status: str):
        """Key bị revoke/not_found → thông báo + đóng app."""
        from tkinter import messagebox
        msg = {
            "revoked": "License đã bị thu hồi.\nApp sẽ đóng lại.",
            "not_found": "License không còn hợp lệ.\nApp sẽ đóng lại.",
        }.get(status, "License không hợp lệ.\nApp sẽ đóng lại.")
        try:
            messagebox.showerror("License", msg)
        except Exception:
            pass
        self.destroy()

    def _on_close(self):
        # Tắt sidecar VieNeu nếu đang chạy (process leak nếu skip)
        try:
            from core.vieneu_tts import stop_sidecar
            stop_sidecar()
        except Exception:
            pass
        self.config.save()
        self.destroy()
