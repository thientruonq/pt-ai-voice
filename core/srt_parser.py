"""
SRT / VTT Parser — Phân tích file phụ đề cross-platform
Hỗ trợ: .srt, .vtt, plain text
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

_ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1")


# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class Segment:
    index: int
    start_ms: int       # thời gian bắt đầu (ms)
    end_ms: int         # thời gian kết thúc (ms)
    text: str
    audio_path: str = field(default="", compare=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

_HTML_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")
_SPECIAL_RE = re.compile(r"[#@$%^&*~`|\\<>{}[\]]")
# Split tại ranh giới câu — . ! ? theo sau bởi space (giữ delimiter với lookbehind)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")


def split_long_text(text: str, max_chars: int) -> List[str]:
    """Chia text dài thành list part <= max_chars, cắt tại ranh giới câu.

    - Không cắt giữa câu nếu có thể tránh (gộp các câu cho vừa max_chars).
    - Nếu 1 câu > max_chars → hard-split theo max_chars (không còn lựa chọn).
    - Text <= max_chars → trả [text].
    """
    text = text.strip()
    if len(text) <= max_chars or max_chars <= 0:
        return [text] if text else []

    parts: List[str] = []
    current = ""
    for sent in _SENTENCE_SPLIT_RE.split(text):
        sent = sent.strip()
        if not sent:
            continue
        # Câu đơn quá dài → xả current, hard-split câu này
        if len(sent) > max_chars:
            if current:
                parts.append(current)
                current = ""
            for i in range(0, len(sent), max_chars):
                parts.append(sent[i:i + max_chars])
            continue
        # Gộp câu vào current nếu vẫn vừa
        candidate = f"{current} {sent}".strip() if current else sent
        if len(candidate) <= max_chars:
            current = candidate
        else:
            parts.append(current)
            current = sent
    if current:
        parts.append(current)
    return parts


def time_to_ms(t: str) -> int:
    """'00:01:23,456' hoặc '00:01:23.456' → milliseconds"""
    t = t.replace(".", ",")
    parts = re.split(r"[:,]", t)
    if len(parts) == 4:
        h, m, s, ms = map(int, parts)
        return h * 3_600_000 + m * 60_000 + s * 1_000 + ms
    return 0


def ms_to_time(ms: int) -> str:
    """milliseconds → '00:01:23,456'"""
    ms = max(0, int(ms))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def clean_text(text: str, remove_special: bool = True) -> str:
    text = _HTML_RE.sub("", text)
    if remove_special:
        text = _SPECIAL_RE.sub("", text)
    return _MULTI_SPACE_RE.sub(" ", text).strip()


def read_file_safe(path: str) -> str:
    """Đọc file với nhiều encoding, raise nếu không được"""
    for enc in _ENCODINGS:
        try:
            return Path(path).read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError(f"Không đọc được file: {path}")


# ── Parsers ───────────────────────────────────────────────────────────────────

class SRTParser:
    """Parse file .srt"""

    def __init__(self, remove_special: bool = True, max_chars: int = 500):
        self.remove_special = remove_special
        self.max_chars = max_chars

    def parse_file(self, filepath: str) -> List[Segment]:
        return self.parse(read_file_safe(filepath))

    def parse(self, content: str) -> List[Segment]:
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        blocks = re.split(r"\n{2,}", content.strip())
        segments: List[Segment] = []
        next_idx = 1  # re-index tuần tự (sub-segments không trùng file name)

        for block in blocks:
            lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
            if len(lines) < 3:
                continue
            try:
                _ = int(lines[0])
            except ValueError:
                continue

            tc = re.match(
                r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})",
                lines[1],
            )
            if not tc:
                continue

            text = clean_text(" ".join(lines[2:]), self.remove_special)
            if not text:
                continue

            start_ms = time_to_ms(tc.group(1))
            end_ms = time_to_ms(tc.group(2))
            # Split câu dài → nhiều sub-segments, chia timing tuyến tính theo char
            parts = split_long_text(text, self.max_chars)
            if not parts:
                continue
            total_chars = sum(len(p) for p in parts) or 1
            total_dur = max(0, end_ms - start_ms)
            cur_start = start_ms
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    part_end = end_ms  # phần cuối bám sát end_ms gốc
                else:
                    part_end = cur_start + int(total_dur * len(part) / total_chars)
                segments.append(Segment(
                    index=next_idx,
                    start_ms=cur_start,
                    end_ms=part_end,
                    text=part,
                ))
                next_idx += 1
                cur_start = part_end
        return segments


class VTTParser:
    """Parse file .vtt (WebVTT)"""

    def __init__(self, remove_special: bool = True, max_chars: int = 500):
        self.remove_special = remove_special
        self.max_chars = max_chars
        self._srt = SRTParser(remove_special, max_chars)

    def parse_file(self, filepath: str) -> List[Segment]:
        return self.parse(read_file_safe(filepath))

    def parse(self, content: str) -> List[Segment]:
        # Bỏ header WEBVTT và NOTE
        content = re.sub(r"WEBVTT.*?\n", "\n", content)
        content = re.sub(r"NOTE[^\n]*\n.*?\n", "\n", content, flags=re.DOTALL)
        # VTT dùng dấu chấm thay dấu phẩy → chuẩn hóa
        content = re.sub(r"(\d{2}:\d{2}:\d{2})\.(\d{3})", r"\1,\2", content)
        # Thêm index giả nếu không có
        blocks = re.split(r"\n{2,}", content.strip())
        srt_blocks = []
        for i, blk in enumerate(blocks, 1):
            lines = [ln.strip() for ln in blk.split("\n") if ln.strip()]
            if not lines:
                continue
            if "-->" not in lines[0]:
                srt_blocks.append(blk)
            else:
                srt_blocks.append(f"{i}\n{blk}")
        return self._srt.parse("\n\n".join(srt_blocks))


class TXTParser:
    """Chia text thuần thành các đoạn theo dòng/câu"""

    def __init__(self, max_chars: int = 500):
        self.max_chars = max_chars

    def parse(self, content: str, ms_per_char: int = 80) -> List[Segment]:
        """ms_per_char: ước tính thời gian đọc mỗi ký tự (ms)"""
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        segments: List[Segment] = []
        cursor_ms = 0
        next_idx = 1
        for line in lines:
            # Split câu dài → nhiều sub-segments (không truncate)
            for part in split_long_text(line, self.max_chars):
                duration = max(len(part) * ms_per_char, 500)
                segments.append(Segment(
                    index=next_idx,
                    start_ms=cursor_ms,
                    end_ms=cursor_ms + duration,
                    text=part,
                ))
                cursor_ms += duration + 300  # 300ms gap
                next_idx += 1
        return segments


def parse_file(filepath: str, **kwargs) -> List[Segment]:
    """Auto-detect định dạng và parse"""
    ext = Path(filepath).suffix.lower()
    if ext == ".vtt":
        return VTTParser(**kwargs).parse_file(filepath)
    if ext == ".txt":
        content = read_file_safe(filepath)
        return TXTParser(kwargs.get("max_chars", 500)).parse(content)
    # Mặc định SRT
    return SRTParser(**kwargs).parse_file(filepath)


def build_new_srt(segments: List[Segment], gap_ms: int = 300,
                  ffmpeg: str = "ffmpeg") -> str:
    """
    Tạo nội dung SRT mới dựa trên duration thực của từng file audio.
    Timestamps khớp 100% với audio đã tổng hợp.

    gap_ms: khoảng lặng giữa các đoạn (ms), mặc định 300ms
    """
    from core.audio_processor import get_audio_duration_ms

    lines: List[str] = []
    cursor_ms = 0

    for seg in segments:
        if not seg.audio_path:
            continue
        from pathlib import Path as _Path
        if not _Path(seg.audio_path).exists():
            continue

        dur = get_audio_duration_ms(seg.audio_path, ffmpeg)
        if dur <= 0:
            dur = seg.end_ms - seg.start_ms  # fallback về SRT gốc

        start = ms_to_time(cursor_ms)
        end = ms_to_time(cursor_ms + dur)
        lines.append(f"{seg.index}")
        lines.append(f"{start} --> {end}")
        lines.append(seg.text)
        lines.append("")
        cursor_ms += dur + gap_ms

    return "\n".join(lines)
