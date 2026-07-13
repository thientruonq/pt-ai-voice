"""
PT AI Voice — License & Activation Module
Xác thực License Key qua Google Apps Script + Google Sheets.

Key format:  PTAV-XXXX-XXXX-XXXX  (case-insensitive, normalize upper)
Storage:     %APPDATA%\\PT-AI-Voice\\license.dat  (Fernet encrypted, device-bound)
HMAC ns:     PTAIVoiceV1  (khớp docs/google_apps_script.js)

Ported từ Auto-YTB — thay app name / namespace để tách data + không conflict key.
"""

import base64
import hashlib
import hmac as _hmac
import json
import os
import platform
import socket
import threading as _threading
import time
import uuid
from pathlib import Path
from typing import Tuple

# Lazy import — cryptography là dep nặng (~20ms), defer đến lúc dùng
Fernet = None
InvalidToken = None
_crypto_lock = _threading.Lock()


def _ensure_crypto():
    global Fernet, InvalidToken
    if Fernet is None:
        with _crypto_lock:
            if Fernet is None:  # double-check sau khi acquire lock
                from cryptography.fernet import Fernet as _F, InvalidToken as _IT
                Fernet = _F
                InvalidToken = _IT


# ══════════════════════════════════════════════════════════════════════════════
# CẤU HÌNH — License API endpoint (paste URL Apps Script sau khi deploy)
# ══════════════════════════════════════════════════════════════════════════════
# Hướng dẫn deploy: docs/license-setup.md
# URL rỗng / chứa "YOUR_GOOGLE" → dev-mode (bypass, return "active", "Dev Mode")
LICENSE_API_URL = ""
# ══════════════════════════════════════════════════════════════════════════════

# Số ngày cho phép dùng offline nếu đã verify thành công lần trước
_OFFLINE_GRACE_DAYS = 7
_CACHE_EXPIRY_SECS = _OFFLINE_GRACE_DAYS * 24 * 3600

_APP_NAME = "PT-AI-Voice"


# ── Đường dẫn lưu trữ ────────────────────────────────────────────────────────

def _config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    d = base / _APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _license_file() -> Path:
    return _config_dir() / "license.dat"


def _stable_id_file() -> Path:
    return _config_dir() / "stable_id.txt"


# ── Device ID — định danh thiết bị duy nhất ──────────────────────────────────

def _get_device_id() -> str:
    """Tạo ID duy nhất cho thiết bị dựa trên phần cứng (hostname + MAC).

    NOTE: volatile trên macOS — uuid.getnode() có thể trả MAC random khác
    nhau giữa các session (Wi-Fi randomization). Dùng cho server-side
    signing (server tolerant). Cho LOCAL encrypt → dùng _get_stable_id().
    """
    raw = f"{socket.gethostname()}|{uuid.getnode()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _get_stable_id() -> str:
    """ID stable PERSISTED qua file → không bị macOS MAC randomization phá.

    Lần đầu: lấy seed = current device_id, lưu vào stable_id.txt. Lần sau:
    đọc file → luôn cùng giá trị → Fernet decrypt thành công xuyên session.
    """
    f = _stable_id_file()
    try:
        if f.exists():
            sid = f.read_text(encoding="utf-8").strip()
            if sid:
                return sid
    except Exception:
        pass
    sid = _get_device_id()
    try:
        f.write_text(sid, encoding="utf-8")
    except Exception:
        pass
    return sid


def _get_hostname() -> str:
    return socket.gethostname()


# ── HMAC request signing ──────────────────────────────────────────────────────

def _get_signing_key() -> bytes:
    """Reconstruct signing key từ parts để chống string-search trong binary.

    prefix "PTAIVoiceLicSign" + first 16 bytes SHA-256("PTAIVoiceV1")
    Namespace khác Auto-YTB → key 2 app không bao giờ collide dù dùng chung
    Sheet vô tình.
    """
    parts = [b'\x50\x54\x41\x49', b'\x56\x6f\x69', b'\x63\x65',
             b'\x4c\x69\x63', b'\x53\x69\x67\x6e']
    return b''.join(parts) + hashlib.sha256(b'PTAIVoiceV1').digest()[:16]


def _sign_request(key: str, device_id: str, timestamp: int) -> str:
    """Tạo HMAC-SHA256 signature. message = key + device_id + str(timestamp)"""
    message = (key + device_id + str(timestamp)).encode("utf-8")
    return _hmac.new(_get_signing_key(), message, hashlib.sha256).hexdigest()


# ── Fernet encryption (device-bound) ─────────────────────────────────────────

def _derive_key(device_id: str) -> bytes:
    """Derive 32-byte Fernet key từ device_id qua PBKDF2-HMAC-SHA256.
    Key bind vào máy → license.dat KHÔNG portable (copy máy khác vô dụng).
    """
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        device_id.encode("utf-8"),
        salt=b"PTAIVoiceLicV1",
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(raw)


def _encrypt_license(data: str, device_id: str) -> str:
    _ensure_crypto()
    f = Fernet(_derive_key(device_id))
    return f.encrypt(data.encode("utf-8")).decode("ascii")


def _decrypt_license(token: str, device_id: str) -> str:
    _ensure_crypto()
    f = Fernet(_derive_key(device_id))
    return f.decrypt(token.encode("ascii")).decode("utf-8")


# ── Đọc / Ghi cache ──────────────────────────────────────────────────────────

def _load_cache_meta() -> dict:
    """Load metadata (status, name, last_check) mà KHÔNG decrypt key.
    Dùng cho check_license_fast() → tránh cost Fernet import."""
    f = _license_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {
            "status": data.get("status", ""),
            "name": data.get("name", ""),
            "last_check": data.get("last_check", 0.0),
            "has_key": bool(data.get("key", "")),
        }
    except Exception:
        return {}


def _load_cache() -> dict:
    """Load license cache từ disk. Field 'key' là Fernet-encrypted.

    Decrypt order:
      1. stable_id (current — survives MAC randomization)
      2. device_id (legacy) → migrate lên stable_id
      3. base64 (very old) → migrate lên Fernet
    """
    f = _license_file()
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}

    raw_key = data.get("key", "")
    if not raw_key:
        return data

    try:
        _ensure_crypto()
        data["key"] = _decrypt_license(raw_key, _get_stable_id())
        return data
    except Exception:
        pass

    try:
        _ensure_crypto()
        plaintext_key = _decrypt_license(raw_key, _get_device_id())
        data["key"] = plaintext_key
        _save_cache(plaintext_key, data.get("status", ""), data.get("name", ""))
        return data
    except Exception:
        pass

    try:
        plaintext_key = base64.b64decode(raw_key.encode("ascii")).decode("utf-8")
        data["key"] = plaintext_key
        _save_cache(plaintext_key, data.get("status", ""), data.get("name", ""))
        return data
    except Exception:
        return {}


def _save_cache(key: str, status: str, name: str = ""):
    data = {
        "key": _encrypt_license(key.strip().upper(), _get_stable_id()),
        "status": status,
        "name": name,
        "last_check": time.time(),
    }
    _license_file().write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def get_saved_key() -> str:
    """Trả về key đã lưu local, hoặc '' nếu chưa có."""
    cache = _load_cache()
    return cache.get("key", "")


def clear_license():
    """Xóa license local (dùng khi reset / đăng xuất)."""
    f = _license_file()
    if f.exists():
        f.unlink()


# ── Verify online ─────────────────────────────────────────────────────────────

def verify_online(key: str, timeout: int = 10) -> Tuple[str, str]:
    """Gọi Google Apps Script kiểm tra key + đăng ký thiết bị.

    Trả về (status, name):
      "active"      → Hợp lệ
      "revoked"     → Đã bị thu hồi
      "not_found"   → Không tồn tại
      "max_devices" → Vượt giới hạn thiết bị
      "error"       → Lỗi mạng / server
    """
    import urllib.request
    import urllib.error

    if not LICENSE_API_URL or "YOUR_GOOGLE" in LICENSE_API_URL:
        # Chưa cấu hình API → dev-mode bypass
        return ("active", "Dev Mode")

    try:
        import ssl

        _key = key.strip().upper()
        _device_id = _get_device_id()
        _ts = int(time.time())
        post_data = json.dumps({
            "key": _key,
            "device_id": _device_id,
            "hostname": _get_hostname(),
            "timestamp": _ts,
            "signature": _sign_request(_key, _device_id, _ts),
        }).encode("utf-8")
        req = urllib.request.Request(
            LICENSE_API_URL,
            data=post_data,
            headers={
                "User-Agent": "PT-AI-Voice-License/1.0",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        resp_obj = urllib.request.urlopen(req, timeout=timeout, context=ctx)

        with resp_obj as resp:
            data = json.loads(resp.read().decode("utf-8"))

        status = str(data.get("status", "not_found")).lower()
        name = str(data.get("name", ""))
        return (status, name)
    except Exception as e:
        print(f"[License] Verify failed: {type(e).__name__}: {e}")
        return ("error", "")


# ── Fast check (cache-only, no network — gọi từ main.py lúc khởi động) ───────

def check_license_fast() -> Tuple[str, str]:
    """Kiểm tra license chỉ bằng cache local — KHÔNG mạng, KHÔNG decrypt key.
    Trả về ngay (<10ms). Online verify chạy background sau.

    Trả về (status, name):
      "active"   → Cache active + còn hạn → cho vào app ngay
      "no_key"   → Chưa kích hoạt lần nào
      "expired"  → Cache hết hạn (cần online verify)
    """
    meta = _load_cache_meta()
    if not meta.get("has_key"):
        return ("no_key", "")

    cached_status = meta.get("status", "")
    last_check = meta.get("last_check", 0.0)
    remaining = _CACHE_EXPIRY_SECS - (time.time() - last_check)

    if cached_status == "active" and remaining > 0:
        return ("active", meta.get("name", ""))

    return ("expired", meta.get("name", ""))


# ── Full check (blocking — gọi khi cần online verify) ────────────────────────

def check_license() -> Tuple[str, str]:
    """Kiểm tra license đầy đủ:
      1. Đọc key đã lưu local
      2. Verify online
      3. Nếu offline → dùng cache (grace period 7 ngày)

    Trả về (status, name):
      "active"          → OK, cho vào app
      "active_offline"  → Đang offline nhưng cache còn hạn
      "revoked"         → Bị thu hồi
      "not_found"       → Key không tồn tại
      "no_key"          → Chưa kích hoạt lần nào
      "offline"         → Mất mạng VÀ cache hết hạn
    """
    key = get_saved_key()
    if not key:
        return ("no_key", "")

    status, name = verify_online(key)

    if status == "error":
        cache = _load_cache()
        cached_status = cache.get("status", "")
        last_check = cache.get("last_check", 0.0)
        remaining = _CACHE_EXPIRY_SECS - (time.time() - last_check)

        if cached_status == "active" and remaining > 0:
            return ("active_offline", cache.get("name", ""))

        return ("offline", "")

    _save_cache(key, status, name)
    return (status, name)


# ── Kích hoạt key mới ────────────────────────────────────────────────────────

def activate(key: str) -> Tuple[str, str]:
    """Kích hoạt key mới. Lưu vào local nếu active. Trả (status, name)."""
    key = key.strip().upper()
    if not key:
        return ("not_found", "")

    status, name = verify_online(key)
    if status == "active":
        _save_cache(key, status, name)
    return (status, name)
