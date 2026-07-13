"""
Tab Cài đặt — Cấu hình engine, credentials, advanced options
"""
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog, messagebox
import json

from core.config_manager import ConfigManager


def _get_downloads_dir() -> str:
    """Trả về thư mục Downloads của hệ thống (cross-platform, tránh OneDrive redirect)."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Downloads")
    return str(Path.home() / "Downloads")


class SettingsTab(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, restart_cb=None, status_cb=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self.restart_cb = restart_cb
        self.status_cb = status_cb
        self._build_ui()
        # Hide/show VieNeu buttons + ẩn sliders nếu engine = vieneu
        self.after(100, self._refresh_engine_specific_ui)
        # Ẩn section FFmpeg nếu app tự tìm được (giảm rối UI)
        self.after(100, self._maybe_hide_ffmpeg_section)
        # Tự động tải giọng sau khi UI dựng xong (silent: bỏ qua cảnh báo OmniVoice rỗng)
        self.after(300, lambda: self._load_voices(show_warnings=False))

    def _build_ui(self):
        # Scrollable frame
        scroll = ctk.CTkScrollableFrame(self, label_text="")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Engine ────────────────────────────────────────────────────────
        self._section(scroll, "🔊 Engine TTS")

        eng_row = ctk.CTkFrame(scroll, fg_color="transparent")
        eng_row.pack(fill="x", padx=8, pady=4)

        self.engine_var = ctk.StringVar(value=self.config.get("tts_engine", "edge"))
        ctk.CTkLabel(eng_row, text="Engine:", width=120, anchor="w").grid(row=0, column=0)
        ctk.CTkRadioButton(
            eng_row, text="Edge TTS (Miễn phí)", variable=self.engine_var, value="edge",
            command=self._on_engine_change,
        ).grid(row=0, column=1, padx=8)
        ctk.CTkRadioButton(
            eng_row, text="Google Cloud TTS", variable=self.engine_var, value="google",
            command=self._on_engine_change,
        ).grid(row=0, column=2, padx=8)
        ctk.CTkRadioButton(
            eng_row, text="🎭 OmniVoice (Colab)", variable=self.engine_var, value="omnivoice",
            fg_color="#7c3aed", hover_color="#5b21b6",
            command=self._on_engine_change,
        ).grid(row=0, column=3, padx=8)
        ctk.CTkRadioButton(
            eng_row, text="🇻🇳 VieNeu (Offline)", variable=self.engine_var, value="vieneu",
            fg_color="#a855f7", hover_color="#9333ea",
            command=self._on_engine_change,
        ).grid(row=0, column=4, padx=8)

        # VieNeu action buttons (Tạo giọng / Gỡ / chỉ báo CPU-GPU) — hide khi engine khác
        self._vn_clone_btn = ctk.CTkButton(
            eng_row, text="🎤 Tạo giọng", width=110, height=26,
            command=self._vieneu_open_clone_dialog,
            fg_color="#a855f7", hover_color="#9333ea", font=("Segoe UI", 11, "bold"),
        )
        self._vn_uninstall_btn = ctk.CTkButton(
            eng_row, text="🗑 Gỡ VieNeu", width=110, height=26,
            command=self._vieneu_uninstall,
            fg_color="#dc2626", hover_color="#b91c1c", font=("Segoe UI", 11),
        )
        self._vn_hw_label = ctk.CTkLabel(eng_row, text="", font=("Segoe UI", 11),
                                          text_color="#94a3b8")

        # ── Voice & Speed ─────────────────────────────────────────────────
        self._section(scroll, "🎙 Giọng đọc & Tốc độ")

        vs = ctk.CTkFrame(scroll, fg_color="transparent")
        vs.pack(fill="x", padx=8, pady=4)

        # Language selector
        ctk.CTkLabel(vs, text="Ngôn ngữ:", width=130, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        
        self.languages = {
            "🇺🇸 English (US)": "en-US",
            "🇬🇧 English (UK)": "en-GB",
            "🇦🇺 English (AU)": "en-AU",
            "🇻🇳 Tiếng Việt": "vi-VN",
            "🇯🇵 日本語 Japanese": "ja-JP",
            "🇨🇳 中文 Chinese": "zh-CN",
            "🇰🇷 한국어 Korean": "ko-KR",
            "🇪🇸 Español (Spain)": "es-ES",
            "🇲🇽 Español (Mexico)": "es-MX",
            "🇫🇷 Français": "fr-FR",
            "🇩🇪 Deutsch": "de-DE",
            "🇷🇺 Русский": "ru-RU",
            "🇸🇦 العربية Arabic": "ar-SA",
            "🇮🇳 हिन्दी Hindi": "hi-IN",
            "🇹🇭 ไทย Thai": "th-TH",
            "🇮🇩 Indonesia": "id-ID",
            "🇵🇹 Português (BR)": "pt-BR",
            "🇮🇹 Italiano": "it-IT",
            "🇳🇱 Nederlands": "nl-NL",
            "🇵🇱 Polski": "pl-PL",
            "🇹🇷 Türkçe": "tr-TR",
        }
        
        # Lấy ngôn ngữ mặc định từ voice_id
        current_voice = self.config.get("voice_id", "vi-VN-HoaiMyNeural")
        default_lang = "🇻🇳 Tiếng Việt"
        for display, code in self.languages.items():
            if current_voice.startswith(code):
                default_lang = display
                break
        
        self.lang_var = ctk.StringVar(value=default_lang)
        self.lang_combo = ctk.CTkComboBox(
            vs, variable=self.lang_var, width=200,
            values=list(self.languages.keys()),
            command=self._on_language_change,
        )
        self.lang_combo.grid(row=0, column=1, sticky="w", padx=4)

        self.btn_load_voices = ctk.CTkButton(
            vs, text="↺ Tải giọng", width=100, command=self._load_voices
        )
        self.btn_load_voices.grid(row=0, column=2, padx=8)

        # Voice selector
        ctk.CTkLabel(vs, text="Giọng đọc:", width=130, anchor="w").grid(row=1, column=0, sticky="w", pady=3)
        self._voice_map: dict = {}  # display_label → voice_id
        self.voice_combo = ctk.CTkComboBox(
            vs, width=400, values=[current_voice],
        )
        self.voice_combo.set(current_voice)
        self.voice_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=4, pady=3)

        self._slider_row(vs, "Speed (Edge):", "speed", 2, -50, 100, 5, "%")
        self._slider_row(vs, "Volume (Edge):", "volume", 3, -50, 50, 5, "%")
        self._slider_row(vs, "Pitch (Edge):", "pitch", 4, -20, 20, 1, "Hz")

        # ── Output Folder ─────────────────────────────────────────────────
        self._section(scroll, "📁 Thư mục lưu file")

        of = ctk.CTkFrame(scroll, fg_color="transparent")
        of.pack(fill="x", padx=8, pady=4)
        of.columnconfigure(1, weight=1)

        ctk.CTkLabel(of, text="Thư mục:", width=130, anchor="w").grid(row=0, column=0, sticky="w")
        saved_dir = self.config.get("output_dir", "") or _get_downloads_dir()
        self._output_dir_var = ctk.StringVar(value=saved_dir)
        self._output_dir_entry = ctk.CTkEntry(
            of, textvariable=self._output_dir_var, width=380,
            placeholder_text=_get_downloads_dir(),
        )
        self._output_dir_entry.grid(row=0, column=1, sticky="ew", padx=4)
        ctk.CTkButton(
            of, text="📂 Chọn", width=90, command=self._pick_output_dir
        ).grid(row=0, column=2, padx=(4, 0))

        # ── Theme ─────────────────────────────────────────────────────────
        self._section(scroll, "🎨 Giao diện")
        th = ctk.CTkFrame(scroll, fg_color="transparent")
        th.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(th, text="Theme:", width=120, anchor="w").grid(row=0, column=0)
        self.theme_var = ctk.StringVar(value=self.config.get("theme", "dark"))
        for i, t in enumerate(["dark", "light", "system"]):
            ctk.CTkRadioButton(
                th, text=t.capitalize(), variable=self.theme_var, value=t,
                command=self._apply_theme,
            ).grid(row=0, column=i + 1, padx=8)
        # ── OmniVoice Credentials ─────────────────────────────────────────
        self._omni_section_header = self._section(scroll, "🎭 OmniVoice (Colab) Credentials")

        ov = ctk.CTkFrame(scroll, fg_color="transparent")
        ov.pack(fill="x", padx=8, pady=4)
        ov.columnconfigure(1, weight=1)
        self._omni_section_frame = ov

        ctk.CTkLabel(ov, text="Server URL(s):", width=140, anchor="nw").grid(
            row=0, column=0, sticky="nw", pady=3)
        self._omni_endpoint_box = ctk.CTkTextbox(ov, height=70, width=380)
        self._omni_endpoint_box.grid(row=0, column=1, columnspan=2, sticky="ew", padx=4, pady=3)
        _omni_creds = self.config.get("omnivoice_credentials") or {}
        _omni_endpoint = _omni_creds.get("endpoint", "")
        if _omni_endpoint:
            self._omni_endpoint_box.insert("1.0", _omni_endpoint)

        ctk.CTkLabel(ov, text="Voice Kind:", width=140, anchor="w").grid(
            row=1, column=0, sticky="w", pady=3)
        self._omni_kind_var = ctk.StringVar(
            value=_omni_creds.get("voice_kind", "preset")
        )
        ctk.CTkOptionMenu(
            ov, values=["preset", "clone"], variable=self._omni_kind_var,
            width=140, command=lambda _: self._load_voices()
        ).grid(row=1, column=1, sticky="w", padx=4)

        ctk.CTkButton(
            ov, text="🔌 Test kết nối", width=140,
            fg_color="#7c3aed", hover_color="#5b21b6",
            command=self._test_omnivoice,
        ).grid(row=1, column=2, sticky="w", padx=4)

        ctk.CTkLabel(
            ov,
            text="ℹ️ Chạy OmniVoice-Colab-Server notebook → Run all → copy URL Cloudflare (*.trycloudflare.com)\n"
                 "Notebook hiện dùng Cloudflare Quick Tunnel (không cần token, không rate limit).\n"
                 "Vẫn chấp nhận URL ngrok / LocalTunnel — mỗi dòng 1 URL (pool tự rotate khi fail).",
            text_color="gray", font=("Segoe UI", 11), justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 6))

        # ── Google Credentials ────────────────────────────────────────────
        self._google_section_header = self._section(scroll, "☁ Google Cloud TTS Credentials")

        gc = ctk.CTkFrame(scroll, fg_color="transparent")
        gc.pack(fill="x", padx=8, pady=4)
        self._google_section_frame = gc

        ctk.CTkLabel(gc, text="File JSON:", width=120, anchor="w").grid(row=0, column=0)
        self.cred_label = ctk.CTkLabel(gc, text="Chưa nạp", text_color="gray", anchor="w")
        self.cred_label.grid(row=0, column=1, sticky="w", padx=4)
        ctk.CTkButton(gc, text="📂 Nạp file", width=100, command=self._load_google_json).grid(row=0, column=2, padx=8)

        # ── FFmpeg ────────────────────────────────────────────────────────
        # Save FFmpeg header làm mốc — OmniVoice/Google section re-pack
        # 'before' widget này để giữ đúng thứ tự khi user đổi engine.
        self._ffmpeg_section_header = self._section(scroll, "⚙ FFmpeg")
        ff = ctk.CTkFrame(scroll, fg_color="transparent")
        ff.pack(fill="x", padx=8, pady=4)
        self._ffmpeg_section_frame = ff
        ctk.CTkLabel(ff, text="Đường dẫn:", width=120, anchor="w").grid(row=0, column=0)
        self.ffmpeg_entry = ctk.CTkEntry(ff, width=300,
                                          placeholder_text="Để trống = tự tìm trong PATH")
        self.ffmpeg_entry.grid(row=0, column=1, padx=4)
        self.ffmpeg_entry.insert(0, self.config.get_adv("ffmpeg_path", ""))
        ctk.CTkButton(ff, text="Browse", width=80,
                      command=self._pick_ffmpeg).grid(row=0, column=2)
        # Hint chỉ hiện khi auto-detect fail — cho user biết vì sao section này bung ra
        self._ffmpeg_hint = ctk.CTkLabel(
            ff, text="⚠ Không tự tìm được ffmpeg — nhập đường dẫn thủ công.",
            text_color="#f59e0b", font=("Segoe UI", 11),
        )
        self._ffmpeg_hint.grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(4, 0))
        self._ffmpeg_hint.grid_remove()  # hidden by default; only show on fail

        # ── Advanced ──────────────────────────────────────────────────────
        # Cũng save làm anchor phòng khi FFmpeg header bị ẩn (auto-detect ok)
        self._advanced_section_header = self._section(scroll, "🔧 Tùy chọn nâng cao")

        adv = ctk.CTkFrame(scroll, fg_color="transparent")
        adv.pack(fill="x", padx=8, pady=4)

        adv_items = [
            ("silence_between_segments", "Thêm khoảng lặng giữa đoạn"),
            ("use_srt_timing", "Căn timing theo SRT"),
            ("trim_silence", "Cắt lặng đầu/cuối"),
            ("remove_special_chars", "Xóa ký tự đặc biệt"),
        ]
        self._adv_vars: dict = {}
        for i, (key, label) in enumerate(adv_items):
            var = ctk.BooleanVar(value=self.config.get_adv(key, True))
            self._adv_vars[key] = var
            ctk.CTkCheckBox(adv, text=label, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=12, pady=4
            )

        num_row = ctk.CTkFrame(scroll, fg_color="transparent")
        num_row.pack(fill="x", padx=8, pady=4)
        self._num_field(num_row, "Khoảng lặng (ms):", "silence_duration_ms", 0, default=300)
        self._num_field(num_row, "Luồng song song:", "max_workers", 1, default=5)
        self._num_field(num_row, "Rate limit (req/s):", "rate_limit", 2, default=1.0)

        # ── Save ─────────────────────────────────────────────────────────
        ctk.CTkButton(
            scroll, text="💾 Lưu cài đặt", height=40,
            fg_color="#2e7d32", hover_color="#1b5e20",
            command=self._save
        ).pack(fill="x", padx=8, pady=(16, 4))

    # ── UI helpers ──────────────────────────────────────────────────────────

    def _section(self, parent, title: str):
        f = ctk.CTkFrame(parent, fg_color=("#d0d0d0", "#2a2a2a"), corner_radius=6)
        f.pack(fill="x", padx=4, pady=(12, 2))
        ctk.CTkLabel(f, text=title, font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=10, pady=4)
        return f

    def _field(self, parent, label: str, key: str, row: int, hint: str = ""):
        ctk.CTkLabel(parent, text=label, width=130, anchor="w").grid(row=row, column=0, sticky="w", pady=3)
        entry = ctk.CTkEntry(parent, width=280, placeholder_text=hint)
        entry.grid(row=row, column=1, sticky="w", padx=4)
        entry.insert(0, str(self.config.get(key, "")))
        setattr(self, f"_entry_{key}", entry)

    def _slider_row(self, parent, label: str, key: str, row: int,
                    from_: float, to: float, step: float, unit: str):
        """Create a labeled slider row, read/write config key as '+Xunit' string."""
        # Parse stored value (e.g. '+20%' → 20, '-10Hz' → -10)
        raw = self.config.get(key, "+0" + unit)
        try:
            num_str = raw.replace("+", "").replace("%", "").replace("Hz", "").strip()
            init_val = float(num_str)
        except Exception:
            init_val = 0.0
        # Clamp to range
        init_val = max(from_, min(to, init_val))

        val_var = ctk.StringVar(value=self._fmt_slider(init_val, unit))

        label_w = ctk.CTkLabel(parent, text=label, width=130, anchor="w")
        label_w.grid(row=row, column=0, sticky="w", pady=4)

        slider = ctk.CTkSlider(
            parent, from_=from_, to=to,
            number_of_steps=int(round((to - from_) / step)),
            width=260,
            command=lambda v, u=unit, vv=val_var, s=step: vv.set(
                self._fmt_slider(round(v / s) * s, u)
            ),
        )
        slider.set(init_val)
        slider.grid(row=row, column=1, sticky="w", padx=4)

        val_w = ctk.CTkLabel(parent, textvariable=val_var, width=70, anchor="w")
        val_w.grid(row=row, column=2, sticky="w", padx=(6, 0))

        setattr(self, f"_slider_{key}", slider)
        setattr(self, f"_slider_{key}_unit", unit)
        setattr(self, f"_slider_{key}_step", step)
        # Lưu widgets để hide/show theo engine (VieNeu không hỗ trợ slider)
        setattr(self, f"_slider_{key}_widgets", (label_w, slider, val_w))

    @staticmethod
    def _fmt_slider(val: float, unit: str) -> str:
        """Format slider value as '+20%' or '-10Hz' etc."""
        v = int(round(val))
        return f"+{v}{unit}" if v >= 0 else f"{v}{unit}"

    def _num_field(self, parent, label: str, adv_key: str, col: int, default=0):
        ctk.CTkLabel(parent, text=label, anchor="w").grid(row=0, column=col * 2, padx=(12, 4))
        entry = ctk.CTkEntry(parent, width=80)
        entry.grid(row=0, column=col * 2 + 1, padx=(0, 12))
        entry.insert(0, str(self.config.get_adv(adv_key, default)))
        setattr(self, f"_num_{adv_key}", entry)

    # ── Actions ─────────────────────────────────────────────────────────────

    def _on_language_change(self, selected_display: str):
        """Khi thay đổi ngôn ngữ, tự động tải giọng"""
        self._load_voices()

    @staticmethod
    def _voice_display_label(voice: dict) -> str:
        """Tạo label hiển thị: ♀ HoaiMy (vi-VN) · Neural"""
        gender_icon = {"Female": "♀", "Male": "♂"}.get(voice.get("gender", ""), "◆")
        name_id = voice["name"]  # e.g. vi-VN-HoaiMyNeural
        locale = voice.get("locale", "")
        # Trích short name: bỏ locale prefix và đuôi 'Neural'
        parts = name_id.split("-")
        short = "-".join(parts[2:]) if len(parts) > 2 else name_id
        short = short.replace("Neural", "").replace("neural", "").strip()
        return f"{gender_icon} {short}  ({locale})"

    # ── VieNeu integration ──────────────────────────────────────────────────

    def _on_engine_change(self):
        """Khi user đổi engine: hiện/ẩn UI tuỳ engine + nếu chọn VieNeu chưa
        cài thì mở dialog cài. Tự reload voices + refresh badge header ngay."""
        engine = self.engine_var.get()
        # Persist vào config in-memory (Save mới ghi file) → badge header +
        # voice_loader + các nơi đọc config.tts_engine sẽ thấy engine mới ngay.
        self.config.set("tts_engine", engine)
        # Refresh badge header qua status_cb (app đọc lại config.tts_engine)
        if self.status_cb:
            try:
                self.status_cb("Chưa lưu — nhớ bấm 💾 Lưu cài đặt", "yellow")
            except Exception:
                pass
        self._refresh_engine_specific_ui()
        # Reload voices ngay với engine mới (silent: không phiền popup)
        self._load_voices(show_warnings=False)
        # VieNeu chưa cài → mở dialog cài luôn
        if engine == "vieneu":
            try:
                from core import vieneu_installer as _inst
                if not _inst.is_installed():
                    self._vieneu_open_install_dialog()
            except Exception as e:
                print(f"[VieNeu] check install fail: {e}")

    def _refresh_engine_specific_ui(self):
        """Hide/show widgets theo engine hiện tại — chỉ hiện phần cài đặt của
        engine đang chọn:
        - Edge: chỉ sliders (Speed/Volume/Pitch)
        - Google: chỉ section Google Credentials
        - OmniVoice: chỉ section OmniVoice Credentials
        - VieNeu: chỉ nút clone/uninstall (ẩn sliders — không hỗ trợ)
        """
        engine = self.engine_var.get()
        is_vieneu = (engine == "vieneu")
        is_omni = (engine == "omnivoice")
        is_google = (engine == "google")

        # Sliders speed/volume/pitch — chỉ Edge dùng (Google có speaking_rate
        # nhưng thang khác + hiếm chỉnh). VieNeu/OmniVoice không hỗ trợ.
        show_sliders = (engine == "edge")
        for key in ("speed", "volume", "pitch"):
            ws = getattr(self, f"_slider_{key}_widgets", None)
            if not ws:
                continue
            for w in ws:
                try:
                    if show_sliders:
                        w.grid()
                    else:
                        w.grid_remove()
                except Exception:
                    pass

        # OmniVoice section — chỉ hiện khi engine=omnivoice
        self._toggle_section(
            getattr(self, "_omni_section_header", None),
            getattr(self, "_omni_section_frame", None),
            show=is_omni,
        )

        # Google section — chỉ hiện khi engine=google
        self._toggle_section(
            getattr(self, "_google_section_header", None),
            getattr(self, "_google_section_frame", None),
            show=is_google,
        )

        # VieNeu action buttons
        try:
            from core import vieneu_installer as _inst
            installed = _inst.is_installed()
        except Exception:
            installed = False
        for w in (self._vn_clone_btn, self._vn_uninstall_btn, self._vn_hw_label):
            try:
                w.grid_forget()
            except Exception:
                pass
        if is_vieneu and installed:
            try:
                from core import vieneu_installer as _inst
                hw = _inst.installed_info().get("hardware", "cpu")
                self._vn_hw_label.configure(
                    text=("🖥️ GPU" if hw == "gpu" else "🖥️ CPU"))
            except Exception:
                pass
            self._vn_clone_btn.grid(row=0, column=5, padx=(12, 4))
            self._vn_uninstall_btn.grid(row=0, column=6, padx=4)
            self._vn_hw_label.grid(row=0, column=7, padx=(8, 0))

    def _maybe_hide_ffmpeg_section(self):
        """Auto-detect ffmpeg. Nếu tìm được → ẩn cả section (giảm rối). Nếu
        không → giữ section + hiện hint cảnh báo user nhập tay."""
        try:
            from core.audio_processor import find_ffmpeg
            # Truyền custom_path để tôn trọng cấu hình cũ (nếu user đã set + còn dùng được)
            find_ffmpeg(self.config.get_adv("ffmpeg_path", ""))
            found = True
        except Exception:
            found = False

        header = getattr(self, "_ffmpeg_section_header", None)
        frame = getattr(self, "_ffmpeg_section_frame", None)
        hint = getattr(self, "_ffmpeg_hint", None)
        if found:
            for w in (header, frame):
                try:
                    if w is not None:
                        w.pack_forget()
                except Exception:
                    pass
        else:
            # Đảm bảo hiển thị + hint
            if hint is not None:
                try:
                    hint.grid()
                except Exception:
                    pass

    def _toggle_section(self, header, frame, show: bool):
        """Ẩn/hiện cặp (header, content frame) của 1 section. Re-pack 'before'
        FFmpeg header (hoặc Advanced header nếu FFmpeg đang ẩn) để giữ đúng
        thứ tự khi user đổi engine (nếu không, pack lại sẽ đưa section xuống
        cuối cùng — sau nút Save)."""
        anchor = getattr(self, "_ffmpeg_section_header", None)
        if anchor is None or not anchor.winfo_ismapped():
            anchor = getattr(self, "_advanced_section_header", None)
        for w, opts in ((header, dict(fill="x", padx=4, pady=(12, 2))),
                        (frame, dict(fill="x", padx=8, pady=4))):
            if w is None:
                continue
            try:
                if show:
                    if not w.winfo_ismapped():
                        if anchor is not None and anchor.winfo_ismapped():
                            w.pack(**opts, before=anchor)
                        else:
                            w.pack(**opts)
                else:
                    w.pack_forget()
            except Exception:
                pass

    def _vieneu_center_popup(self, popup):
        """Đặt popup vào chính giữa app window."""
        try:
            popup.update_idletasks()
            pw = popup.winfo_reqwidth() or popup.winfo_width()
            ph = popup.winfo_reqheight() or popup.winfo_height()
            root = self.winfo_toplevel()
            ax, ay = root.winfo_x(), root.winfo_y()
            aw, ah = root.winfo_width(), root.winfo_height()
            if aw <= 1 or ah <= 1:
                aw, ah = popup.winfo_screenwidth(), popup.winfo_screenheight()
                ax = ay = 0
            x = max(0, ax + (aw - pw) // 2)
            y = max(0, ay + (ah - ph) // 2)
            popup.geometry(f"+{x}+{y}")
        except Exception:
            pass
        try:
            popup.deiconify()
            popup.lift()
            popup.focus_force()
        except Exception:
            pass

    def _vieneu_open_install_dialog(self):
        """Dialog auto-tải VieNeu (uv → venv → vieneu[gpu|cpu] → model)."""
        from core import vieneu_installer as _inst
        hw = _inst.detect_hardware()
        size = "~3-5GB" if hw == "gpu" else "~0.8GB"

        popup = ctk.CTkToplevel(self)
        popup.withdraw()
        popup.title("Cài VieNeu-TTS")
        popup.transient(self.winfo_toplevel())
        popup.resizable(False, False)
        try:
            popup.grab_set()
        except Exception:
            pass

        ctk.CTkLabel(popup, text="Cài VieNeu-TTS (giọng đọc tiếng Việt local)",
                     font=("Segoe UI", 14, "bold")).pack(padx=20, pady=(16, 6))
        ctk.CTkLabel(
            popup, justify="left", font=("Segoe UI", 12), text_color="#94a3b8",
            text=(f"Phát hiện phần cứng: {'GPU NVIDIA (nhanh)' if hw == 'gpu' else 'CPU'}\n"
                  f"Cần tải về {size} (1 lần, lưu local máy KHÔNG sync OneDrive).\n"
                  "Chạy offline sau khi cài. Có thể Gỡ sau để giải phóng ổ."),
        ).pack(padx=20, pady=(0, 10))

        bar = ctk.CTkProgressBar(popup, width=440)
        bar.set(0)
        bar.pack(padx=20, pady=(0, 6))
        status = ctk.CTkLabel(popup, text="", font=("Segoe UI", 11), text_color="#94a3b8",
                              wraplength=440, justify="left")
        status.pack(padx=20, pady=(0, 10))

        cancel_event = threading.Event()
        state = {"installing": False}

        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.pack(padx=20, pady=(0, 16))

        def _progress(stage, pct, msg):
            def _ui():
                try:
                    if pct is not None:
                        bar.set(max(0, min(100, pct)) / 100.0)
                    status.configure(text=msg)
                except Exception:
                    pass
            self.after(0, _ui)

        def _on_done(ok, msg):
            def _ui():
                state["installing"] = False
                try:
                    if ok:
                        bar.set(1.0)
                        status.configure(text=f"✓ {msg}", text_color="#22c55e")
                        try:
                            self._load_voices(show_warnings=False)
                            self._refresh_engine_specific_ui()
                        except Exception:
                            pass
                        popup.after(800, popup.destroy)
                    else:
                        status.configure(text=f"✗ {msg}", text_color="#ef4444")
                        start_btn.configure(state="normal", text="🔧 Thử lại")
                        cancel_btn.configure(text="Đóng")
                except Exception:
                    pass
            self.after(0, _ui)

        def _start():
            if state["installing"]:
                return
            state["installing"] = True
            start_btn.configure(state="disabled", text="⏳ Đang cài…")
            _inst.install_async(_progress, _on_done, cancel_event=cancel_event)

        def _cancel():
            if state["installing"]:
                cancel_event.set()
                cancel_btn.configure(text="⏳ Đang dừng…", state="disabled")
            else:
                try:
                    popup.destroy()
                except Exception:
                    pass

        start_btn = ctk.CTkButton(btn_row, text="🔧 Bắt đầu cài", width=150, height=34,
                                  fg_color="#16a34a", hover_color="#15803d",
                                  font=("Segoe UI", 12, "bold"), command=_start)
        start_btn.pack(side="left", padx=(0, 8))
        cancel_btn = ctk.CTkButton(btn_row, text="Hủy", width=90, height=34,
                                   fg_color="#475569", hover_color="#334155",
                                   command=_cancel)
        cancel_btn.pack(side="left")

        self._vieneu_center_popup(popup)

    def _vieneu_open_clone_dialog(self):
        """Dialog tạo giọng clone từ file audio mẫu (3-5s)."""
        from core import vieneu_installer as _inst
        if not _inst.is_installed():
            messagebox.showwarning(
                "VieNeu chưa cài",
                "Chọn engine VieNeu để mở dialog cài đặt.")
            return

        audio = filedialog.askopenfilename(
            title="Chọn file giọng mẫu (3-5 giây)",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"),
                       ("All", "*.*")])
        if not audio:
            return

        dlg = ctk.CTkToplevel(self)
        dlg.withdraw()
        dlg.title("Tạo giọng clone")
        dlg.transient(self.winfo_toplevel())
        dlg.resizable(False, False)
        try:
            dlg.grab_set()
        except Exception:
            pass

        ctk.CTkLabel(dlg, text="Tên giọng:", font=("Segoe UI", 12)).pack(
            anchor="w", padx=20, pady=(16, 2))
        name_e = ctk.CTkEntry(dlg, width=400, placeholder_text="VD: Giọng nữ trầm")
        name_e.pack(padx=20)
        ctk.CTkLabel(dlg, text="Lời thoại trong mẫu (tùy chọn — giúp clone chuẩn hơn):",
                     font=("Segoe UI", 12)).pack(anchor="w", padx=20, pady=(10, 2))
        tr_e = ctk.CTkEntry(dlg, width=400, placeholder_text="Nội dung audio mẫu nói gì…")
        tr_e.pack(padx=20)
        msg = ctk.CTkLabel(dlg, text="", font=("Segoe UI", 11), text_color="#94a3b8")
        msg.pack(padx=20, pady=(8, 0))

        def _save():
            name = name_e.get().strip()
            if not name:
                msg.configure(text="⚠️ Nhập tên giọng", text_color="#ef4444")
                return
            ffmpeg_path = self.config.get_adv("ffmpeg_path", "") or "ffmpeg"

            def _work():
                try:
                    from core import vieneu_tts as _vt
                    _vt.add_clone(name, audio, transcript=tr_e.get().strip(),
                                  ffmpeg=ffmpeg_path)
                    self.after(0, lambda: (
                        messagebox.showinfo("VieNeu", f"✓ Đã tạo giọng: {name}"),
                        self._load_voices(show_warnings=False),
                        dlg.destroy()))
                except Exception as e:
                    err = str(e)[:120]
                    self.after(0, lambda em=err: msg.configure(
                        text=f"✗ Lỗi: {em}", text_color="#ef4444"))
            msg.configure(text="⏳ Đang xử lý…", text_color="#94a3b8")
            threading.Thread(target=_work, daemon=True).start()

        bf = ctk.CTkFrame(dlg, fg_color="transparent")
        bf.pack(padx=20, pady=16)
        ctk.CTkButton(bf, text="✅ Lưu", width=120, command=_save,
                      fg_color="#16a34a", hover_color="#15803d").pack(side="left", padx=(0, 8))
        ctk.CTkButton(bf, text="Đóng", width=90, command=dlg.destroy,
                      fg_color="#475569", hover_color="#334155").pack(side="left")

        self._vieneu_center_popup(dlg)

    def _vieneu_uninstall(self):
        """Confirm + gỡ runtime VieNeu (giữ giọng clone). Nếu install share với
        app khác (Auto-YTB) → từ chối, bảo user gỡ ở tool đó."""
        from core import vieneu_installer as _inst
        if _inst.is_shared_install():
            messagebox.showinfo(
                "VieNeu — Install dùng chung",
                "Runtime VieNeu hiện đang dùng chung với tool khác (Auto-YTB).\n\n"
                "Để tiết kiệm ~0.8GB đĩa, PT-AI-Voice tự dùng lại install có sẵn.\n"
                "Muốn gỡ → vào Auto-YTB → Settings → Gỡ VieNeu.")
            return
        if not messagebox.askyesno(
                "Gỡ VieNeu",
                "Gỡ runtime VieNeu (giải phóng ổ đĩa)?\n"
                "Giọng clone của bạn vẫn được GIỮ lại."):
            return
        try:
            from core.vieneu_tts import stop_sidecar
            stop_sidecar()
        except Exception:
            pass
        ok = _inst.uninstall()
        if ok:
            messagebox.showinfo("VieNeu", "✓ Đã gỡ VieNeu")
        else:
            messagebox.showerror("VieNeu", "✗ Gỡ thất bại")
        try:
            self._refresh_engine_specific_ui()
            self._load_voices(show_warnings=False)
        except Exception:
            pass

    def _load_voices(self, show_warnings: bool = True):
        """Tải danh sách giọng — dùng helper chung load_voices_for_config().

        OmniVoice: cần Save creds trước khi click (helper đọc config) — nếu chưa
        save, dùng staging tạm từ UI để Test ngay không cần save.

        show_warnings=False: dùng cho auto-load lúc mở app, không hiện popup
        cảnh báo OmniVoice rỗng (tránh làm phiền nếu user dùng engine khác)."""
        self.btn_load_voices.configure(state="disabled", text="Đang tải...")

        # Staging: nếu engine = OmniVoice + user vừa nhập endpoint chưa Save →
        # tạm set vào config in-memory để helper đọc được (không persist).
        if self.engine_var.get() == "omnivoice":
            staged_endpoint = self._omni_endpoint_box.get("1.0", "end").strip()
            staged_kind = self._omni_kind_var.get() or "preset"
            if not staged_endpoint:
                self.btn_load_voices.configure(state="normal", text="↺ Tải giọng")
                messagebox.showwarning(
                    "OmniVoice",
                    "Chưa nhập Server URL — paste URL Cloudflare (*.trycloudflare.com) từ Colab notebook")
                return
            # Sync UI staging → config in-memory (Save mới persist xuống file)
            self.config.set("tts_engine", "omnivoice")
            self.config.set_omnivoice_creds(staged_endpoint, staged_kind)

        def _do():
            try:
                from ui.voice_loader import load_voices_for_config
                selected_display = self.lang_var.get()
                lang_code = self.languages.get(selected_display, "vi-VN")
                voice_items = load_voices_for_config(self.config, lang_code)
                self.after(0, lambda: self._update_voice_list(voice_items, show_warnings=show_warnings))
            except Exception as e:
                print(f"[Load Voices Error] {e}")
                self.after(0, lambda: self.btn_load_voices.configure(state="normal", text="↺ Tải giọng"))
                self.after(0, lambda: messagebox.showerror("Load Voices", f"Lỗi: {e}"))

        import threading
        threading.Thread(target=_do, daemon=True).start()

    def _test_omnivoice(self):
        """Test ping OmniVoice server, hiển thị toast OK/Fail."""
        endpoint = self._omni_endpoint_box.get("1.0", "end").strip()
        if not endpoint:
            messagebox.showwarning("OmniVoice", "Chưa nhập Server URL")
            return

        def _do():
            try:
                from core.omnivoice_engine import OmniVoiceColabEngine
                engine = OmniVoiceColabEngine(endpoint=endpoint)
                ok, detail = engine.check_server()
                if ok:
                    self.after(0, lambda: messagebox.showinfo(
                        "OmniVoice ✓", f"Kết nối OK\n\n{detail}"))
                else:
                    self.after(0, lambda: messagebox.showerror(
                        "OmniVoice ✗", f"Kết nối FAIL\n\n{detail}"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "OmniVoice", f"Lỗi: {e}"))

        import threading
        threading.Thread(target=_do, daemon=True).start()

    def _update_voice_list(self, voice_items: list, show_warnings: bool = True):
        """Cập nhật combobox với danh sách giọng mới (list of (label, voice_id))"""
        if not voice_items:
            self.btn_load_voices.configure(state="normal", text="↺ Tải giọng")
            # OmniVoice empty result → hint user check voice_kind (preset vs clone)
            # Chỉ hiện khi user chủ động (click "Tải giọng"/đổi ngôn ngữ), không hiện lúc auto-load mở app
            if show_warnings and self.engine_var.get() == "omnivoice":
                _kind = self._omni_kind_var.get() or "preset"
                _other = "clone" if _kind == "preset" else "preset"
                messagebox.showwarning(
                    "OmniVoice — Không có giọng",
                    f"Server không trả giọng nào cho 'Voice Kind = {_kind}'.\n\n"
                    f"Thử đổi Voice Kind sang '{_other}' rồi click 'Tải giọng' lại.\n"
                    f"(Folder Drive share từ Auto-YTB thường chứa clone — chọn 'clone'.)"
                )
            return

        self._voice_map = {label: vid for label, vid in voice_items}
        labels = [label for label, _ in voice_items]

        # Chọn label tương ứng với voice_id hiện tại (nếu có)
        current_id = self.config.get("voice_id", "")
        reverse_map = {vid: label for label, vid in voice_items}
        current_label = reverse_map.get(current_id, labels[0])

        self.voice_combo.configure(values=labels)
        self.voice_combo.set(current_label)
        self.btn_load_voices.configure(state="normal", text="↺ Tải giọng")

    def _apply_theme(self):
        ctk.set_appearance_mode(self.theme_var.get())

    def _load_google_json(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON file", "*.json"), ("All", "*.*")],
            title="Chọn Service Account JSON",
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            required = ["type", "private_key", "client_email"]
            missing = [k for k in required if not data.get(k)]
            if missing:
                messagebox.showerror("File không hợp lệ", f"Thiếu các trường: {', '.join(missing)}")
                return
            self.config.set_google_creds(data)
            self.cred_label.configure(text=f"✓ {data.get('client_email', '')}", text_color="green")
        except Exception as e:
            messagebox.showerror("Lỗi đọc JSON", str(e))

    def _pick_output_dir(self):
        directory = filedialog.askdirectory(
            title="Chọn thư mục lưu file audio",
            initialdir=self._output_dir_var.get() or _get_downloads_dir(),
        )
        if directory:
            self._output_dir_var.set(directory)

    def _pick_ffmpeg(self):
        path = filedialog.askopenfilename(
            filetypes=[("Executable", "*.exe ffmpeg"), ("All", "*.*")],
            title="Chọn ffmpeg executable",
        )
        if path:
            self.ffmpeg_entry.delete(0, "end")
            self.ffmpeg_entry.insert(0, path)

    def _save(self):
        # Voice - resolve từ _voice_map nếu đang hiển thị label đẹp
        selected = self.voice_combo.get()
        selected_voice = self._voice_map.get(selected, selected)  # fallback về raw ID
        self.config.set("voice_id", selected_voice)
        
        # Sliders (speed / volume / pitch)
        for key in ("speed", "volume", "pitch"):
            slider = getattr(self, f"_slider_{key}", None)
            if slider:
                unit = getattr(self, f"_slider_{key}_unit", "%")
                step = getattr(self, f"_slider_{key}_step", 1.0)
                v = round(slider.get() / step) * step
                self.config.set(key, self._fmt_slider(v, unit))
            else:  # fallback: text entry if still used
                entry = getattr(self, f"_entry_{key}", None)
                if entry:
                    self.config.set(key, entry.get().strip())

        # Output directory
        out_dir = self._output_dir_var.get().strip()
        self.config.set("output_dir", out_dir if out_dir else _get_downloads_dir())

        # Engine & theme
        self.config.set("tts_engine", self.engine_var.get())
        self.config.set("theme", self.theme_var.get())

        # OmniVoice credentials
        omni_endpoint = self._omni_endpoint_box.get("1.0", "end").strip()
        omni_kind     = self._omni_kind_var.get() or "preset"
        self.config.set_omnivoice_creds(omni_endpoint, omni_kind)

        # FFmpeg
        self.config.set_adv("ffmpeg_path", self.ffmpeg_entry.get().strip())

        # Bool advanced
        for key, var in self._adv_vars.items():
            self.config.set_adv(key, var.get())

        # Numeric advanced
        for adv_key in ("silence_duration_ms", "max_workers", "rate_limit"):
            entry = getattr(self, f"_num_{adv_key}", None)
            if entry:
                try:
                    val = float(entry.get())
                    if adv_key in ("silence_duration_ms", "max_workers"):
                        val = int(val)
                    self.config.set_adv(adv_key, val)
                except ValueError:
                    pass

        self.config.save()
        # Refresh engine badge ở header (status_cb gọi set_status → re-render badge)
        if self.status_cb:
            self.status_cb("Đã lưu cài đặt", "green")
        messagebox.showinfo("Đã lưu", "Cài đặt đã được lưu thành công!")
