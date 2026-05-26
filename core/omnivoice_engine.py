"""
OmniVoice Colab Engine — HTTP client cho server Voice Library trên Google Colab.

Server (tools/omnivoice-colab-server.ipynb ở Auto-YTB) giữ 2 thư mục:
  - presets/ — giọng mẫu (read-only)
  - clones/  — giọng user upload qua Auto-YTB (persist trên Drive)

Client gửi (voice_kind, voice_id) — server tra library → synthesize.

Multi-URL pool: user có thể nhập nhiều URL public tunnel của server
(newline-separated) — hỗ trợ ngrok, Cloudflare Tunnel (trycloudflare.com),
LocalTunnel, hoặc bất kỳ HTTP(S) endpoint nào. Pool tự xoay vòng khi 1
URL fail (Colab disconnect / tunnel expire). Pool state persist xuống
disk → recover qua app restart.

License: Apache 2.0 — commercial OK.
"""
import json
import os
import re as _re
import ssl as _ssl
import threading as _threading
import time as _time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional, Union

from .tts_engine import TTSEngine

BASE_DIR = Path(__file__).parent.parent
_DATA_DIR = BASE_DIR / "data"


# ── Helpers ──────────────────────────────────────────────────────────────────

def parse_omnivoice_endpoints(text: str) -> List[str]:
    """Parse newline/comma/semicolon-separated URLs → cleaned list.

    - Strip whitespace, lower scheme
    - Chỉ giữ http:// hoặc https://
    - Strip trailing slash, dedupe giữ thứ tự
    """
    if not text:
        return []
    raw = str(text).replace(",", "\n").replace(";", "\n").splitlines()
    seen: dict = {}
    for line in raw:
        u = line.strip()
        if not u:
            continue
        if not u.lower().startswith(("http://", "https://")):
            continue
        u = u.rstrip("/")
        if u not in seen:
            seen[u] = True
    return list(seen.keys())


def _normalize_allcaps_vi(text: str) -> str:
    """Lowercase ALL-CAPS words tiếng Việt để tránh model đánh vần.

    "KHÔNG" → "Không" (có dấu VN, ≥2 ký tự → emphasis)
    "USA"   → "USA"   (3 ký tự ASCII trong text VI vẫn coi acronym — không đổi)
    "HOA SEN" → "Hoa Sen" (≥3 ký tự ASCII trong context VI → emphasis)
    """
    _VN_ACCENTED = (
        "ĂÂÊÔƠƯĐÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆ"
        "ÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
    )

    def _fix(m):
        w = m.group(0)
        if len(w) < 2 or not w.isupper():
            return w
        if any(c in _VN_ACCENTED for c in w):
            return w.capitalize()
        # VI voice + ≥3 ký tự ASCII all-caps → emphasis (rare acronym in VI script)
        if len(w) >= 3:
            return w.capitalize()
        return w

    return _re.sub(r"[^\W\d_]+", _fix, text, flags=_re.UNICODE)


def _build_ssl_context():
    """SSL context dùng certifi bundle (fix HTTPS tunnel fail trên Mac)."""
    try:
        import certifi
        return _ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return _ssl.create_default_context()


_SSL_CTX = _build_ssl_context()


# ── URL Pool ────────────────────────────────────────────────────────────────

class OmniVoiceUrlPool:
    """Pool URL OmniVoice với STICKY preference + cooldown + persist.

    State machine per URL: alive ↔ failed (cooldown N giây → auto-revert alive).

    Acquisition strategy: ưu tiên URL được dùng thành công gần nhất (sticky)
    để giữ voice cache nóng trên server. Fallback round-robin khi sticky fail.
    """

    _COOLDOWN_S = 30.0

    def __init__(self, urls: List[str], persist: bool = True):
        self._urls: List[str] = list(urls)
        self._lock = _threading.Lock()
        self._idx = 0
        self._last_success: str = ""
        self._failed: dict = {}
        self._last_logged_url: str = ""
        self._persist = persist
        if persist:
            self._load()

    def __len__(self) -> int:
        return len(self._urls)

    @property
    def urls(self) -> List[str]:
        return list(self._urls)

    def _is_alive_now(self, url: str) -> bool:
        ts = self._failed.get(url, 0)
        if ts <= 0:
            return True
        if _time.time() - ts >= self._COOLDOWN_S:
            self._failed.pop(url, None)
            return True
        return False

    @property
    def alive_count(self) -> int:
        with self._lock:
            return sum(1 for u in self._urls if self._is_alive_now(u))

    def acquire(self) -> str:
        """Trả URL alive — ưu tiên sticky rồi round-robin."""
        with self._lock:
            if not self._urls:
                raise RuntimeError("OmniVoice pool rỗng — chưa nhập Server URL nào")
            n = len(self._urls)
            if self._last_success and self._last_success in self._urls:
                if self._is_alive_now(self._last_success):
                    return self._last_success
            for _ in range(n):
                url = self._urls[self._idx % n]
                self._idx = (self._idx + 1) % n
                if self._is_alive_now(url):
                    return url
            # Tất cả failed → pick URL có failed_at cũ nhất
            return min(self._urls, key=lambda u: self._failed.get(u, 0))

    def mark_failed(self, url: str, reason: str = "") -> None:
        if not url:
            return
        with self._lock:
            _was_failed = url in self._failed
            self._failed[url] = _time.time()
            _short = self._short_url(url)
            _sticky_cleared = (self._last_success == url)
            if _sticky_cleared:
                self._last_success = ""
            if not _was_failed:
                print(f"[OmniVoicePool] ⛔ Mark failed: {_short} ({reason[:60]}) — "
                      f"cooldown {int(self._COOLDOWN_S)}s"
                      + (" | 🔓 Sticky cleared" if _sticky_cleared else ""))
        if self._persist:
            self._save_async()

    def mark_recovered(self, url: str) -> None:
        """Mark URL alive + update sticky preference."""
        if not url:
            return
        with self._lock:
            _was_failed = url in self._failed
            _sticky_changed = (self._last_success != url)
            _short = self._short_url(url)
            if _was_failed:
                self._failed.pop(url, None)
                print(f"[OmniVoicePool] ✓ URL recovered: {_short}")
            if _sticky_changed:
                self._last_success = url
        if (_was_failed or _sticky_changed) and self._persist:
            self._save_async()

    @staticmethod
    def _short_url(url: str) -> str:
        """Lấy subdomain đầu để hiển thị log gọn.
        VD: 'https://clock-halt.ngrok-free.dev' → 'clock-halt'
            'https://norm-exhaust.trycloudflare.com' → 'norm-exhaust'
        """
        if not url:
            return "?"
        s = str(url).replace("https://", "").replace("http://", "")
        if "." in s:
            return s.split(".")[0]
        return s[:40]

    def report(self) -> str:
        """Format pool state cho log."""
        with self._lock:
            alive = sum(1 for u in self._urls if self._is_alive_now(u))
            total = len(self._urls)
            if total == 0:
                return "pool empty"
            active = self._last_success if (
                self._last_success and self._last_success in self._urls
                and self._is_alive_now(self._last_success)
            ) else ""
            if not active:
                for i in range(total):
                    u = self._urls[(self._idx + i) % total]
                    if self._is_alive_now(u):
                        active = u
                        break
            active_short = self._short_url(active) if active else "?"
            sticky_marker = "🔒 " if (self._last_success and active == self._last_success) else ""
            if alive == total:
                return f"{alive}/{total} alive | active: {sticky_marker}{active_short}"
            failed_urls = [u for u in self._urls if not self._is_alive_now(u)]
            failed_short = [self._short_url(u) for u in failed_urls[:3]]
            return (f"{alive}/{total} alive | active: {sticky_marker}{active_short}"
                    f" | failed: {', '.join(failed_short)}")

    # ── Persistence ────────────────────────────────────────────────────────

    @staticmethod
    def _state_path() -> Path:
        return _DATA_DIR / "omnivoice_pool.json"

    def _load(self) -> None:
        p = self._state_path()
        if not p.exists():
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            failed = data.get("failed_urls", {}) or {}
            _now = _time.time()
            cleaned = {}
            for url, info in failed.items():
                try:
                    ts = float(info.get("failed_at", 0)) if isinstance(info, dict) else float(info)
                except (ValueError, TypeError):
                    continue
                if url in self._urls and (_now - ts) < self._COOLDOWN_S:
                    cleaned[url] = ts
            self._failed = cleaned
            _last = data.get("last_success", "") or ""
            if _last and _last in self._urls and _last not in self._failed:
                self._last_success = _last
                print(f"[OmniVoicePool] Restored sticky URL: {_last}")
        except Exception as _e:
            print(f"[OmniVoicePool] Load state fail (non-fatal): {_e}")

    def _save_async(self) -> None:
        try:
            _threading.Thread(target=self._save, daemon=True).start()
        except Exception:
            pass

    def _save(self) -> None:
        p = self._state_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = {
                    "failed_urls": {
                        url: {"failed_at": ts}
                        for url, ts in self._failed.items()
                    },
                    "last_success": self._last_success,
                }
            tmp = p.with_suffix(f".{os.getpid()}.{_threading.get_ident()}.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, p)
        except Exception as _e:
            print(f"[OmniVoicePool] Save state fail (non-fatal): {_e}")


# ── Engine ──────────────────────────────────────────────────────────────────

class OmniVoiceColabEngine(TTSEngine):
    """TTS engine dùng OmniVoice Voice Library server trên Colab.

    Server expose qua public tunnel: ngrok, Cloudflare Tunnel
    (trycloudflare.com), LocalTunnel, ... — client treat mọi URL đồng nhất.

    Args:
        endpoint: URL public tunnel (string newline/comma-separated, hoặc list[str])
        voice_kind: "preset" | "clone"
        voice_id: ID giọng trong library (slug folder)
        timeout: HTTP timeout giây
    """

    # Header `ngrok-skip-browser-warning` chỉ ngrok hiểu — Cloudflare/LocalTunnel
    # bỏ qua nên gửi mọi request vẫn an toàn cross-provider.
    _SERVER_HEADERS = {"ngrok-skip-browser-warning": "true"}

    def __init__(
        self,
        endpoint: Union[str, List[str]] = "",
        voice_kind: str = "preset",
        voice_id: str = "",
        timeout: int = 180,
    ):
        if isinstance(endpoint, list):
            _urls = [str(u).rstrip("/") for u in endpoint if u]
            _urls = [u for u in _urls if u.lower().startswith(("http://", "https://"))]
        else:
            _urls = parse_omnivoice_endpoints(str(endpoint or ""))
        self._pool = OmniVoiceUrlPool(_urls) if _urls else None
        self.endpoint = _urls[0] if _urls else ""
        self.voice_kind = voice_kind if voice_kind in ("preset", "clone") else "preset"
        self.voice_id = (voice_id or "").strip()
        self.timeout = int(timeout)

    def _current_endpoint(self) -> str:
        if self._pool and len(self._pool) > 0:
            return self._pool.acquire()
        return self.endpoint

    @staticmethod
    def _is_url_failure(exc: Exception) -> bool:
        """True nếu lỗi do URL/server (cần mark_failed + rotate)."""
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code >= 500 or exc.code == 404
        if isinstance(exc, urllib.error.URLError):
            return True
        msg = str(exc).lower()
        return any(kw in msg for kw in (
            "timeout", "timed out", "getaddrinfo", "connection refused",
            "connection reset", "connection aborted", "name or service",
        ))

    @staticmethod
    def _encode_multipart(fields: dict) -> tuple:
        boundary = "----OmniVoiceBoundary" + str(_threading.get_ident())
        lines = []
        for name, value in fields.items():
            lines.append(f"--{boundary}".encode())
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(str(value).encode("utf-8"))
        lines.append(f"--{boundary}--".encode())
        lines.append(b"")
        body = b"\r\n".join(lines)
        return body, f"multipart/form-data; boundary={boundary}"

    # ── TTSEngine interface ──────────────────────────────────────────────

    def synthesize(self, text: str, output_path: str, **kwargs) -> bool:
        if not text or not text.strip():
            return False
        if not self._pool or len(self._pool) == 0:
            print("[OmniVoice] Thiếu Server URL — setup Colab notebook + paste URL tunnel (ngrok/Cloudflare)")
            return False
        if not self.voice_id:
            print("[OmniVoice] Thiếu voice_id — chọn giọng trong Settings")
            return False

        # Normalize ALL-CAPS VI + collapse punctuation
        _norm = _normalize_allcaps_vi(text.strip())
        _norm = _re.sub(r'!{2,}', '!', _norm)
        _norm = _re.sub(r'\?{2,}', '?', _norm)
        _norm = _re.sub(r'\.{4,}', '...', _norm)
        _norm = _re.sub(r'\s+([,.!?;:])', r'\1', _norm)
        _norm = _re.sub(r'\s{2,}', ' ', _norm).strip()

        _MAX_RETRIES = 2  # tổng 3 attempts để rotate qua pool
        _current_url = ""
        for _attempt in range(_MAX_RETRIES + 1):
            try:
                _current_url = self._current_endpoint()
                if (self._pool and len(self._pool) > 1
                        and _current_url != self._pool._last_logged_url):
                    _short = self._pool._short_url(_current_url)
                    _is_sticky = (self._pool._last_success == _current_url)
                    _marker = "🔒 sticky" if _is_sticky else "🔄 round-robin"
                    print(f"[OmniVoice] → Using {_short} ({_marker})")
                    self._pool._last_logged_url = _current_url

                fields = {
                    "text": _norm,
                    "voice_kind": self.voice_kind,
                    "voice_id": self.voice_id,
                    "apply_watermark": False,
                }
                body, ctype = self._encode_multipart(fields)
                req = urllib.request.Request(
                    f"{_current_url}/synthesize",
                    data=body,
                    headers={"Content-Type": ctype, **self._SERVER_HEADERS},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL_CTX) as resp:
                    audio_bytes = resp.read()
                if not audio_bytes or len(audio_bytes) < 100:
                    if _attempt < _MAX_RETRIES:
                        print(f"[OmniVoice] Audio rỗng, retry {_attempt+1}/{_MAX_RETRIES}")
                        continue
                    return False
                Path(output_path).write_bytes(audio_bytes)
                if self._pool and _current_url:
                    self._pool.mark_recovered(_current_url)
                return True

            except urllib.error.HTTPError as e:
                _detail = ""
                try:
                    _detail = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                _is_server_fail = (e.code >= 500 or e.code == 404)
                if _is_server_fail and self._pool and _current_url:
                    self._pool.mark_failed(_current_url, f"HTTP {e.code}")
                if e.code == 404:
                    print(f"[OmniVoice] ❌ HTTP 404 — URL tunnel HẾT HẠN hoặc sai endpoint: {_current_url}")
                    print(f"[OmniVoice]    ➜ Vào Colab notebook chạy lại, paste URL tunnel mới.")
                elif e.code == 502 and "ERR_NGROK_8012" in _detail:
                    print(f"[OmniVoice] ❌ HTTP 502 — Tunnel OK nhưng Colab ĐÃ TẮT: {_current_url}")
                    print(f"[OmniVoice]    ➜ Restart Colab notebook (Runtime → Restart).")
                elif e.code in (502, 503, 504):
                    print(f"[OmniVoice] ❌ HTTP {e.code} — Server quá tải: {_current_url}")
                elif e.code >= 500:
                    print(f"[OmniVoice] ❌ HTTP {e.code}: {(_detail or e.reason)[:120]}")
                else:
                    print(f"[OmniVoice] ❌ HTTP {e.code}: {(_detail or e.reason)[:120]}")
                if _is_server_fail and self._pool and self._pool.alive_count > 0 and _attempt < _MAX_RETRIES:
                    print(f"[OmniVoice] 🔄 Rotate URL khác (pool: {self._pool.report()})")
                    continue
                return False
            except urllib.error.URLError as e:
                if self._pool and _current_url:
                    self._pool.mark_failed(_current_url, str(e)[:60])
                print(f"[OmniVoice] ❌ KHÔNG KẾT NỐI ĐƯỢC: {_current_url}")
                print(f"[OmniVoice]    ➜ {str(e.reason)[:120] if hasattr(e, 'reason') else str(e)[:120]}")
                if self._pool and self._pool.alive_count > 0 and _attempt < _MAX_RETRIES:
                    print(f"[OmniVoice] 🔄 Rotate URL khác (pool: {self._pool.report()})")
                    continue
                return False
            except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
                _winerr = getattr(e, 'winerror', None)
                if self._pool and _current_url:
                    self._pool.mark_failed(_current_url, f"ConnReset (WinError {_winerr})")
                print(f"[OmniVoice] ❌ KẾT NỐI BỊ NGẮT: {_current_url} (WinError {_winerr})")
                if self._pool and self._pool.alive_count > 0 and _attempt < _MAX_RETRIES:
                    continue
                return False
            except Exception as e:
                print(f"[OmniVoice] ❌ Lỗi ({type(e).__name__}): {str(e)[:120]}")
                if self._pool and self._pool.alive_count > 1 and _attempt < _MAX_RETRIES:
                    if _current_url:
                        self._pool.mark_failed(_current_url, str(e)[:60])
                    continue
                return False
        return False

    def list_voices(self, lang_filter: str = "", kind: str = "all") -> List[dict]:
        """Trả list giọng (aggregate từ TẤT CẢ URL trong pool, dedup theo id).

        Mỗi item: {id, name, gender, locale, _kind: "preset"|"clone", ...}
        """
        if not self._pool or len(self._pool) == 0:
            return []
        qs = urllib.parse.urlencode({"lang": lang_filter or "", "kind": kind})
        _seen_ids: set = set()
        _aggregated: List[dict] = []
        _success_count = 0
        _last_err = ""

        for _url in list(self._pool.urls):
            try:
                req = urllib.request.Request(
                    f"{_url}/voices?{qs}",
                    headers=self._SERVER_HEADERS,
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
                    _text = resp.read().decode("utf-8", errors="replace")
                try:
                    data = json.loads(_text)
                except json.JSONDecodeError as _je:
                    _last_err = f"{_url}: response không phải JSON"
                    print(f"[OmniVoice list_voices] {_last_err} ({_je})")
                    self._pool.mark_failed(_url, "JSON parse fail")
                    continue
                if not isinstance(data, dict):
                    _last_err = f"{_url}: response sai schema"
                    self._pool.mark_failed(_url, "schema fail")
                    continue
                _new_p = _new_c = 0
                for v in data.get("presets", []):
                    _vid = v.get("id")
                    if _vid and _vid not in _seen_ids:
                        v["_kind"] = "preset"
                        _aggregated.append(v)
                        _seen_ids.add(_vid)
                        _new_p += 1
                for v in data.get("clones", []):
                    _vid = v.get("id")
                    if _vid and _vid not in _seen_ids:
                        v["_kind"] = "clone"
                        _aggregated.append(v)
                        _seen_ids.add(_vid)
                        _new_c += 1
                _tp = len(data.get("presets", []))
                _tc = len(data.get("clones", []))
                if (_tp + _tc) > 0:
                    print(f"[OmniVoice list_voices] {self._pool._short_url(_url)} "
                          f"→ {_tp}p ({_new_p} new), {_tc}c ({_new_c} new)")
                self._pool.mark_recovered(_url)
                _success_count += 1
            except Exception as e:
                _last_err = f"{_url}: {type(e).__name__}: {str(e)[:80]}"
                print(f"[OmniVoice list_voices] {_last_err}")
                if self._is_url_failure(e):
                    self._pool.mark_failed(_url, str(e)[:80])

        if _success_count > 0:
            _n_p = sum(1 for v in _aggregated if v.get("_kind") == "preset")
            _n_c = sum(1 for v in _aggregated if v.get("_kind") == "clone")
            print(f"[OmniVoice list_voices] ✓ Aggregate từ {_success_count}/"
                  f"{len(self._pool)} URLs → {_n_p} presets, {_n_c} clones")
            return _aggregated
        print(f"[OmniVoice] ❌ Không tải được danh sách giọng: {_last_err}")
        return []

    def check_server(self) -> tuple:
        """Trả (ok, detail). Thử từng URL tới khi 1 cái phản hồi."""
        if not self._pool or len(self._pool) == 0:
            return False, "Chưa nhập Server URL"
        _last_err = "không URL nào phản hồi"
        for _i in range(len(self._pool)):
            _url = self._pool.acquire()
            print(f"[OmniVoice Test] Ping {_url}/health timeout=15s")
            try:
                req = urllib.request.Request(
                    f"{_url}/health",
                    headers=self._SERVER_HEADERS,
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "ok":
                    info = (f"{data.get('device', '?')} • "
                            f"{data.get('presets', 0)} presets, "
                            f"{data.get('clones', 0)} clones")
                    self._pool.mark_recovered(_url)
                    if len(self._pool) > 1:
                        info = f"{info} • {self._pool.report()}"
                    return True, info
                _last_err = f"{_url}: server trả dữ liệu lạ"
            except urllib.error.HTTPError as e:
                _body = ""
                try:
                    _body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                if e.code == 502 and "ERR_NGROK_8012" in _body:
                    _last_err = f"{_url}: Tunnel OK nhưng Colab tắt"
                elif e.code == 404:
                    _last_err = f"{_url}: URL tunnel hết hạn hoặc sai endpoint (404)"
                else:
                    _last_err = f"{_url}: HTTP {e.code}"
                if self._is_url_failure(e):
                    self._pool.mark_failed(_url, _last_err)
                    continue
                return False, _last_err
            except urllib.error.URLError as e:
                _last_err = f"{_url}: {str(e.reason)[:80]}"
                self._pool.mark_failed(_url, _last_err)
                continue
            except Exception as e:
                _last_err = f"{_url}: {type(e).__name__}: {str(e)[:80]}"
                if self._is_url_failure(e):
                    self._pool.mark_failed(_url, _last_err)
                    continue
                return False, _last_err
        return False, _last_err
