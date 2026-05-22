"""
Tab Nhập Text — Nhập/dán text thủ công và tạo audio
"""
import os
import sys
import threading
import tempfile
from datetime import datetime
from pathlib import Path
import customtkinter as ctk
from tkinter import filedialog, messagebox

from core.config_manager import ConfigManager
from core.tts_engine import create_engine
from core.audio_processor import find_ffmpeg, build_audio_from_segments
from core.srt_parser import TXTParser, Segment


def _get_downloads_dir() -> str:
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Downloads")
    return str(Path.home() / "Downloads")


class TextTab(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, status_cb=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self.status_cb = status_cb or (lambda msg, color="white": None)
        self._build_ui()

    def _build_ui(self):
        # ── Label ──────────────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Nhập văn bản cần đọc:", anchor="w").pack(
            fill="x", padx=16, pady=(12, 4)
        )

        # ── Text area ──────────────────────────────────────────────────────
        self.text_box = ctk.CTkTextbox(self, height=260, font=("Segoe UI", 13))
        self.text_box.pack(fill="both", expand=True, padx=16, pady=4)

        # ── Controls row ───────────────────────────────────────────────────
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=16, pady=6)

        # Row 1: Language selector
        ctk.CTkLabel(ctrl, text="Ngôn ngữ:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        
        # Danh sách ngôn ngữ phổ biến
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
            ctrl, variable=self.lang_var, width=200,
            values=list(self.languages.keys()),
            command=self._on_language_change,
        )
        self.lang_combo.grid(row=0, column=1, sticky="w", padx=(0, 12))

        self.btn_refresh = ctk.CTkButton(
            ctrl, text="↺ Tải giọng", width=100, command=self._reload_voices
        )
        self.btn_refresh.grid(row=0, column=2, padx=(0, 12))

        # Row 2: Voice selector
        ctk.CTkLabel(ctrl, text="Giọng đọc:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 0))

        self.voice_var = ctk.StringVar(value=current_voice)
        self.voice_combo = ctk.CTkComboBox(
            ctrl, variable=self.voice_var, width=400,
            values=self._get_voice_list(),
            command=lambda v: self.config.set("voice_id", v),
        )
        self.voice_combo.grid(row=1, column=1, columnspan=2, sticky="w", padx=(0, 12), pady=(8, 0))

        # Format output
        ctk.CTkLabel(ctrl, text="Định dạng:").grid(row=1, column=3, padx=(12, 4), pady=(8, 0))
        self.fmt_var = ctk.StringVar(value=self.config.get("output_format", "mp3"))
        ctk.CTkComboBox(
            ctrl, variable=self.fmt_var, width=80, values=["mp3", "wav"],
            command=lambda v: self.config.set("output_format", v),
        ).grid(row=1, column=4, pady=(8, 0))

        # ── Progress bar ───────────────────────────────────────────────────
        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=16, pady=(8, 2))

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(4, 12))

        self.btn_preview = ctk.CTkButton(
            btn_row, text="▶ Xem trước (10s)", width=160, command=self._preview
        )
        self.btn_preview.pack(side="left", padx=(0, 10))

        self.btn_generate = ctk.CTkButton(
            btn_row, text="⬇ Tạo Audio & Lưu", width=180,
            fg_color="#2e7d32", hover_color="#1b5e20", command=self._generate
        )
        self.btn_generate.pack(side="left")

        self.btn_clear = ctk.CTkButton(
            btn_row, text="🗑 Xóa text", width=100,
            fg_color="#b71c1c", hover_color="#7f0000", command=self._clear
        )
        self.btn_clear.pack(side="right")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _on_language_change(self, selected_display: str):
        """Khi thay đổi ngôn ngữ, tải lại danh sách giọng"""
        self._reload_voices()

    def _get_voice_list(self) -> list:
        """Lấy list voice_id theo engine + ngôn ngữ. Trả raw IDs (combobox không cần label)."""
        try:
            from ui.voice_loader import load_voices_for_config
            selected_display = self.lang_var.get()
            lang_code = self.languages.get(selected_display, "vi-VN")
            items = load_voices_for_config(self.config, lang_code)
            voice_ids = [vid for _, vid in items]
            return voice_ids if voice_ids else [self.voice_var.get()]
        except Exception as e:
            print(f"[Voice List Error] {e}")
            return [self.voice_var.get()]

    def _reload_voices(self):
        self.btn_refresh.configure(state="disabled", text="Đang tải...")
        def _do():
            voices = self._get_voice_list()
            self.after(0, lambda: self._set_voices(voices))
        threading.Thread(target=_do, daemon=True).start()

    def _set_voices(self, voices: list):
        self.voice_combo.configure(values=voices)
        self.btn_refresh.configure(state="normal", text="↺ Tải giọng")

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.btn_generate.configure(state=state)
        self.btn_preview.configure(state=state)

    def _clear(self):
        self.text_box.delete("1.0", "end")
        self.progress.set(0)

    # ── Preview ──────────────────────────────────────────────────────────────

    def _preview(self):
        text = self.text_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Thiếu text", "Vui lòng nhập văn bản!")
            return
        preview_text = text[:200]  # Chỉ đọc 200 ký tự đầu
        # Cập nhật voice_id từ combo trước khi tạo engine
        self.config.set("voice_id", self.voice_var.get())
        self._set_busy(True)
        self.status_cb("Đang tạo preview...", "yellow")

        def _do():
            try:
                engine = create_engine(self.config)
                tmp = tempfile.mktemp(suffix=".mp3")
                ok = engine.synthesize(preview_text, tmp)
                if ok:
                    self._play_audio(tmp)
                    self.after(0, lambda: self.status_cb("Preview hoàn tất ✓", "green"))
                else:
                    self.after(0, lambda: self.status_cb("Preview thất bại ✗", "red"))
            except Exception as e:
                self.after(0, lambda: self.status_cb(f"Lỗi: {e}", "red"))
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_do, daemon=True).start()

    @staticmethod
    def _play_audio(path: str):
        import platform, subprocess
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.Popen(["afplay", path])
            elif system == "Windows":
                os.startfile(path)  # type: ignore
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            print(f"[Play] {e}")

    # ── Generate ─────────────────────────────────────────────────────────────

    def _generate(self):
        text = self.text_box.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Thiếu text", "Vui lòng nhập văn bản!")
            return

        fmt = self.fmt_var.get()

        # Lấy thư mục đã cài đặt (hoặc mặc định Downloads)
        out_dir = self.config.get("output_dir", "") or _get_downloads_dir()
        out_dir_path = Path(out_dir)
        out_dir_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(out_dir_path / f"output_{timestamp}.{fmt}")

        self.config.set("voice_id", self.voice_var.get())
        self.config.save()

        self._set_busy(True)
        self.progress.set(0)
        self.status_cb("Đang tổng hợp giọng đọc...", "yellow")

        def _do():
            try:
                engine = create_engine(self.config)
                # Chia thành segments theo dòng
                parser = TXTParser(max_chars=self.config.get_adv("max_chars_per_segment", 500))
                segments = parser.parse(text)
                total = len(segments)

                tmp_dir = Path(tempfile.mkdtemp(prefix="ptvoice_text_"))
                segments = engine.synthesize_segments(
                    segments,
                    str(tmp_dir),
                    max_workers=self.config.get_adv("max_workers", 5),
                    progress_cb=lambda d, t: self.after(
                        0, lambda d=d, t=t: self.progress.set(d / t * 0.8)
                    ),
                )

                self.after(0, lambda: self.status_cb("Đang ghép audio...", "yellow"))
                self.after(0, lambda: self.progress.set(0.85))

                final_out = out_path
                if fmt == "mp3":
                    mp3_out = out_path
                    ffmpeg = find_ffmpeg(self.config.get_adv("ffmpeg_path", ""))
                    ok = build_audio_from_segments(
                        segments, mp3_out, ffmpeg,
                        use_timing=False,
                        silence_between=self.config.get_adv("silence_between_segments", True),
                        silence_duration_ms=self.config.get_adv("silence_duration_ms", 300),
                        trim_silence=self.config.get_adv("trim_silence", True),
                    )
                else:
                    # WAV: convert
                    import shutil
                    tmp_mp3 = str(tmp_dir / "out.mp3")
                    ffmpeg = find_ffmpeg(self.config.get_adv("ffmpeg_path", ""))
                    build_audio_from_segments(segments, tmp_mp3, ffmpeg, use_timing=False)
                    from core.audio_processor import convert_to_wav
                    ok = convert_to_wav(tmp_mp3, out_path, ffmpeg)

                self.after(0, lambda: self.progress.set(1.0))
                if ok:
                    self.after(0, lambda: self.status_cb(f"✓ Đã lưu: {Path(out_path).name}", "green"))
                    self.after(0, lambda: messagebox.showinfo("Hoàn tất", f"Đã tạo audio:\n{out_path}"))
                else:
                    self.after(0, lambda: self.status_cb("✗ Tạo audio thất bại", "red"))
            except Exception as e:
                self.after(0, lambda e=e: self.status_cb(f"Lỗi: {e}", "red"))
                self.after(0, lambda e=e: messagebox.showerror("Lỗi", str(e)))
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_do, daemon=True).start()
