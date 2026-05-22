"""
Audio Processor — Ghép audio, trim silence, thêm padding
Cross-platform: dùng ffmpeg (tự tìm trong PATH hoặc cạnh executable)
"""
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .srt_parser import Segment


# ── FFmpeg Finder ─────────────────────────────────────────────────────────────

def find_ffmpeg(custom_path: str = "") -> str:
    """Tìm ffmpeg: custom_path → cạnh script → PATH"""
    if custom_path and Path(custom_path).exists():
        return custom_path

    # Cạnh file script/executable
    base = Path(__file__).parent.parent
    candidates = ["ffmpeg", "ffmpeg.exe"]
    for name in candidates:
        local = base / name
        if local.exists():
            return str(local)

    # Trong PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    # macOS: kiểm tra các đường dẫn Homebrew phổ biến
    if platform.system() == "Darwin":
        brew_paths = [
            "/opt/homebrew/bin/ffmpeg",       # Apple Silicon
            "/usr/local/bin/ffmpeg",           # Intel Mac
        ]
        for bp in brew_paths:
            if os.path.isfile(bp) and os.access(bp, os.X_OK):
                return bp

    raise FileNotFoundError(
        "Không tìm thấy ffmpeg!\n"
        "- Windows: đặt ffmpeg.exe cạnh main.py hoặc thêm vào PATH\n"
        "- macOS: chạy 'brew install ffmpeg'"
    )


def run_ffmpeg(args: List[str], ffmpeg_path: str = "ffmpeg") -> bool:
    """Chạy lệnh ffmpeg, ẩn cửa sổ console trên Windows"""
    cmd = [ffmpeg_path] + args
    kwargs: dict = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore
    try:
        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode != 0:
            print(f"[FFmpeg] Error: {proc.stderr.decode(errors='replace')[-500:]}")
            return False
        return True
    except FileNotFoundError:
        print(f"[FFmpeg] Không tìm thấy: {ffmpeg_path}")
        return False


# ── Core functions ────────────────────────────────────────────────────────────

def generate_silence(duration_ms: int, output_path: str, ffmpeg: str = "ffmpeg") -> bool:
    """Tạo file audio im lặng có độ dài xác định"""
    duration_s = duration_ms / 1000.0
    return run_ffmpeg([
        "-f", "lavfi",
        "-i", f"anullsrc=r=24000:cl=mono",
        "-t", f"{duration_s:.3f}",
        "-q:a", "9",
        "-acodec", "libmp3lame",
        "-y", output_path,
    ], ffmpeg)


def concat_audio_files(
    file_list: List[str],
    output_path: str,
    ffmpeg: str = "ffmpeg",
) -> bool:
    """Nối nhiều file audio thành 1 file duy nhất"""
    if not file_list:
        return False

    # Dùng concat demuxer (ổn định nhất cho nhiều file)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for fp in file_list:
            # Escape đường dẫn cho ffmpeg concat
            escaped = fp.replace("\\", "/").replace("'", "\\'")
            f.write(f"file '{escaped}'\n")
        list_path = f.name

    try:
        ok = run_ffmpeg([
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-y", output_path,
        ], ffmpeg)
    finally:
        Path(list_path).unlink(missing_ok=True)
    return ok


def build_audio_from_segments(
    segments: List[Segment],
    output_path: str,
    ffmpeg: str = "ffmpeg",
    use_timing: bool = True,
    silence_between: bool = True,
    silence_duration_ms: int = 300,
    trim_silence: bool = True,
) -> bool:
    """
    Ghép các đoạn audio từ segments.audio_path thành 1 file hoàn chỉnh.

    - use_timing=True  : chèn khoảng lặng theo timing SRT (start_ms)
    - use_timing=False : chỉ nối thẳng, thêm gap cố định nếu silence_between=True
    """
    if not segments:
        return False

    tmp_dir = Path(tempfile.mkdtemp(prefix="ptvoice_"))
    file_queue: List[str] = []

    try:
        prev_end_ms = 0

        for seg in segments:
            if not seg.audio_path or not Path(seg.audio_path).exists():
                continue

            if use_timing:
                # Khoảng lặng trước đoạn này
                gap_ms = seg.start_ms - prev_end_ms
                if gap_ms > 50:  # Bỏ qua gap < 50ms
                    sil = str(tmp_dir / f"sil_{seg.index:04d}.mp3")
                    generate_silence(gap_ms, sil, ffmpeg)
                    if Path(sil).exists():
                        file_queue.append(sil)
            elif silence_between and file_queue:
                sil = str(tmp_dir / f"sil_{seg.index:04d}.mp3")
                generate_silence(silence_duration_ms, sil, ffmpeg)
                if Path(sil).exists():
                    file_queue.append(sil)

            file_queue.append(seg.audio_path)
            prev_end_ms = seg.end_ms

        if not file_queue:
            return False

        # Nối tất cả
        merged = str(tmp_dir / "merged.mp3")
        if not concat_audio_files(file_queue, merged, ffmpeg):
            return False

        # Trim silence đầu/cuối
        if trim_silence:
            trimmed = str(tmp_dir / "trimmed.mp3")
            ok = run_ffmpeg([
                "-i", merged,
                "-af", "silenceremove=start_periods=1:start_threshold=-60dB"
                       ":stop_periods=1:stop_threshold=-60dB",
                "-y", trimmed,
            ], ffmpeg)
            if ok and Path(trimmed).exists():
                merged = trimmed

        # Chuyển ra output cuối cùng
        shutil.copy2(merged, output_path)
        return True

    except Exception as e:
        print(f"[AudioProcessor] Lỗi: {e}")
        return False
    finally:
        # Dọn dẹp temp
        shutil.rmtree(tmp_dir, ignore_errors=True)


def get_audio_duration_ms(file_path: str, ffmpeg: str = "ffmpeg") -> int:
    """Lấy độ dài thực của file audio (ms) bằng ffprobe/ffmpeg."""
    # Thử ffprobe trước (cùng thư mục với ffmpeg)
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe").replace("ffmpeg.exe", "ffprobe.exe")
    for probe in [ffprobe, "ffprobe", "ffprobe.exe"]:
        try:
            result = subprocess.run(
                [probe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", file_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                **({} if platform.system() != "Windows" else {"creationflags": subprocess.CREATE_NO_WINDOW}),
            )
            if result.returncode == 0:
                val = result.stdout.decode().strip()
                if val:
                    return int(float(val) * 1000)
        except FileNotFoundError:
            continue

    # Fallback: dùng ffmpeg -i để đọc duration từ stderr
    try:
        result = subprocess.run(
            [ffmpeg, "-i", file_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **({} if platform.system() != "Windows" else {"creationflags": subprocess.CREATE_NO_WINDOW}),
        )
        for line in result.stderr.decode(errors="replace").splitlines():
            if "Duration:" in line:
                # "  Duration: 00:00:03.45, ..."
                m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", line)
                if m:
                    h, mi, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    return h * 3_600_000 + mi * 60_000 + s * 1_000 + cs * 10
    except Exception:
        pass
    return 0


def convert_to_wav(input_path: str, output_path: str, ffmpeg: str = "ffmpeg") -> bool:
    """Chuyển MP3 → WAV (PCM 16-bit 44100Hz)"""
    return run_ffmpeg([
        "-i", input_path,
        "-acodec", "pcm_s16le",
        "-ar", "44100",
        "-ac", "1",
        "-y", output_path,
    ], ffmpeg)
