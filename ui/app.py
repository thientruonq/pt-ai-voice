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
    def __init__(self):
        self.config = ConfigManager()

        # Áp dụng theme trước khi tạo window
        ctk.set_appearance_mode(self.config.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        super().__init__()
        self.title(f"{APP_TITLE}  v{APP_VERSION}")
        self.geometry(WIN_SIZE)
        self.minsize(*MIN_SIZE)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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

    def _on_close(self):
        self.config.save()
        self.destroy()
