"""
VieNeu-TTS auto-installer (sidecar runtime, KHÔNG bundle vào .exe).

Khi user chọn engine VieNeu lần đầu → tải `uv` (Python package manager 1-file) →
tạo venv riêng tại data/vieneu → cài `vieneu` (CPU/ONNX) hoặc `vieneu[gpu]`
(NVIDIA CUDA) tùy phần cứng auto-detect. Model tự tải từ HuggingFace lần infer đầu.

Tách runtime (data/vieneu) khỏi giọng clone (data/vieneu_clones) → "Gỡ VieNeu"
xoá runtime nhưng GIỮ giọng clone.

Public API:
    detect_hardware() -> "gpu" | "cpu"
    is_installed() -> bool
    find_free_port() -> int
    venv_python() -> Path
    install_async(progress_cb, on_done, cancel_event, proxy) -> Thread
    uninstall() -> bool
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Progress callback: (stage, percent, message)
ProgressCb = Callable[[str, int, str], None]

_IS_WIN = platform.system() == "Windows"
_SUBPROCESS_FLAGS = 0x08000000 if _IS_WIN else 0  # CREATE_NO_WINDOW

# Model mặc định: "" = dùng default của package (v3-Turbo, ONNX — tối ưu CPU).
# (model_name="...v2" gây TypeError ở local mode → fallback default; v3-Turbo
#  ONNX chạy CPU tốt hơn v2/neucodec nên dùng luôn default.)
DEFAULT_MODEL = ""

# Tên app "của mình" (nơi cài MỚI) + danh sách tên fallback để DISCOVER install
# có sẵn từ tool khác (cùng máy). Thứ tự = thứ tự ưu tiên.
_OWN_APP_NAME = "PT-AI-Voice"
_SIBLING_APP_NAMES = ["AutoYTB"]  # share runtime + clones với Auto-YTB nếu có


# ── Paths ───────────────────────────────────────────────────────────────
# CỐ TÌNH dùng %LOCALAPPDATA% / Application Support — KHÔNG nằm OneDrive (tránh
# sync vài GB venv = thảm hoạ). VieNeu lưu HOÀN TOÀN local máy.
#
# DISCOVERY: nếu thấy install hiện có ở Auto-YTB (cùng máy) → DÙNG CHUNG, không
# bắt user cài lại 0.8GB. Tool nào cài trước thì các tool sau auto-detect path.

def _base_for(app_name: str) -> Path:
    """Path base local cho 1 app name cụ thể (KHÔNG tạo dir)."""
    if _IS_WIN:
        root = os.environ.get("LOCALAPPDATA", "") or str(Path.home() / "AppData" / "Local")
        return Path(root) / app_name
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    xdg = os.environ.get("XDG_DATA_HOME", "")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / app_name


def _own_base() -> Path:
    """Base dir của riêng PT-AI-Voice (cho install MỚI). Tạo nếu chưa có."""
    base = _base_for(_OWN_APP_NAME)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _discover_existing_runtime() -> Optional[Path]:
    """Tìm install VieNeu có sẵn (own → siblings). Trả None nếu chưa có."""
    for name in [_OWN_APP_NAME] + _SIBLING_APP_NAMES:
        cand = _base_for(name) / "vieneu"
        marker = cand / ".installed"
        py = (cand / "venv" / "Scripts" / "python.exe") if _IS_WIN else (cand / "venv" / "bin" / "python")
        if marker.exists() and py.exists():
            return cand
    return None


def _discover_existing_clones() -> Optional[Path]:
    """Tìm clones dir có sẵn (own → siblings). Trả None nếu chưa có."""
    for name in [_OWN_APP_NAME] + _SIBLING_APP_NAMES:
        cand = _base_for(name) / "vieneu_clones"
        if cand.exists() and any(cand.iterdir()):
            return cand
    return None


def _local_base() -> Path:
    """Deprecated alias — giữ cho code cũ nếu có. Dùng _own_base()."""
    return _own_base()


def vieneu_dir() -> Path:
    """Runtime dir VieNeu (uv + venv + marker), LOCAL.

    Nếu thấy install có sẵn (Auto-YTB hoặc PT-AI-Voice cũ) → trả path đó.
    Else tạo + trả path PT-AI-Voice (cho install mới).
    """
    existing = _discover_existing_runtime()
    if existing is not None:
        return existing
    d = _own_base() / "vieneu"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clones_dir() -> Path:
    """Giọng clone, LOCAL — share với app cùng máy nếu có sẵn."""
    existing = _discover_existing_clones()
    if existing is not None:
        return existing
    d = _own_base() / "vieneu_clones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _uv_bin() -> Path:
    return vieneu_dir() / "bin" / ("uv.exe" if _IS_WIN else "uv")


def _venv_dir() -> Path:
    return vieneu_dir() / "venv"


def venv_python() -> Path:
    """Path tới python trong venv VieNeu."""
    if _IS_WIN:
        return _venv_dir() / "Scripts" / "python.exe"
    return _venv_dir() / "bin" / "python"


def _marker() -> Path:
    return vieneu_dir() / ".installed"


# ── Detection ─────────────────────────────────────────────────────────────

def detect_hardware() -> str:
    """Trả 'gpu' nếu có NVIDIA GPU (nvidia-smi chạy được), else 'cpu'.

    macOS Apple Silicon → vẫn trả 'cpu' (VieNeu CPU/ONNX chạy tốt; MPS để SDK
    tự dùng nếu cài bản gpu, nhưng ta ưu tiên CPU build cho đơn giản trên Mac).
    """
    exe = shutil.which("nvidia-smi")
    if not exe and _IS_WIN:
        # nvidia-smi thường ở System32 nhưng có thể thiếu PATH
        _cand = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        if _cand.exists():
            exe = str(_cand)
    if not exe:
        return "cpu"
    try:
        r = subprocess.run([exe], capture_output=True, timeout=8,
                           creationflags=_SUBPROCESS_FLAGS)
        return "gpu" if r.returncode == 0 else "cpu"
    except Exception:
        return "cpu"


def is_installed() -> bool:
    """True nếu venv + marker tồn tại (đã cài xong)."""
    return _marker().exists() and venv_python().exists()


def installed_info() -> dict:
    """Đọc marker → {hardware, model, ts, version}. {} nếu chưa cài."""
    try:
        return json.loads(_marker().read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_free_port(start: int = 7870, tries: int = 50) -> int:
    """Tìm 1 port TCP trống cho sidecar (dò từ `start`).

    Bind thử 127.0.0.1:port → trống thì trả. Fallback: để OS cấp port (0).
    """
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    # Tất cả bận → để OS tự cấp
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── uv download ─────────────────────────────────────────────────────────

def _uv_asset_name() -> Optional[str]:
    """Tên asset uv theo OS/arch (GitHub release astral-sh/uv)."""
    m = platform.machine().lower()
    is_arm = m in ("arm64", "aarch64")
    if _IS_WIN:
        return "uv-x86_64-pc-windows-msvc.zip"
    if platform.system() == "Darwin":
        return "uv-aarch64-apple-darwin.tar.gz" if is_arm else "uv-x86_64-apple-darwin.tar.gz"
    # Linux
    return "uv-aarch64-unknown-linux-gnu.tar.gz" if is_arm else "uv-x86_64-unknown-linux-gnu.tar.gz"


def _download_uv(progress_cb: ProgressCb, cancel_event=None, proxy: str = "") -> bool:
    """Tải uv binary về data/vieneu/bin/. Trả True nếu OK / đã có sẵn."""
    if _uv_bin().exists():
        return True
    asset = _uv_asset_name()
    if not asset:
        progress_cb("uv", 0, "✗ Không hỗ trợ OS/arch này cho uv")
        return False
    url = f"https://github.com/astral-sh/uv/releases/latest/download/{asset}"
    _uv_bin().parent.mkdir(parents=True, exist_ok=True)
    tmp = vieneu_dir() / asset
    progress_cb("uv", 5, "Đang tải uv (Python package manager)…")
    try:
        opener = urllib.request.build_opener()
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(url, timeout=60) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            read = 0
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    progress_cb("uv", 0, "⚠ Hủy bởi user")
                    return False
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if total > 0:
                    progress_cb("uv", min(40, int(read / total * 35 + 5)),
                                f"Đang tải uv… {read // 1024}/{total // 1024} KB")
        # Extract
        if asset.endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(tmp) as z:
                for n in z.namelist():
                    if n.endswith("uv.exe") or n.endswith("/uv") or n == "uv":
                        with z.open(n) as src, open(_uv_bin(), "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        break
        else:
            import tarfile
            with tarfile.open(tmp) as t:
                for member in t.getmembers():
                    if member.name.endswith("/uv") or member.name == "uv":
                        src = t.extractfile(member)
                        if src:
                            with open(_uv_bin(), "wb") as dst:
                                shutil.copyfileobj(src, dst)
                        break
            os.chmod(_uv_bin(), 0o755)
        tmp.unlink(missing_ok=True)
        if not _uv_bin().exists():
            progress_cb("uv", 0, "✗ Giải nén uv thất bại")
            return False
        progress_cb("uv", 40, "✓ Đã tải uv")
        return True
    except Exception as e:
        progress_cb("uv", 0, f"✗ Lỗi tải uv: {str(e)[:160]}")
        return False


# ── Subprocess streaming (progress + cancel) ──────────────────────────────

def _stream(cmd: list, progress_cb: ProgressCb, stage: str, base_pct: int,
            span_pct: int, cancel_event=None, env: Optional[dict] = None,
            no_progress_timeout_s: int = 300) -> int:
    """Chạy cmd, stream stdout → progress. Trả returncode (-1 nếu cancel/timeout)."""
    import queue as _q
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_SUBPROCESS_FLAGS, env=env,
        )
    except Exception as e:
        progress_cb(stage, 0, f"✗ Không chạy được: {str(e)[:160]}")
        return -2
    out_q: "_q.Queue[Optional[str]]" = _q.Queue()

    def _reader():
        try:
            for line in proc.stdout or []:
                out_q.put(line)
        finally:
            out_q.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    last = time.time()
    while True:
        try:
            line = out_q.get(timeout=1.0)
        except _q.Empty:
            if cancel_event is not None and cancel_event.is_set():
                _kill(proc)
                return -1
            if time.time() - last > no_progress_timeout_s:
                progress_cb(stage, 0, f"✗ Timeout {no_progress_timeout_s}s — dừng")
                _kill(proc)
                return -1
            continue
        if line is None:
            break
        line = line.rstrip()
        if not line:
            continue
        last = time.time()
        progress_cb(stage, base_pct + span_pct // 2, line[:180])
    try:
        return proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _kill(proc)
        return -1


def _kill(proc) -> None:
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        proc.kill()
    except Exception:
        pass


def _proxy_env(proxy: str) -> dict:
    """Env kế thừa + inject proxy cho uv/pip/HF."""
    env = dict(os.environ)
    if proxy:
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["ALL_PROXY"] = proxy
    return env


# ── Install / Uninstall ───────────────────────────────────────────────────

def install_async(progress_cb: ProgressCb,
                  on_done: Optional[Callable[[bool, str], None]] = None,
                  cancel_event=None, proxy: str = "") -> threading.Thread:
    """Spawn thread cài VieNeu: uv → venv → pip install vieneu[gpu|cpu].

    progress_cb(stage, percent, message); stage: uv|venv|pip|done|error.
    """

    def _worker():
        try:
            hw = detect_hardware()
            progress_cb("uv", 2, f"Phát hiện phần cứng: {'GPU NVIDIA' if hw == 'gpu' else 'CPU'}")

            # 1. uv
            if not _download_uv(progress_cb, cancel_event, proxy):
                if on_done:
                    on_done(False, "Tải uv thất bại")
                return
            if cancel_event and cancel_event.is_set():
                if on_done: on_done(False, "Cancelled by user")
                return

            env = _proxy_env(proxy)

            # 2. venv (uv tự tải Python 3.12 nếu thiếu)
            progress_cb("venv", 45, "Đang tạo môi trường Python (tải Python nếu cần)…")
            rc = _stream([str(_uv_bin()), "venv", str(_venv_dir()), "--python", "3.12"],
                         progress_cb, "venv", 45, 15, cancel_event, env)
            if rc != 0:
                if on_done: on_done(False, "Tạo venv thất bại" if rc != -1 else "Cancelled by user")
                return

            # 3. pip install vieneu
            pkg = "vieneu[gpu]" if hw == "gpu" else "vieneu"
            progress_cb("pip", 62, f"Đang cài {pkg} (có thể tải lớn, vui lòng đợi)…")
            rc = _stream([str(_uv_bin()), "pip", "install", "--python", str(venv_python()), pkg],
                         progress_cb, "pip", 62, 35, cancel_event, env,
                         no_progress_timeout_s=600)
            if rc != 0:
                if on_done: on_done(False, "Cài vieneu thất bại" if rc != -1 else "Cancelled by user")
                return

            # 4. Warm-up: tải model từ HuggingFace NGAY (≈0.5GB) để lần đọc đầu
            #    KHÔNG bị treo im lặng. Init Vieneu() trigger download + load.
            progress_cb("model", 90, "Đang tải model giọng nói (~0.5GB, 1 lần)…")
            rc = _stream([str(venv_python()), "-c", "from vieneu import Vieneu; Vieneu()"],
                         progress_cb, "model", 90, 9, cancel_event, env,
                         no_progress_timeout_s=600)
            if rc != 0:
                if on_done: on_done(False, "Tải model thất bại" if rc != -1 else "Cancelled by user")
                return

            # 5. Marker
            _marker().write_text(json.dumps({
                "hardware": hw, "model": DEFAULT_MODEL or "default(v3-Turbo)", "package": pkg,
            }, ensure_ascii=False), encoding="utf-8")

            progress_cb("done", 100, "✓ Cài VieNeu-TTS hoàn tất!")
            if on_done:
                on_done(True, f"VieNeu sẵn sàng ({'GPU' if hw == 'gpu' else 'CPU'})")
        except Exception as e:
            progress_cb("error", 0, f"✗ Lỗi: {str(e)[:200]}")
            if on_done:
                on_done(False, str(e)[:200])

    t = threading.Thread(target=_worker, daemon=True, name="vieneu-installer")
    t.start()
    return t


def is_shared_install() -> bool:
    """True nếu runtime hiện đang dùng nằm ở app KHÁC (vd Auto-YTB), không phải
    của PT-AI-Voice. Dùng để cảnh báo trước khi user Gỡ — tránh xóa nhầm install
    chung mà tool khác đang dùng."""
    own_runtime = _own_base() / "vieneu"
    return vieneu_dir() != own_runtime


def uninstall() -> bool:
    """Xoá runtime VieNeu (uv + venv + model marker). GIỮ giọng clone.

    Chỉ xóa nếu runtime nằm dưới base của PT-AI-Voice. Nếu runtime đang share
    với app khác (Auto-YTB) → refuse và return False (UI nên hỏi
    is_shared_install() trước để cảnh báo user).
    """
    if is_shared_install():
        return False
    try:
        d = vieneu_dir()
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        return not d.exists()
    except Exception:
        return False
