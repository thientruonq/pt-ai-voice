"""
Config Manager — Quản lý cấu hình ứng dụng (cross-platform)
"""
import json
import base64
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).parent.parent

DEFAULT_CONFIG: dict = {
    "tts_engine": "edge",          # "edge" | "google" | "omnivoice"
    "voice_id": "vi-VN-HoaiMyNeural",
    "speed": "+0%",                 # Edge TTS rate: "-50%" → "+100%"
    "volume": "+0%",                # Edge TTS volume
    "pitch": "+0Hz",                # Edge TTS pitch
    "output_format": "mp3",        # mp3 | wav
    "output_dir": "",
    "theme": "dark",               # dark | light | system
    # OmniVoice Colab credentials (tuỳ chọn) — Voice Library server trên Colab
    "omnivoice_credentials": {
        "endpoint": "",           # URL public tunnel server (ngrok / Cloudflare / khác — mỗi dòng 1 URL)
        "voice_kind": "preset",   # "preset" | "clone"
    },
    # Google Cloud TTS credentials (tuỳ chọn)
    "google_credentials": {
        "type": "service_account",
        "project_id": "",
        "private_key_id": "",
        "private_key": "",
        "client_email": "",
        "client_id": "",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "",
        "universe_domain": "googleapis.com",
    },
    "advanced": {
        "silence_between_segments": True,
        "silence_duration_ms": 300,    # Khoảng lặng giữa các đoạn (ms)
        "use_srt_timing": True,         # Căn timing theo SRT
        "trim_silence": True,
        "remove_special_chars": True,
        "max_chars_per_segment": 500,
        "max_workers": 5,               # Luồng song song
        "ffmpeg_path": "",              # Để trống = tự tìm trong PATH
    },
}


class ConfigManager:
    """Singleton config manager — đọc/ghi file JSON an toàn."""

    _instance: Optional["ConfigManager"] = None

    def __new__(cls, config_path: str = "voice_config.json"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str = "voice_config.json"):
        if self._initialized:
            return
        self._initialized = True
        self.config_path = BASE_DIR / config_path
        self._data: dict = self._deep_copy(DEFAULT_CONFIG)
        self.load()

    # ── I/O ──────────────────────────────────────────────────────────────────

    def load(self) -> None:
        if not self.config_path.exists():
            return
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._deep_merge(self._data, raw)
            # Auto-fix: reset output_dir nếu đường dẫn không tồn tại (VD: path Windows trên Mac)
            self._fix_output_dir()
        except Exception as e:
            print(f"[Config] Load lỗi: {e}")

    def save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            print(f"[Config] Save lỗi: {e}")

    # ── Getters / Setters ────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_adv(self, key: str, default: Any = None) -> Any:
        return self._data.get("advanced", {}).get(key, default)

    def set_adv(self, key: str, value: Any) -> None:
        self._data.setdefault("advanced", {})[key] = value

    def get_google_creds(self) -> Optional[dict]:
        creds = self._data.get("google_credentials", {})
        if creds.get("private_key") and creds.get("client_email"):
            return dict(creds)
        return None

    def set_google_creds(self, creds: dict) -> None:
        self._data["google_credentials"] = creds

    def get_omnivoice_creds(self) -> Optional[dict]:
        creds = self._data.get("omnivoice_credentials", {})
        if creds.get("endpoint"):
            return dict(creds)
        return None

    def set_omnivoice_creds(self, endpoint: str, voice_kind: str = "preset") -> None:
        self._data.setdefault("omnivoice_credentials", {})["endpoint"] = endpoint
        self._data["omnivoice_credentials"]["voice_kind"] = voice_kind if voice_kind in ("preset", "clone") else "preset"

    # ── Password helpers ────────────────────────────────────────────────────

    @staticmethod
    def encode(text: str) -> str:
        return base64.b64encode(text.encode()).decode()

    @staticmethod
    def decode(encoded: str) -> str:
        try:
            return base64.b64decode(encoded.encode()).decode()
        except Exception:
            return encoded

    # ── Path fixers ────────────────────────────────────────────────────────

    def _fix_output_dir(self) -> None:
        """Reset output_dir nếu đường dẫn không hợp lệ trên máy hiện tại."""
        import os, sys
        out_dir = self._data.get("output_dir", "")
        if out_dir and not Path(out_dir).is_dir():
            # Đường dẫn không tồn tại → dùng Downloads của user hiện tại
            if sys.platform == "win32":
                default = os.path.join(
                    os.environ.get("USERPROFILE", str(Path.home())), "Downloads"
                )
            else:
                default = str(Path.home() / "Downloads")
            self._data["output_dir"] = default
            print(f"[Config] output_dir không hợp lệ → reset về: {default}")
            self.save()

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _deep_copy(d: dict) -> dict:
        import copy
        return copy.deepcopy(d)

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                ConfigManager._deep_merge(base[k], v)
            else:
                base[k] = v
