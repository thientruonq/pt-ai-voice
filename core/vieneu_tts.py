"""
VieNeu-TTS engine — chạy local qua sidecar HTTP (venv riêng %LOCALAPPDATA%/PT-AI-Voice/vieneu).

- Sidecar server (script nhúng dạng string, ghi ra disk lúc chạy → frozen .exe-safe)
  chạy bằng venv python, load model warm.
- VieNeuTTSEngine(TTSEngine) cắm vào pipeline qua factory create_engine.
- Giọng clone lưu local %LOCALAPPDATA%/PT-AI-Voice/vieneu_clones/<slug>/
  (tách khỏi runtime → Gỡ runtime vẫn GIỮ clone).

Voice id quy ước (lưu trong settings.voice_id):
    ""/"default"     → giọng mặc định VieNeu
    "preset:<name>"  → giọng preset theo tên (vd "preset:Ngọc Lan")
    "clone:<slug>"   → giọng clone (ref_audio = clones/<slug>/ref.wav)
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional

from .tts_engine import TTSEngine
from . import vieneu_installer as _inst

_IS_WIN = __import__("platform").system() == "Windows"
_SUBPROCESS_FLAGS = 0x08000000 if _IS_WIN else 0


# ── Sidecar server script (nhúng → ghi ra disk; venv python chạy) ──────────
_SIDECAR_SOURCE = r'''
import argparse, json, sys, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
_TTS = None
_MODEL = ""
def _get_tts():
    global _TTS
    if _TTS is None:
        from vieneu import Vieneu
        if _MODEL:
            try:
                _TTS = Vieneu(model_name=_MODEL)
            except TypeError:
                _TTS = Vieneu()
        else:
            _TTS = Vieneu()
    return _TTS
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="text/plain"):
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        try: self.wfile.write(body)
        except Exception: pass
    def do_GET(self):
        if self.path == "/health": self._send(200, b"ok"); return
        if self.path == "/voices":
            try:
                t=_get_tts(); out=[]
                try:
                    for label, vid in t.list_preset_voices():
                        out.append({"name": str(label), "voice_id": str(vid)})
                except Exception: pass
                self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"), "application/json")
            except Exception as e: self._send(500, str(e).encode("utf-8"))
            return
        self._send(404, b"nf")
    def do_POST(self):
        if self.path != "/synth": self._send(404, b"nf"); return
        try:
            n=int(self.headers.get("Content-Length",0) or 0)
            d=json.loads(self.rfile.read(n) or b"{}")
        except Exception as e: self._send(400, str(e).encode("utf-8")); return
        text=(d.get("text") or "").strip()
        if not text: self._send(400, b"empty"); return
        ref=d.get("ref_audio") or ""; voice=d.get("voice") or ""
        try:
            t=_get_tts(); kw={}
            if ref and Path(ref).exists(): kw["ref_audio"]=ref
            elif voice: kw["voice"]=voice
            audio=t.infer(text=text, **kw)
            tmp=Path(tempfile.gettempdir())/("_vn_%d.wav"%id(audio))
            t.save(audio, str(tmp)); wav=tmp.read_bytes()
            try: tmp.unlink()
            except OSError: pass
            self._send(200, wav, "audio/wav")
        except Exception as e:
            import traceback; traceback.print_exc()
            self._send(500, ("infer error: %s"%e).encode("utf-8"))
def main():
    global _MODEL
    ap=argparse.ArgumentParser(); ap.add_argument("--port",type=int,required=True)
    ap.add_argument("--model",default=""); a=ap.parse_args(); _MODEL=a.model or ""
    srv=ThreadingHTTPServer(("127.0.0.1",a.port),H)
    print("[VieNeuSidecar] listening %d model=%s"%(a.port,_MODEL), flush=True)
    srv.serve_forever()
if __name__=="__main__": main()
'''


def _sidecar_script_path() -> Path:
    """Ghi script sidecar ra disk (idempotent) → trả path để venv python chạy."""
    p = _inst.vieneu_dir() / "sidecar_server.py"
    try:
        if not p.exists() or p.read_text(encoding="utf-8") != _SIDECAR_SOURCE:
            p.write_text(_SIDECAR_SOURCE, encoding="utf-8")
    except Exception:
        p.write_text(_SIDECAR_SOURCE, encoding="utf-8")
    return p


# ── Sidecar lifecycle (singleton, warm suốt session) ──────────────────────
class _Sidecar:
    _lock = threading.Lock()
    _proc: Optional[subprocess.Popen] = None
    _port: int = 0
    _logf = None  # file handle log sidecar (đóng ở stop())
    _log_path = None

    @classmethod
    def base_url(cls) -> str:
        return f"http://127.0.0.1:{cls._port}" if cls._port else ""

    @classmethod
    def _alive(cls) -> bool:
        if not cls._port or cls._proc is None or cls._proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"{cls.base_url()}/health", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    @classmethod
    def ensure(cls, model: str, timeout_s: int = 60) -> str:
        """Đảm bảo sidecar đang chạy → trả base_url. Raise nếu fail."""
        with cls._lock:
            if cls._alive():
                return cls.base_url()
            if not _inst.is_installed():
                raise RuntimeError("VieNeu chưa cài. Vào Settings → chọn VieNeu để tải.")
            cls._port = _inst.find_free_port()
            script = _sidecar_script_path()
            cmd = [str(_inst.venv_python()), str(script),
                   "--port", str(cls._port), "--model", model]
            # CRITICAL: redirect stdout/stderr ra LOG FILE, KHÔNG dùng PIPE.
            # vieneu/torch/HF in nhiều (progress model, warning) → PIPE buffer
            # (~64KB) đầy + không ai đọc → sidecar block giữa lúc infer → treo.
            # Ghi log file vừa tránh deadlock vừa giữ chẩn đoán.
            cls._log_path = _inst.vieneu_dir() / "sidecar.log"
            cls._logf = open(cls._log_path, "w", encoding="utf-8", errors="replace")
            cls._proc = subprocess.Popen(
                cmd, stdout=cls._logf, stderr=subprocess.STDOUT,
                creationflags=_SUBPROCESS_FLAGS,
            )
            # Chờ /health
            t0 = time.time()
            while time.time() - t0 < timeout_s:
                if cls._proc.poll() is not None:
                    out = ""
                    try:
                        out = cls._log_path.read_text(encoding="utf-8", errors="replace")[-300:]
                    except Exception:
                        pass
                    raise RuntimeError(f"Sidecar VieNeu thoát sớm. {out}")
                if cls._alive():
                    return cls.base_url()
                time.sleep(0.5)
            cls.stop()
            raise RuntimeError("Sidecar VieNeu không phản hồi (timeout).")

    @classmethod
    def stop(cls):
        with cls._lock:
            if cls._proc is not None:
                try:
                    cls._proc.terminate()
                    try:
                        cls._proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        cls._proc.kill()
                except Exception:
                    pass
            if cls._logf is not None:
                try:
                    cls._logf.close()
                except Exception:
                    pass
            cls._logf = None
            cls._proc = None
            cls._port = 0


def stop_sidecar():
    """Gọi khi app thoát → tắt sidecar."""
    _Sidecar.stop()


# Giọng preset của VieNeu v3-Turbo (cố định theo model → hardcode để liệt kê
# tức thì, KHÔNG cần load model). Đồng bộ với tts.list_preset_voices().
_PRESET_VOICES = [
    ("Ngọc Lan — nữ, dịu dàng", "Ngọc Lan"),
    ("Mỹ Duyên — nữ, mượt mà", "Mỹ Duyên"),
    ("Trúc Ly — nữ, trẻ trung", "Trúc Ly"),
    ("Ngọc Linh — nữ, tươi sáng", "Ngọc Linh"),
    ("Gia Bảo — nam, mượt mà", "Gia Bảo"),
    ("Thái Sơn — nam, chắc khỏe", "Thái Sơn"),
    ("Đức Trí — nam, rõ ràng", "Đức Trí"),
    ("Xuân Vĩnh — nam, vui tươi", "Xuân Vĩnh"),
    ("Trọng Hữu — nam, uyên bác", "Trọng Hữu"),
    ("Bình An — nam, điềm đạm", "Bình An"),
]


# ── Quản lý giọng clone (local, data/vieneu_clones) ───────────────────────
def _slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").strip().lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s or "giong"


def list_clones() -> List[dict]:
    """Liệt kê giọng clone: [{voice_id, name, lang, ...}]."""
    out = []
    base = _inst.clones_dir()
    for d in sorted(base.iterdir()) if base.exists() else []:
        if not d.is_dir() or not (d / "ref.wav").exists():
            continue
        meta = {}
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            pass
        out.append({
            "voice_id": f"clone:{d.name}",
            "name": meta.get("name", d.name),
            "lang": meta.get("lang", "vi-VN"),
        })
    return out


def add_clone(name: str, audio_path: str, transcript: str = "",
              lang: str = "vi-VN", ffmpeg: str = "ffmpeg") -> str:
    """Thêm giọng clone từ file audio mẫu. Trả voice_id 'clone:<slug>'."""
    slug = _slug(name)
    d = _inst.clones_dir() / slug
    d.mkdir(parents=True, exist_ok=True)
    ref = d / "ref.wav"
    # Convert audio mẫu → wav 24kHz mono (chuẩn cho clone)
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", audio_path,
           "-ar", "24000", "-ac", "1", str(ref)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       creationflags=_SUBPROCESS_FLAGS)
    if r.returncode != 0 or not ref.exists():
        raise RuntimeError(f"Không xử lý được file mẫu: {r.stderr[:160]}")
    (d / "meta.json").write_text(json.dumps({
        "name": name, "lang": lang, "transcript": transcript,
    }, ensure_ascii=False), encoding="utf-8")
    if transcript:
        (d / "ref.txt").write_text(transcript, encoding="utf-8")
    return f"clone:{slug}"


def delete_clone(voice_id: str) -> bool:
    """Xoá 1 giọng clone."""
    import shutil
    slug = voice_id.split(":", 1)[1] if ":" in voice_id else voice_id
    d = _inst.clones_dir() / slug
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        return not d.exists()
    return False


# ── Engine ────────────────────────────────────────────────────────────────
class VieNeuTTSEngine(TTSEngine):
    """TTS local qua sidecar VieNeu. voice_id quy ước ở docstring module."""

    def __init__(self, voice_id: str = "", model: str = "",
                 ffmpeg: str = "ffmpeg", timeout: int = 300):
        self.voice_id = (voice_id or "").strip()
        # "" = dùng default package (v3-Turbo). KHÔNG lấy label marker (info-only).
        self.model = (model or "").strip()
        self.ffmpeg = ffmpeg
        self.timeout = int(timeout)
        self._tls = threading.local()

    def _resolve_voice(self) -> dict:
        """voice_id → payload {voice|ref_audio} cho sidecar."""
        vid = self.voice_id
        if vid.startswith("clone:"):
            slug = vid.split(":", 1)[1]
            ref = _inst.clones_dir() / slug / "ref.wav"
            if ref.exists():
                return {"ref_audio": str(ref)}
        elif vid.startswith("preset:"):
            return {"voice": vid.split(":", 1)[1]}
        return {}  # default voice

    def synthesize(self, text: str, output_path: str, **kwargs) -> bool:
        self._tls.sentence_timing = []  # VieNeu không trả word timing
        try:
            base = _Sidecar.ensure(self.model)
            payload = {"text": text}
            payload.update(self._resolve_voice())
            req = urllib.request.Request(
                f"{base}/synth",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    print(f"[VieNeu] synth HTTP {resp.status}")
                    return False
                wav_bytes = resp.read()
            if not wav_bytes:
                return False
            # wav tạm → ffmpeg convert sang output (mp3/wav theo pipeline)
            tmp_wav = Path(output_path).with_suffix(".vieneu.wav")
            tmp_wav.write_bytes(wav_bytes)
            cmd = [self.ffmpeg, "-y", "-loglevel", "error", "-i", str(tmp_wav),
                   str(output_path)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=_SUBPROCESS_FLAGS)
            try:
                tmp_wav.unlink()
            except OSError:
                pass
            return r.returncode == 0 and Path(output_path).exists()
        except urllib.error.HTTPError as e:
            try:
                print(f"[VieNeu] synth lỗi: {e.read()[:160]!r}")
            except Exception:
                print(f"[VieNeu] synth lỗi HTTP {e.code}")
            return False
        except Exception as e:
            print(f"[VieNeu] synth lỗi: {str(e)[:160]}")
            return False

    def list_voices(self, lang_filter: str = "") -> List[dict]:
        """Giọng mặc định + giọng clone local (không cần load model)."""
        voices = [{
            "name": "Giọng mặc định (VieNeu)", "voice_id": "default",
            "locale": "vi-VN", "gender": "",
        }]
        # 10 giọng preset sẵn có của VieNeu
        for label, name in _PRESET_VOICES:
            voices.append({
                "name": f"🎙 {label}", "voice_id": f"preset:{name}",
                "locale": "vi-VN", "gender": "",
            })
        for c in list_clones():
            voices.append({
                "name": f"👤 {c['name']} (clone)", "voice_id": c["voice_id"],
                "locale": c.get("lang", "vi-VN"), "gender": "",
            })
        return voices
