"""
Tab Cài đặt — Cấu hình engine, credentials, advanced options
"""
import os
import sys
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
        # Tự động tải giọng sau khi UI dựng xong
        self.after(300, self._load_voices)

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
            eng_row, text="Edge TTS (Miễn phí)", variable=self.engine_var, value="edge"
        ).grid(row=0, column=1, padx=8)
        ctk.CTkRadioButton(
            eng_row, text="🇲🇸 Microsoft Azure TTS", variable=self.engine_var, value="azure",
            fg_color="#0078d4", hover_color="#005a9e",
        ).grid(row=0, column=2, padx=8)
        ctk.CTkRadioButton(
            eng_row, text="Google Cloud TTS", variable=self.engine_var, value="google"
        ).grid(row=0, column=3, padx=8)
        ctk.CTkRadioButton(
            eng_row, text="🎭 OmniVoice (Colab)", variable=self.engine_var, value="omnivoice",
            fg_color="#7c3aed", hover_color="#5b21b6",
        ).grid(row=0, column=4, padx=8)

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
        # ── Azure Credentials ─────────────────────────────────────────────────
        self._section(scroll, "🇲🇸 Microsoft Azure TTS Credentials")

        az = ctk.CTkFrame(scroll, fg_color="transparent")
        az.pack(fill="x", padx=8, pady=4)

        ctk.CTkLabel(az, text="Subscription Key:", width=140, anchor="w").grid(row=0, column=0, sticky="w", pady=3)
        self._azure_key_entry = ctk.CTkEntry(az, width=320, placeholder_text="Nhập Azure Speech subscription key")
        self._azure_key_entry.grid(row=0, column=1, sticky="w", padx=4)
        az_key = (self.config.get("azure_credentials") or {}).get("subscription_key", "")
        if az_key:
            self._azure_key_entry.insert(0, az_key)

        ctk.CTkLabel(az, text="Region:", width=140, anchor="w").grid(row=1, column=0, sticky="w", pady=3)
        self._azure_region_entry = ctk.CTkEntry(az, width=200, placeholder_text="VD: eastasia, eastus, westeurope")
        self._azure_region_entry.grid(row=1, column=1, sticky="w", padx=4)
        az_region = (self.config.get("azure_credentials") or {}).get("region", "eastasia")
        self._azure_region_entry.insert(0, az_region)

        ctk.CTkLabel(az, text="Voice Style:", width=140, anchor="w").grid(row=2, column=0, sticky="w", pady=3)
        az_styles = ["", "newscast", "cheerful", "empathetic", "sad", "angry",
                     "excited", "friendly", "hopeful", "shouting", "whispering"]
        self._azure_style_var = ctk.StringVar(
            value=(self.config.get("azure_credentials") or {}).get("style", "")
        )
        style_menu = ctk.CTkOptionMenu(
            az, values=az_styles, variable=self._azure_style_var, width=200
        )
        style_menu.grid(row=2, column=1, sticky="w", padx=4)

        ctk.CTkLabel(
            az,
            text="ℹ️ Tạo key miễn phí tại portal.azure.com → Cognitive Services → Speech",
            text_color="gray", font=("Segoe UI", 11),
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 6))
        # ── OmniVoice Credentials ─────────────────────────────────────────
        self._section(scroll, "🎭 OmniVoice (Colab) Credentials")

        ov = ctk.CTkFrame(scroll, fg_color="transparent")
        ov.pack(fill="x", padx=8, pady=4)
        ov.columnconfigure(1, weight=1)

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
            text="ℹ️ Mở notebook tools/omnivoice-colab-server.ipynb trên Colab → Run all → paste URL ngrok\n"
                 "Nhiều URL: mỗi dòng 1 URL (pool tự rotate khi 1 URL fail).",
            text_color="gray", font=("Segoe UI", 11), justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 6))

        # ── Google Credentials ────────────────────────────────────────────
        self._section(scroll, "☁ Google Cloud TTS Credentials")

        gc = ctk.CTkFrame(scroll, fg_color="transparent")
        gc.pack(fill="x", padx=8, pady=4)

        ctk.CTkLabel(gc, text="File JSON:", width=120, anchor="w").grid(row=0, column=0)
        self.cred_label = ctk.CTkLabel(gc, text="Chưa nạp", text_color="gray", anchor="w")
        self.cred_label.grid(row=0, column=1, sticky="w", padx=4)
        ctk.CTkButton(gc, text="📂 Nạp file", width=100, command=self._load_google_json).grid(row=0, column=2, padx=8)

        # ── FFmpeg ────────────────────────────────────────────────────────
        self._section(scroll, "⚙ FFmpeg")
        ff = ctk.CTkFrame(scroll, fg_color="transparent")
        ff.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(ff, text="Đường dẫn:", width=120, anchor="w").grid(row=0, column=0)
        self.ffmpeg_entry = ctk.CTkEntry(ff, width=300, placeholder_text="Để trống = tự tìm trong PATH")
        self.ffmpeg_entry.grid(row=0, column=1, padx=4)
        self.ffmpeg_entry.insert(0, self.config.get_adv("ffmpeg_path", ""))
        ctk.CTkButton(ff, text="Browse", width=80, command=self._pick_ffmpeg).grid(row=0, column=2)

        # ── Advanced ──────────────────────────────────────────────────────
        self._section(scroll, "🔧 Tùy chọn nâng cao")

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

        ctk.CTkLabel(parent, text=label, width=130, anchor="w").grid(
            row=row, column=0, sticky="w", pady=4)

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

        ctk.CTkLabel(parent, textvariable=val_var, width=70, anchor="w").grid(
            row=row, column=2, sticky="w", padx=(6, 0))

        setattr(self, f"_slider_{key}", slider)
        setattr(self, f"_slider_{key}_unit", unit)
        setattr(self, f"_slider_{key}_step", step)

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

    def _load_voices(self):
        """Tải danh sách giọng — dùng helper chung load_voices_for_config().

        OmniVoice: cần Save creds trước khi click (helper đọc config) — nếu chưa
        save, dùng staging tạm từ UI để Test ngay không cần save."""
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
                    "Chưa nhập Server URL — paste URL ngrok từ Colab notebook")
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
                self.after(0, lambda: self._update_voice_list(voice_items))
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

    def _update_voice_list(self, voice_items: list):
        """Cập nhật combobox với danh sách giọng mới (list of (label, voice_id))"""
        if not voice_items:
            self.btn_load_voices.configure(state="normal", text="↺ Tải giọng")
            # OmniVoice empty result → hint user check voice_kind (preset vs clone)
            if self.engine_var.get() == "omnivoice":
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

        # Azure credentials
        az_key    = self._azure_key_entry.get().strip()
        az_region = self._azure_region_entry.get().strip() or "eastasia"
        az_style  = self._azure_style_var.get()
        self.config.set_azure_creds(az_key, az_region, az_style)
        if az_key:
            self._azure_key_entry.configure(placeholder_text="✓ Đã lưu")

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
