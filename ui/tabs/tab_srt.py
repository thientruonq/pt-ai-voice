"""
Tab SRT/VTT/TXT — Đọc file phụ đề, tạo audio theo timing
"""
import os
import sys
import threading
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk

from core.config_manager import ConfigManager
from core.tts_engine import create_engine
from core.audio_processor import find_ffmpeg, build_audio_from_segments
from core import srt_parser


def _local_desktop() -> str:
    """
    Trả về đường dẫn Downloads (tránh OneDrive folder redirection trên Desktop).
    """
    if sys.platform == "win32":
        return os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Downloads")
    return str(Path.home() / "Downloads")


class SRTTab(ctk.CTkFrame):
    def __init__(self, master, config: ConfigManager, status_cb=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self.status_cb = status_cb or (lambda msg, color="white": None)
        self._segments = []
        self._file_path = ""
        self._batch_files: list = []  # >1 file → batch mode
        self._last_output_dir = ""
        self._voice_map: dict = {}
        self._preview_thread: threading.Thread | None = None
        self._preview_tmp: str = ""
        self._new_srt_content: str = ""
        self._last_theme: str = ""
        self._stop_event = threading.Event()
        self._resume_state: dict | None = None
        self._build_ui()
        self.after(300, self._reload_voices)
        self.after(100, self._apply_tree_theme)   # áp theme ngay sau khi UI dựng
        self.after(1500, self._poll_theme)         # bắt đầu polling

    def _build_ui(self):
        # ── Scrollable container ───────────────────────────────────────────
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # ── File picker ────────────────────────────────────────────────────
        file_row = ctk.CTkFrame(scroll, fg_color="transparent")
        file_row.pack(fill="x", padx=16, pady=(12, 6))

        ctk.CTkLabel(file_row, text="File:").pack(side="left", padx=(0, 6))
        self.file_label = ctk.CTkLabel(
            file_row, text="Chưa chọn file", text_color="gray", anchor="w"
        )
        self.file_label.pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            file_row, text="📂 Chọn file", width=120, command=self._pick_file
        ).pack(side="right")

        # ── Preview segments ───────────────────────────────────────────────
        ctk.CTkLabel(scroll, text="Nội dung phụ đề (preview):", anchor="w").pack(
            fill="x", padx=16, pady=(4, 2)
        )

        self.tree_frame = tk.Frame(scroll)
        self.tree_frame.pack(fill="both", expand=True, padx=16, pady=(0, 6))

        # style riêng cho bảng này để không ảnh hưởng widget khác
        self._tree_style_name = "SRTTab.Treeview"
        self._tree_style = ttk.Style()
        self._tree_style.theme_use("default")

        cols = ("#", "srt_goc", "srt_moi", "noi_dung", "trang_thai")
        self.preview_tree = ttk.Treeview(self.tree_frame, columns=cols, show="headings",
                                         height=12, selectmode="browse",
                                         style=self._tree_style_name)

        self.preview_tree.heading("#",          text="#")
        self.preview_tree.heading("srt_goc",    text="SRT Gốc")
        self.preview_tree.heading("srt_moi",    text="SRT Mới")
        self.preview_tree.heading("noi_dung",   text="Nội dung")
        self.preview_tree.heading("trang_thai", text="Trạng thái")

        self.preview_tree.column("#",          width=40,  minwidth=30,  anchor="center", stretch=False)
        self.preview_tree.column("srt_goc",    width=210, minwidth=160, anchor="center", stretch=False)
        self.preview_tree.column("srt_moi",    width=210, minwidth=160, anchor="center", stretch=False)
        self.preview_tree.column("noi_dung",   width=480, minwidth=200, anchor="w",      stretch=True)
        self.preview_tree.column("trang_thai", width=90,  minwidth=70,  anchor="center", stretch=False)

        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical",   command=self.preview_tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.preview_tree.xview)
        self.preview_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.preview_tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree_frame.rowconfigure(0, weight=1)
        self.tree_frame.columnconfigure(0, weight=1)

        # ── Options ────────────────────────────────────────────────────────
        opt = ctk.CTkFrame(scroll, fg_color="transparent")
        opt.pack(fill="x", padx=16, pady=4)

        # Row 0: Language selector
        ctk.CTkLabel(opt, text="Ngôn ngữ:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        
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
            opt, variable=self.lang_var, width=200,
            values=list(self.languages.keys()),
            command=self._on_language_change,
        )
        self.lang_combo.grid(row=0, column=1, sticky="w", padx=(0, 8))

        self.btn_refresh = ctk.CTkButton(
            opt, text="↺ Tải giọng", width=100, command=self._reload_voices
        )
        self.btn_refresh.grid(row=0, column=2, padx=(0, 8))

        # Row 1: Voice selector + options
        ctk.CTkLabel(opt, text="Giọng đọc:").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 0))
        self.voice_combo = ctk.CTkComboBox(
            opt, width=280,
            values=[current_voice],
        )
        self.voice_combo.set(current_voice)
        self.voice_combo.grid(row=1, column=1, sticky="w", padx=(0, 4), pady=(8, 0))

        self.btn_preview = ctk.CTkButton(
            opt, text="▶ Nghe thử", width=100,
            fg_color="#6a1b9a", hover_color="#4a148c",
            command=self._preview_voice,
        )
        self.btn_preview.grid(row=1, column=2, sticky="w", padx=(0, 8), pady=(8, 0))

        # Use SRT timing
        self.use_timing_var = ctk.BooleanVar(
            value=self.config.get_adv("use_srt_timing", True)
        )
        ctk.CTkCheckBox(
            opt, text="Căn timing SRT", variable=self.use_timing_var
        ).grid(row=1, column=3, padx=(8, 0), pady=(8, 0))

        # Format
        ctk.CTkLabel(opt, text="Định dạng:").grid(row=1, column=4, padx=(16, 4), pady=(8, 0))
        self.fmt_var = ctk.StringVar(value=self.config.get("output_format", "mp3"))
        ctk.CTkComboBox(
            opt, variable=self.fmt_var, width=80, values=["mp3", "wav"],
        ).grid(row=1, column=5, pady=(8, 0))

        # ── Stats row ──────────────────────────────────────────────────────
        self.stats_label = ctk.CTkLabel(
            scroll, text="", text_color="gray", font=("Segoe UI", 11)
        )
        self.stats_label.pack(anchor="w", padx=16)

        # ── Progress ───────────────────────────────────────────────────────
        self.progress = ctk.CTkProgressBar(scroll)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=16, pady=(6, 2))

        # ── Buttons ────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(4, 12))

        self.btn_export_segments = ctk.CTkButton(
            btn_row, text="🔊 Tạo từng đoạn Audio", width=200,
            fg_color="#2e7d32", hover_color="#1b5e20", command=self._export_segments
        )
        self.btn_export_segments.pack(side="left", padx=(0, 10))

        self.btn_merge = ctk.CTkButton(
            btn_row, text="⬇ Ghép thành 1 file", width=160,
            command=self._generate,
            state="disabled"
        )
        self.btn_merge.pack(side="left", padx=(0, 10))

        self.btn_stop = ctk.CTkButton(
            btn_row, text="⏹ Dừng", width=120,
            fg_color="#c62828", hover_color="#8e0000",
            command=self._stop_click,
            state="disabled"
        )
        self.btn_stop.pack(side="left", padx=(0, 10))

        self.btn_open_folder = ctk.CTkButton(
            btn_row, text="📂 Mở folder", width=120,
            fg_color="#1565c0", hover_color="#0d47a1",
            command=self._open_output_folder,
            state="disabled"
        )
        self.btn_open_folder.pack(side="left", padx=(0, 10))

        self.btn_download_srt = ctk.CTkButton(
            btn_row, text="📄 Tải SRT mới", width=140,
            fg_color="#00838f", hover_color="#006064",
            command=self._download_new_srt,
            state="disabled"
        )
        self.btn_download_srt.pack(side="left")

    # ── Theme ────────────────────────────────────────────────────────────────

    def _apply_tree_theme(self):
        mode = ctk.get_appearance_mode()  # "Light" | "Dark" | "System"
        dark = (mode.lower() != "light")

        if dark:
            bg, fg         = "#1e1e1e", "#e0e0e0"
            sel_bg, sel_fg = "#2d5a8e", "#ffffff"
            head_bg        = "#2a2a2a"
            head_fg        = "#b0b0b0"
            odd_bg, even_bg = "#1e1e1e", "#252525"
        else:
            bg, fg         = "#ffffff", "#1a1a1a"
            sel_bg, sel_fg = "#3b8ed0", "#ffffff"
            head_bg        = "#e8e8e8"
            head_fg        = "#333333"
            odd_bg, even_bg = "#ffffff", "#f5f5f5"

        s, n = self._tree_style, self._tree_style_name
        s.configure(n,
            background=bg, foreground=fg, fieldbackground=bg,
            rowheight=24, font=("Segoe UI", 10),
        )
        s.configure(f"{n}.Heading",
            background=head_bg, foreground=head_fg,
            font=("Segoe UI", 10, "bold"), relief="flat",
        )
        s.map(n, background=[("selected", sel_bg)], foreground=[("selected", sel_fg)])
        s.map(f"{n}.Heading", background=[("active", head_bg)])
        self.preview_tree.tag_configure("odd",  background=odd_bg,   foreground=fg)
        self.preview_tree.tag_configure("even", background=even_bg,  foreground=fg)
        self.preview_tree.tag_configure("done",  foreground="#4caf50")
        self.preview_tree.tag_configure("error", foreground="#f44336")
        self.preview_tree.tag_configure("proc",  foreground="#ffc107")
        self.tree_frame.configure(bg=bg)

    def _poll_theme(self):
        """Kiểm tra mỗi giây — nếu theme thay đổi thì re-apply"""
        try:
            mode = ctk.get_appearance_mode()
            if mode != self._last_theme:
                self._last_theme = mode
                self._apply_tree_theme()
        except Exception:
            pass
        self.after(1000, self._poll_theme)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _pick_file(self):
        paths = filedialog.askopenfilenames(
            filetypes=[
                ("Subtitle files", "*.srt *.vtt *.txt"),
                ("SRT files", "*.srt"),
                ("VTT files", "*.vtt"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
            title="Chọn 1 hoặc nhiều file phụ đề/text (Ctrl/Shift để chọn nhiều)",
        )
        if not paths:
            return
        paths = list(paths)
        self._batch_files = paths
        self._file_path = paths[0]
        if len(paths) == 1:
            self.file_label.configure(text=Path(paths[0]).name, text_color="white")
            self._parse_and_preview(paths[0])
        else:
            head = ", ".join(Path(p).name for p in paths[:2])
            tail = "..." if len(paths) > 2 else ""
            self.file_label.configure(
                text=f"📚 Batch {len(paths)} files: {head}{tail}",
                text_color="#b39ddb"
            )
            # Batch: tree show 1 dòng/file (parse nhẹ ở background để đếm segment)
            self._show_batch_preview(paths)

    def _show_batch_preview(self, paths: list):
        """Batch mode: tree show 1 dòng/file thay vì segments. Parse nhẹ ở background
        để đếm số đoạn mỗi file."""
        # Clear + show skeleton rows ngay (parse async để không block UI)
        for row in self.preview_tree.get_children():
            self.preview_tree.delete(row)
        for i, p in enumerate(paths, 1):
            tag = "even" if i % 2 == 0 else "odd"
            self.preview_tree.insert("", "end", iid=f"f{i}", tags=(tag,), values=(
                i, "—", "—", Path(p).name, "pending"
            ))
        self.stats_label.configure(text=f"📚 Batch: {len(paths)} files queued")
        self.btn_merge.configure(state="normal")
        # Cờ batch_iid_map: file_path → iid trong tree (dùng update progress lúc chạy)
        self._batch_iid_map = {p: f"f{i+1}" for i, p in enumerate(paths)}
        # _segments để check has-data trong _export_segments/_generate — set 1 placeholder
        self._segments = [object()]  # truthy placeholder; thực tế batch parse lại từng file

        # Parse async để đếm segments + show vào cột "Nội dung" + "SRT Gốc"
        def _count_async():
            remove_special = self.config.get_adv("remove_special_chars", True)
            max_chars = self.config.get_adv("max_chars_per_segment", 500)
            total_segs = 0
            for p in paths:
                try:
                    segs = srt_parser.parse_file(p, remove_special=remove_special, max_chars=max_chars)
                    n = len(segs)
                    total_segs += n
                    preview_text = (segs[0].text[:80] + "...") if segs and len(segs[0].text) > 80 else (segs[0].text if segs else "")
                    # SRT Gốc time range: từ segment đầu → segment cuối
                    if segs:
                        time_range = f"{self._fmt_time(segs[0].start_ms)} --> {self._fmt_time(segs[-1].end_ms)}"
                    else:
                        time_range = "—"
                    self.after(0, lambda _p=p, _n=n, _t=preview_text, _tr=time_range:
                               self._update_batch_row(_p, content=f"[{_n} đoạn] {_t}", srt_goc=_tr))
                except Exception as e:
                    self.after(0, lambda _p=p, _e=str(e)[:40]:
                               self._update_batch_row(_p, content=f"❌ Lỗi parse: {_e}", status="error"))
            self.after(0, lambda ts=total_segs, n=len(paths):
                       self.stats_label.configure(text=f"📚 Batch: {n} files | tổng {ts} đoạn"))
        threading.Thread(target=_count_async, daemon=True).start()

    def _update_batch_row(self, file_path: str, content: str = None,
                           status: str = None, tag: str = None,
                           srt_goc: str = None, srt_moi: str = None):
        """Update 1 dòng file trong batch preview tree.
        Cột: [0]# [1]SRT Gốc [2]SRT Mới [3]Nội dung [4]Trạng thái"""
        iid = getattr(self, "_batch_iid_map", {}).get(file_path)
        if not iid or not self.preview_tree.exists(iid):
            return
        vals = list(self.preview_tree.item(iid, "values"))
        if srt_goc is not None:
            vals[1] = srt_goc
        if srt_moi is not None:
            vals[2] = srt_moi
        if content is not None:
            vals[3] = content
        if status is not None:
            vals[4] = status
        tags = [t for t in self.preview_tree.item(iid, "tags") if t not in ("done", "error", "proc")]
        if tag:
            tags.append(tag)
        self.preview_tree.item(iid, values=vals, tags=tags)

    def _parse_and_preview(self, path: str):
        try:
            remove_special = self.config.get_adv("remove_special_chars", True)
            max_chars = self.config.get_adv("max_chars_per_segment", 500)
            self._segments = srt_parser.parse_file(
                path, remove_special=remove_special, max_chars=max_chars
            )
            self._update_preview()
            self.stats_label.configure(
                text=f"✓ {len(self._segments)} đoạn | "
                     f"Tổng: {sum(len(s.text) for s in self._segments)} ký tự"
            )
            # Enable button ghép khi có segments
            self.btn_merge.configure(state="normal")
        except Exception as e:
            messagebox.showerror("Lỗi đọc file", str(e))

    def _update_preview(self):
        for row in self.preview_tree.get_children():
            self.preview_tree.delete(row)
        for i, seg in enumerate(self._segments):
            tag = "even" if i % 2 == 0 else "odd"
            self.preview_tree.insert("", "end", iid=str(seg.index), tags=(tag,), values=(
                seg.index,
                f"{self._fmt_time(seg.start_ms)} --> {self._fmt_time(seg.end_ms)}",
                "--:--:--.---",
                seg.text,
                "pending",
            ))

    def _update_row_new_srt(self, seg_index: int, new_start_ms: int, new_end_ms: int):
        """Cập nhật cột SRT Mới và Trạng thái cho 1 hàng trong bảng"""
        iid = str(seg_index)
        if self.preview_tree.exists(iid):
            vals = list(self.preview_tree.item(iid, "values"))
            vals[2] = f"{self._fmt_time(new_start_ms)} --> {self._fmt_time(new_end_ms)}"
            vals[4] = "✓ done"
            existing = [t for t in self.preview_tree.item(iid, "tags")
                        if t not in ("done", "error", "proc")]
            existing.append("done")
            self.preview_tree.item(iid, values=vals, tags=existing)

    def _update_row_status(self, seg_index: int, status: str, tag: str):
        """Cập nhật chỉ cột Trạng thái (dùng để cập nhật real-time)"""
        iid = str(seg_index)
        if self.preview_tree.exists(iid):
            vals = list(self.preview_tree.item(iid, "values"))
            vals[4] = status
            existing = [t for t in self.preview_tree.item(iid, "tags")
                        if t not in ("done", "error", "proc")]
            existing.append(tag)
            self.preview_tree.item(iid, values=vals, tags=existing)

    @staticmethod
    def _fmt_time(ms: int) -> str:
        ms = max(0, int(ms))
        h, ms  = divmod(ms, 3_600_000)
        m, ms  = divmod(ms, 60_000)
        s, ms  = divmod(ms, 1_000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _on_language_change(self, selected_display: str):
        """Khi thay đổi ngôn ngữ, tải lại danh sách giọng"""
        self._reload_voices()

    # Mẫu câu ngắn để nghe thử theo ngôn ngữ
    _PREVIEW_TEXT = {
        "vi": "Xin chào, đây là giọng đọc mẫu của bạn.",
        "en": "Hello, this is a sample of the selected voice.",
        "ja": "こんにちは、選択した音声のサンプルです。",
        "zh": "你好，这是选定语音的示例。",
        "ko": "안녕하세요, 선택한 음성 샘플입니다.",
        "fr": "Bonjour, voici un exemple de la voix sélectionnée.",
        "de": "Hallo, dies ist ein Beispiel der ausgewählten Stimme.",
        "es": "Hola, este es un ejemplo de la voz seleccionada.",
        "ru": "Привет, это образец выбранного голоса.",
        "ar": "مرحبا، هذا مثال على الصوت المختار.",
        "hi": "नमस्ते, यह चयनित आवाज का नमूना है।",
        "th": "สวัสดีครับ นี่คือตัวอย่างเสียงที่เลือก",
        "id": "Halo, ini adalah contoh suara yang dipilih.",
        "pt": "Olá, este é um exemplo da voz selecionada.",
        "it": "Ciao, questo è un esempio della voce selezionata.",
        "nl": "Hallo, dit is een voorbeeld van de geselecteerde stem.",
        "pl": "Cześć, to jest przykład wybranego głosu.",
        "tr": "Merhaba, bu seçilen sesin bir örneğidir.",
    }

    def _preview_voice(self):
        """Tổng hợp đoạn ngắn và phát thử giọng đang chọn"""
        # Nếu đang có preview chạy thì bỏ qua
        if self._preview_thread and self._preview_thread.is_alive():
            return

        label = self.voice_combo.get()
        voice_id = self._voice_map.get(label, label)
        if not voice_id:
            return

        # Xác định ngôn ngữ từ lang_code
        lang_code = self.languages.get(self.lang_var.get(), "vi-VN")
        lang_prefix = lang_code.split("-")[0]
        sample_text = self._PREVIEW_TEXT.get(lang_prefix, self._PREVIEW_TEXT["en"])

        self.btn_preview.configure(state="disabled", text="⏳ Đang tải...")

        def _do():
            try:
                from core.tts_engine import EdgeTTSEngine
                import asyncio, subprocess

                engine = EdgeTTSEngine(voice=voice_id)
                tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                tmp.close()
                self._preview_tmp = tmp.name

                ok = engine.synthesize(sample_text, tmp.name)
                if not ok:
                    raise RuntimeError("Synthesis failed")

                # Phát âm thanh
                self.after(0, lambda: self.btn_preview.configure(text="🔊 Đang phát..."))
                if sys.platform == "win32":
                    path_escaped = tmp.name.replace("'", "''")
                    ps_cmd = (
                        "Add-Type -AssemblyName presentationCore; "
                        "$p = New-Object System.Windows.Media.MediaPlayer; "
                        f"$p.Open([System.Uri]::new('{path_escaped}')); "
                        "$p.Play(); Start-Sleep 6; $p.Stop()"
                    )
                    proc = subprocess.Popen(
                        ["powershell", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                        creationflags=0x08000000,  # CREATE_NO_WINDOW
                    )
                    proc.wait()  # chờ phát xong mới reset button
                else:
                    os.system(f'afplay "{tmp.name}"')

            except Exception as e:
                print(f"[Preview Error] {e}")
            finally:
                self.after(0, lambda: self.btn_preview.configure(state="normal", text="▶ Nghe thử"))

        self._preview_thread = threading.Thread(target=_do, daemon=True)
        self._preview_thread.start()

    @staticmethod
    def _voice_display_label(voice: dict) -> str:
        gender_icon = {"Female": "♀", "Male": "♂"}.get(voice.get("gender", ""), "◆")
        name_id = voice["name"]
        locale = voice.get("locale", "")
        parts = name_id.split("-")
        short = "-".join(parts[2:]) if len(parts) > 2 else name_id
        short = short.replace("Neural", "").replace("neural", "").strip()
        return f"{gender_icon} {short}  ({locale})"

    def _reload_voices(self):
        """Tải danh sách giọng theo engine + ngôn ngữ đã chọn.
        OmniVoice: gọi server library; engine khác: Edge filter theo locale."""
        self.btn_refresh.configure(state="disabled", text="Đang tải...")

        def _do():
            try:
                from ui.voice_loader import load_voices_for_config
                selected_display = self.lang_var.get()
                lang_code = self.languages.get(selected_display, "vi-VN")
                voice_items = load_voices_for_config(self.config, lang_code)

                if voice_items:
                    self.after(0, lambda: self._update_voice_list(voice_items))
                else:
                    self.after(0, lambda: self.btn_refresh.configure(state="normal", text="↺ Tải giọng"))
            except Exception as e:
                print(f"[Load Voices Error] {e}")
                self.after(0, lambda: self.btn_refresh.configure(state="normal", text="↺ Tải giọng"))

        threading.Thread(target=_do, daemon=True).start()

    def _update_voice_list(self, voice_items: list):
        """Cập nhật combobox với danh sách giọng mới (list of (label, voice_id))"""
        self._voice_map = {label: vid for label, vid in voice_items}
        labels = [label for label, _ in voice_items]

        # Chọn label tương ứng với voice_id hiện tại
        current_id = self.config.get("voice_id", "")
        reverse_map = {vid: label for label, vid in voice_items}
        current_label = reverse_map.get(current_id, labels[0])

        self.voice_combo.configure(values=labels)
        self.voice_combo.set(current_label)
        self.btn_refresh.configure(state="normal", text="↺ Tải giọng")

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        self.btn_export_segments.configure(state=state)
        self.btn_merge.configure(state=state)
        if busy:
            # Hiển nút Dừng và reset về trạng thái đỏ
            self.btn_stop.configure(
                state="normal", text="⏹ Dừng",
                fg_color="#c62828", hover_color="#8e0000"
            )
        else:
            # Hoàn thành bình thường: ẩn nút Dừng
            self.btn_stop.configure(state="disabled", text="⏹ Dừng",
                                    fg_color="#c62828", hover_color="#8e0000")
            self._resume_state = None
        # Chỉ enable nút "Mở folder" nếu đã có folder output
        if not busy and self._last_output_dir:
            self.btn_open_folder.configure(state="normal")
        # Chỉ enable nút "Tải SRT mới" nếu đã có nội dung
        if not busy and self._new_srt_content:
            self.btn_download_srt.configure(state="normal")

    # ── Generate ─────────────────────────────────────────────────────────────

    def _generate(self):
        if not self._segments:
            messagebox.showwarning("Chưa có dữ liệu", "Vui lòng chọn file phụ đề trước!")
            return

        # Batch mode: nhiều file → loop, mỗi file ghép thành 1 audio riêng
        if len(self._batch_files) > 1:
            self._batch_run("merge")
            return

        fmt = self.fmt_var.get()

        # Lấy thư mục đã cài đặt (hoặc mặc định Downloads)
        out_dir = self.config.get("output_dir", "") or _local_desktop()
        out_dir_path = Path(out_dir)
        out_dir_path.mkdir(parents=True, exist_ok=True)

        stem = Path(self._file_path).stem if self._file_path else "output"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(out_dir_path / f"{stem}_{timestamp}.{fmt}")
        self._last_output_dir = str(out_dir_path)  # dùng cho nút "Mở folder"

        selected_label = self.voice_combo.get()
        self.config.set("voice_id", self._voice_map.get(selected_label, selected_label))
        self.config.set("output_format", fmt)
        self.config.save()

        use_timing = self.use_timing_var.get()
        segments = list(self._segments)  # copy

        self._stop_event.clear()
        self._resume_state = None
        self._set_busy(True)
        self.progress.set(0)
        self.status_cb("Đang tổng hợp giọng đọc...", "yellow")

        self._run_merge_do(segments, segments, Path(tempfile.mkdtemp(prefix="ptvoice_srt_")),
                           out_path, fmt, use_timing, is_fresh=True)
    # ── Merge worker ──────────────────────────────────────────────────────────────────

    def _run_merge_do(self, pending_segs, all_segs, tmp_dir: Path,
                      out_path: str, fmt: str, use_timing: bool, is_fresh: bool = False):
        """Chạy synthesis + merge trong background. Dùng cho cả lần đầu và resume."""
        total = len(all_segs)
        already_done = sum(1 for s in all_segs if s.audio_path and Path(s.audio_path).exists())
        progress_base = (already_done / total * 0.8) if total > 0 else 0.0
        progress_range = ((len(pending_segs) / total) * 0.8) if total > 0 else 0.8
        def _do():
            is_stopped = False
            try:
                engine = create_engine(self.config)

                def _seg_cb(seg, success):
                    if success:
                        self.after(0, lambda i=seg.index:
                                   self._update_row_status(i, "✓ done", "done"))
                    elif self._stop_event.is_set():
                        self.after(0, lambda i=seg.index:
                                   self._update_row_status(i, "⏸ bỏ qua", "proc"))
                    else:
                        self.after(0, lambda i=seg.index:
                                   self._update_row_status(i, "✗ lỗi (10/10)", "error"))

                def _retry_cb(seg, attempt, max_r):
                    self.after(0, lambda i=seg.index, a=attempt, m=max_r:
                               self._update_row_status(i, f"🔄 thử lại {a}/{m}", "proc"))

                new_segs = engine.synthesize_segments(
                    pending_segs, str(tmp_dir),
                    max_workers=self.config.get_adv("max_workers", 5),
                    progress_cb=lambda d, t: self.after(
                        0, lambda d=d, t=t: self.progress.set(
                            progress_base + (d / t * progress_range) if t > 0 else progress_base
                        )
                    ),
                    segment_cb=_seg_cb,
                    retry_cb=_retry_cb,
                    rate_limit=self.config.get_adv("rate_limit", 1.0),
                    max_retries=10,
                    stop_event=self._stop_event,
                )

                # Ghép kết quả mới vào all_segs
                seg_map = {s.index: s for s in all_segs}
                for s in new_segs:
                    seg_map[s.index] = s
                segs = [seg_map[s.index] for s in all_segs]

                if self._stop_event.is_set():
                    is_stopped = True
                    self._handle_stopped("merge", segs,
                                         out_path=out_path, tmp_dir=tmp_dir,
                                         fmt=fmt, use_timing=use_timing)
                    return

                self.after(0, lambda: self.status_cb("Đang ghép audio...", "yellow"))
                self.after(0, lambda: self.progress.set(0.85))

                ffmpeg = find_ffmpeg(self.config.get_adv("ffmpeg_path", ""))
                mp3_path = out_path if fmt == "mp3" else str(tmp_dir / "out.mp3")

                ok = build_audio_from_segments(
                    segs, mp3_path, ffmpeg,
                    use_timing=use_timing,
                    silence_between=self.config.get_adv("silence_between_segments", True),
                    silence_duration_ms=self.config.get_adv("silence_duration_ms", 300),
                    trim_silence=self.config.get_adv("trim_silence", True),
                )

                if ok and fmt == "wav":
                    from core.audio_processor import convert_to_wav
                    ok = convert_to_wav(mp3_path, out_path, ffmpeg)

                self.after(0, lambda: self.progress.set(1.0))
                if ok:
                    n_fail = sum(1 for s in segs if not s.audio_path or not Path(s.audio_path).exists())
                    try:
                        from core.audio_processor import get_audio_duration_ms
                        gap = self.config.get_adv("silence_duration_ms", 300)
                        cursor = 0
                        srt_lines = []
                        for seg in segs:
                            if not seg.audio_path or not Path(seg.audio_path).exists():
                                continue
                            dur = get_audio_duration_ms(seg.audio_path, ffmpeg)
                            if dur <= 0:
                                dur = seg.end_ms - seg.start_ms
                            s0, s1 = cursor, cursor + dur
                            self.after(0, lambda i=seg.index, a=s0, b=s1:
                                       self._update_row_new_srt(i, a, b))
                            srt_lines += [str(seg.index),
                                          f"{self._fmt_time(s0)} --> {self._fmt_time(s1)}",
                                          seg.text, ""]
                            cursor += dur + gap
                        self._new_srt_content = "\n".join(srt_lines)
                    except Exception:
                        self._new_srt_content = ""
                    fail_line = f"\n\u26a0 {n_fail} đoạn lỗi (không được ghép vào)" if n_fail else ""
                    self.after(0, lambda: self.status_cb(
                        f"✓ {Path(out_path).name}" + (f" | {n_fail} đoạn lỗi" if n_fail else ""),
                        "yellow" if n_fail else "green"
                    ))
                    self.after(0, lambda: messagebox.showinfo(
                        "Hoàn tất", f"Đã tạo:\n{out_path}{fail_line}"
                    ))
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                else:
                    self.after(0, lambda: self.status_cb("✗ Thất bại", "red"))
                    shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception as e:
                self.after(0, lambda e=e: self.status_cb(f"Lỗi: {e}", "red"))
                self.after(0, lambda e=e: messagebox.showerror("Lỗi", str(e)))
            finally:
                if not is_stopped:
                    self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_do, daemon=True).start()
    # ── Export từng đoạn ─────────────────────────────────────────────────────

    def _export_segments(self):
        """Xuất từng đoạn audio riêng biệt vào folder"""
        if not self._segments:
            messagebox.showwarning("Chưa có dữ liệu", "Vui lòng chọn file phụ đề trước!")
            return

        # Batch mode: nhiều file → loop tuần tự, không dùng resume
        if len(self._batch_files) > 1:
            self._batch_run("export")
            return

        # Cập nhật voice_id từ combo trước khi tạo engine (tránh dùng voice cũ trong config)
        selected_label = self.voice_combo.get()
        self.config.set("voice_id", self._voice_map.get(selected_label, selected_label))
        self.config.set("output_format", self.fmt_var.get())
        self.config.save()

        # Lấy thư mục đã cài đặt (hoặc mặc định Downloads), tạo subfolder theo tên file
        base_dir = self.config.get("output_dir", "") or _local_desktop()
        default_folder = Path(self._file_path).stem + "_audio" if self._file_path else "audio_segments"
        output_folder = Path(base_dir) / default_folder
        output_folder.mkdir(parents=True, exist_ok=True)
        
        self._last_output_dir = str(output_folder)  # Lưu để mở sau
        segments = list(self._segments)
        self._stop_event.clear()
        self._resume_state = None
        self._set_busy(True)
        self.progress.set(0)
        self.status_cb("Đang tạo từng đoạn audio...", "yellow")

        self._run_export_do(segments, segments, output_folder)

    def _run_export_do(self, pending_segs, all_segs, output_folder: Path):
        """Chạy synthesis export từng đoạn trong background. Dùng cho cả lần đầu và resume."""
        total = len(all_segs)
        already_done = sum(1 for s in all_segs if s.audio_path and Path(s.audio_path).exists())
        progress_base = (already_done / total) if total > 0 else 0.0
        progress_range = (len(pending_segs) / total) if total > 0 else 1.0
        def _do():
            is_stopped = False
            try:
                engine = create_engine(self.config)
                from core.audio_processor import get_audio_duration_ms
                ffmpeg_path = find_ffmpeg(self.config.get_adv("ffmpeg_path", ""))
                gap = self.config.get_adv("silence_duration_ms", 300)
                _dur_cache: dict = {}
                _seg_status: dict = {}   # index → 'fail' | 'skip'

                # Ordered segment indices — dùng để tính cumulative timestamp real-time
                _seg_order = [s.index for s in all_segs]
                _cursor_state = [0, 0]   # [cursor_ms, next_pos trong _seg_order]
                import threading as _th
                _cursor_lock = _th.Lock()

                def _try_advance():
                    """Tính và cập nhật SRT Mới ngay khi có kết quả liên tiếp"""
                    with _cursor_lock:
                        while _cursor_state[1] < len(_seg_order):
                            idx = _seg_order[_cursor_state[1]]
                            if idx in _dur_cache:
                                dur = _dur_cache[idx]
                                s0 = _cursor_state[0]
                                s1 = s0 + dur
                                _cursor_state[0] = s1 + gap
                                _cursor_state[1] += 1
                                self.after(0, lambda i=idx, a=s0, b=s1:
                                           self._update_row_new_srt(i, a, b))
                            elif _seg_status.get(idx) in ('fail', 'skip'):
                                # Đoạn lỗi/bỏ qua → không có SRT entry, không cộng gap
                                _cursor_state[1] += 1
                            else:
                                break   # chưa có kết quả, dừng

                def _seg_cb(seg, success):
                    if success:
                        try:
                            dur = get_audio_duration_ms(seg.audio_path, ffmpeg_path)
                            if dur <= 0:
                                dur = seg.end_ms - seg.start_ms
                        except Exception:
                            dur = seg.end_ms - seg.start_ms
                        _dur_cache[seg.index] = dur
                        _try_advance()
                    elif self._stop_event.is_set():
                        _seg_status[seg.index] = 'skip'
                        _try_advance()
                        self.after(0, lambda i=seg.index:
                                   self._update_row_status(i, "⏸ bỏ qua", "proc"))
                    else:
                        _seg_status[seg.index] = 'fail'
                        _try_advance()
                        self.after(0, lambda i=seg.index:
                                   self._update_row_status(i, "✗ lỗi (10/10)", "error"))

                def _retry_cb(seg, attempt, max_r):
                    self.after(0, lambda i=seg.index, a=attempt, m=max_r:
                               self._update_row_status(i, f"🔄 thử lại {a}/{m}", "proc"))

                new_segs = engine.synthesize_segments(
                    pending_segs, str(output_folder),
                    prefix="",
                    max_workers=self.config.get_adv("max_workers", 5),
                    progress_cb=lambda d, t: self.after(
                        0, lambda d=d, t=t: self.progress.set(
                            progress_base + (d / t * progress_range) if t > 0 else progress_base
                        )
                    ),
                    segment_cb=_seg_cb,
                    retry_cb=_retry_cb,
                    rate_limit=self.config.get_adv("rate_limit", 1.0),
                    max_retries=10,
                    stop_event=self._stop_event,
                )

                # Ghép kết quả mới vào all_segs
                seg_map = {s.index: s for s in all_segs}
                for s in new_segs:
                    seg_map[s.index] = s
                segs = [seg_map[s.index] for s in all_segs]

                if self._stop_event.is_set():
                    is_stopped = True
                    self._handle_stopped("export", segs,
                                         output_folder=output_folder,
                                         dur_cache=_dur_cache, gap=gap,
                                         ffmpeg_path=ffmpeg_path)
                    return

                # Hoàn thành — tạo playlist và SRT mới
                n_ok = sum(1 for s in segs if s.audio_path and Path(s.audio_path).exists())
                n_fail = len(segs) - n_ok

                playlist_path = output_folder / "_playlist.txt"
                with open(playlist_path, "w", encoding="utf-8") as f:
                    for seg in segs:
                        if seg.audio_path and Path(seg.audio_path).exists():
                            f.write(f"[{seg.index:03d}] {Path(seg.audio_path).name}\n")
                            f.write(f"       {seg.text[:80]}...\n\n")

                try:
                    # UI đã cập nhật real-time trong _try_advance()
                    # Chỉ cần tái tính để build _new_srt_content cho nút "Tải SRT mới"
                    build_cursor = 0
                    srt_lines = []
                    for seg in segs:
                        if not seg.audio_path or not Path(seg.audio_path).exists():
                            continue
                        dur = _dur_cache.get(seg.index)
                        if not dur or dur <= 0:
                            dur = get_audio_duration_ms(seg.audio_path, ffmpeg_path)
                        if dur <= 0:
                            dur = seg.end_ms - seg.start_ms
                        s0, s1 = build_cursor, build_cursor + dur
                        srt_lines += [str(seg.index),
                                      f"{self._fmt_time(s0)} --> {self._fmt_time(s1)}",
                                      seg.text, ""]
                        build_cursor += dur + gap
                    self._new_srt_content = "\n".join(srt_lines)
                except Exception:
                    import traceback
                    traceback.print_exc()
                    self._new_srt_content = ""

                fail_line = f"\n\u26a0 {n_fail} đoạn lỗi" if n_fail else ""
                self.after(0, lambda: self.progress.set(1.0))
                self.after(0, lambda: self.status_cb(
                    f"✓ {n_ok}/{len(segs)} đoạn thành công" + (f" | {n_fail} lỗi" if n_fail else ""),
                    "yellow" if n_fail else "green"
                ))
                self.after(0, lambda: self.btn_open_folder.configure(state="normal"))
                self.after(0, lambda: messagebox.showinfo(
                    "Hoàn tất",
                    f"Đã tạo {n_ok}/{len(segs)} file audio{fail_line}\n\nLưu tại:\n{output_folder}\n\nClick 'Mở folder' để xem"
                ))
            except Exception as e:
                self.after(0, lambda e=e: self.status_cb(f"Lỗi: {e}", "red"))
                self.after(0, lambda e=e: messagebox.showerror("Lỗi", str(e)))
            finally:
                if not is_stopped:
                    self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_do, daemon=True).start()

    # ── Batch (nhiều file) ────────────────────────────────────────────────────────────
    def _batch_run(self, mode: str):
        """Xử lý batch N file tuần tự. mode = 'export' | 'merge'.

        Không hỗ trợ resume — Stop sẽ break loop hoàn toàn. Mỗi file output
        riêng (export → subfolder {stem}_audio/; merge → file {stem}_{ts}.{fmt}).
        """
        files = list(self._batch_files)
        if not files:
            return

        # Snapshot voice + format từ UI (giống single-file flow)
        selected_label = self.voice_combo.get()
        self.config.set("voice_id", self._voice_map.get(selected_label, selected_label))
        fmt = self.fmt_var.get()
        self.config.set("output_format", fmt)
        self.config.save()

        use_timing = self.use_timing_var.get() if mode == "merge" else False
        base_dir = Path(self.config.get("output_dir", "") or _local_desktop())
        base_dir.mkdir(parents=True, exist_ok=True)
        # Nút "Mở folder": export → trỏ vào subfolder segment/; merge → base_dir
        self._last_output_dir = str(base_dir / "segment") if mode == "export" else str(base_dir)

        self._stop_event.clear()
        self._resume_state = None
        self._set_busy(True)
        self.progress.set(0)
        self.status_cb(f"Batch {mode}: 0/{len(files)} files", "yellow")

        def _driver():
            results = []  # list[(filepath, ok: bool, info: str)]
            for idx, fp in enumerate(files, 1):
                if self._stop_event.is_set():
                    results.append((fp, False, "⏸ đã dừng"))
                    break
                self.after(0, lambda i=idx, n=len(files), p=fp:
                           self.status_cb(f"Batch {mode} {i}/{n}: {Path(p).name}", "yellow"))
                self.after(0, lambda i=idx, n=len(files):
                           self.progress.set((i - 1) / n))
                # Mark dòng file đang chạy → trạng thái "🔄 processing"
                self.after(0, lambda p=fp: self._update_batch_row(p, status="🔄 processing", tag="proc"))
                try:
                    segments = srt_parser.parse_file(
                        fp,
                        remove_special=self.config.get_adv("remove_special_chars", True),
                        max_chars=self.config.get_adv("max_chars_per_segment", 500),
                    )
                    self._file_path = fp
                    ok, info, new_range = self._batch_process_one(mode, fp, segments, base_dir, fmt, use_timing)
                    results.append((fp, ok, info))
                    # Update trạng thái + cột SRT Mới (duration audio đã gen)
                    self.after(0, lambda p=fp, o=ok, inf=info, nr=new_range:
                               self._update_batch_row(p,
                                   status=f"✓ {inf}" if o else f"✗ {inf}",
                                   tag="done" if o else "error",
                                   srt_moi=nr))
                except Exception as e:
                    print(f"[Batch {mode}] {fp} fail: {e}")
                    err_msg = f"Lỗi: {str(e)[:60]}"
                    results.append((fp, False, err_msg))
                    self.after(0, lambda p=fp, em=err_msg:
                               self._update_batch_row(p, status=f"✗ {em}", tag="error"))

            # Tổng kết
            n_ok = sum(1 for _, ok, _ in results if ok)
            self.after(0, lambda: self.progress.set(1.0))
            self.after(0, lambda no=n_ok, n=len(files):
                       self.status_cb(f"Batch hoàn tất: {no}/{n} files",
                                       "green" if no == n else "yellow"))
            self.after(0, lambda: self.btn_open_folder.configure(state="normal"))
            summary = "\n".join(f"  • {Path(p).name}: {info}" for p, _, info in results)
            self.after(0, lambda: messagebox.showinfo(
                "Batch hoàn tất",
                f"Đã xử lý {n_ok}/{len(files)} files:\n\n{summary}\n\nLưu tại: {base_dir}"
            ))
            self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_driver, daemon=True).start()

    def _batch_process_one(self, mode: str, file_path: str, segments: list,
                            base_dir: Path, fmt: str, use_timing: bool) -> tuple:
        """Sync — xử lý 1 file. Trả (ok, info_string, new_time_range_str).
        new_time_range_str = '00:00:00,000 --> 00:01:23,456' tính từ duration audio đã gen.
        Block đến khi xong."""
        engine = create_engine(self.config)
        ffmpeg_path = find_ffmpeg(self.config.get_adv("ffmpeg_path", ""))
        max_workers = self.config.get_adv("max_workers", 5)
        rate_limit  = self.config.get_adv("rate_limit", 1.0)
        from core.audio_processor import get_audio_duration_ms
        gap = self.config.get_adv("silence_duration_ms", 300)

        def _calc_total_audio_ms(segs) -> int:
            """Tổng duration audio đã gen + gap giữa segments (giống logic build_audio_from_segments)."""
            total = 0
            cnt = 0
            for s in segs:
                if not s.audio_path or not Path(s.audio_path).exists():
                    continue
                dur = get_audio_duration_ms(s.audio_path, ffmpeg_path) or (s.end_ms - s.start_ms)
                total += dur
                cnt += 1
            if cnt > 1:
                total += gap * (cnt - 1)
            return total

        if mode == "export":
            output_folder = base_dir / "segment"
            output_folder.mkdir(parents=True, exist_ok=True)
            file_stem = Path(file_path).stem
            new_segs = engine.synthesize_segments(
                segments, str(output_folder),
                prefix=file_stem,
                max_workers=max_workers,
                rate_limit=rate_limit,
                max_retries=10,
                stop_event=self._stop_event,
            )
            n_ok = sum(1 for s in new_segs if s.audio_path and Path(s.audio_path).exists())
            total_ms = _calc_total_audio_ms(new_segs)
            new_range = f"{self._fmt_time(0)} --> {self._fmt_time(total_ms)}"
            return n_ok > 0, f"{n_ok}/{len(new_segs)} đoạn → segment/{file_stem}_*", new_range

        # merge mode
        tmp_dir = Path(tempfile.mkdtemp(prefix="ptvoice_batch_"))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = str(base_dir / f"{Path(file_path).stem}_{timestamp}.{fmt}")
        try:
            new_segs = engine.synthesize_segments(
                segments, str(tmp_dir),
                max_workers=max_workers,
                rate_limit=rate_limit,
                max_retries=10,
                stop_event=self._stop_event,
            )
            mp3_path = out_path if fmt == "mp3" else str(tmp_dir / "out.mp3")
            ok = build_audio_from_segments(
                new_segs, mp3_path, ffmpeg_path,
                use_timing=use_timing,
                silence_between=self.config.get_adv("silence_between_segments", True),
                silence_duration_ms=self.config.get_adv("silence_duration_ms", 300),
                trim_silence=self.config.get_adv("trim_silence", True),
            )
            if ok and fmt == "wav":
                from core.audio_processor import convert_to_wav
                ok = convert_to_wav(mp3_path, out_path, ffmpeg_path)
            # Đo duration file cuối (nếu ok) — accurate hơn cộng segments do trim/timing
            total_ms = get_audio_duration_ms(out_path, ffmpeg_path) if ok else _calc_total_audio_ms(new_segs)
            new_range = f"{self._fmt_time(0)} --> {self._fmt_time(total_ms)}"
            return ok, Path(out_path).name if ok else "build fail", new_range
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ── Dừng / Tiếp tục ────────────────────────────────────────────────────────────────

    def _stop_click(self):
        if self._stop_event.is_set():
            # Button đang hiển "▶ Tiếp tục" → resume
            self._resume()
        else:
            # Button đang hiển "⏹ Dừng" → stop
            self._stop_event.set()
            self.btn_stop.configure(state="disabled", text="⏸ Đang dừng...")
            self.status_cb("⏸ Đang dừng quá trình...", "yellow")

    def _handle_stopped(self, mode: str, segs: list, **kwargs):
        """Gọi từ background thread khi stop_event được set."""
        self._resume_state = {"mode": mode, "segs": segs, **kwargs}
        done = sum(1 for s in segs if s.audio_path and Path(s.audio_path).exists())
        total = len(segs)

        def _ui():
            self.btn_export_segments.configure(state="normal")
            self.btn_merge.configure(state="normal")
            self.btn_stop.configure(
                state="normal", text="▶ Tiếp tục",
                fg_color="#2e7d32", hover_color="#1b5e20"
            )
            if self._last_output_dir:
                self.btn_open_folder.configure(state="normal")
            self.status_cb(f"⏸ Đã dừng – {done}/{total} đoạn hoàn thành", "yellow")

        self.after(0, _ui)

    def _resume(self):
        if not self._resume_state:
            return
        state = self._resume_state
        self._resume_state = None
        self._stop_event.clear()

        # Cập nhật UI ngay
        self.btn_stop.configure(
            state="normal", text="⏹ Dừng",
            fg_color="#c62828", hover_color="#8e0000"
        )
        self.btn_export_segments.configure(state="disabled")
        self.btn_merge.configure(state="disabled")
        self.status_cb("▶ Đang tiếp tục...", "yellow")

        segs = state["segs"]
        pending = [s for s in segs if not s.audio_path or not Path(s.audio_path).exists()]
        total = len(segs)
        done = total - len(pending)
        # Đặt progress bar về đúng vị trí đã hoàn thành
        self.progress.set((done / total) if total > 0 else 0)

        if state["mode"] == "export":
            output_folder = state["output_folder"]
            self._run_export_do(pending, segs, output_folder)
        else:
            out_path = state["out_path"]
            tmp_dir = state["tmp_dir"]
            fmt = state["fmt"]
            use_timing = state["use_timing"]
            self._run_merge_do(pending, segs, tmp_dir, out_path, fmt, use_timing)

    def _download_new_srt(self):
        """Lưu file SRT mới (khớp 100% với audio đã tạo)"""
        if not self._new_srt_content:
            messagebox.showwarning("Chưa có SRT", "Hãy tạo audio trước!")
            return
        stem = Path(self._file_path).stem if self._file_path else "output"
        save_path = filedialog.asksaveasfilename(
            initialdir=self._last_output_dir or self.config.get("output_dir", "") or _local_desktop(),
            initialfile=f"{stem}_new.srt",
            defaultextension=".srt",
            filetypes=[("SRT subtitle", "*.srt"), ("All Files", "*.*")],
            title="Lưu file SRT mới",
        )
        if not save_path:
            return
        Path(save_path).write_text(self._new_srt_content, encoding="utf-8")
        self.status_cb(f"✓ Đã lưu {Path(save_path).name}", "green")
        messagebox.showinfo("Đã lưu", f"SRT mới đã lưu tại:\n{save_path}")

    def _open_output_folder(self):
        if not self._last_output_dir or not Path(self._last_output_dir).exists():
            messagebox.showwarning("Chưa có folder", "Vui lòng tạo audio trước!")
            return
        
        import platform
        import subprocess
        
        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                subprocess.Popen(["open", self._last_output_dir])
            elif system == "Windows":
                os.startfile(self._last_output_dir)
            else:  # Linux
                subprocess.Popen(["xdg-open", self._last_output_dir])
            
            self.status_cb(f"✓ Đã mở folder", "green")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể mở folder:\n{e}")
