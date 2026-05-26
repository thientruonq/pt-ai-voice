"""
TTS Engine — Hỗ trợ Edge TTS (miễn phí), Google Cloud TTS và OmniVoice (Colab)
Cross-platform: Windows & macOS
"""
import asyncio
import os
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, List, Optional

from .srt_parser import Segment


# ── Base ──────────────────────────────────────────────────────────────────────

class TTSEngine(ABC):
    """Interface chung cho tất cả TTS engines"""

    @abstractmethod
    def synthesize(self, text: str, output_path: str, **kwargs) -> bool:
        """Chuyển text → file audio. Trả về True nếu thành công."""
        ...

    @abstractmethod
    def list_voices(self, lang_filter: str = "") -> List[dict]:
        """Trả về danh sách giọng đọc [{"name": ..., "gender": ..., "locale": ...}]"""
        ...

    def synthesize_segments(
        self,
        segments: List[Segment],
        output_dir: str,
        prefix: str = "seg",
        max_workers: int = 5,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        segment_cb: Optional[Callable[["Segment", bool], None]] = None,
        retry_cb: Optional[Callable[["Segment", int, int], None]] = None,
        rate_limit: float = 1.0,
        max_retries: int = 10,
        stop_event=None,  # threading.Event — nếu set thì bỏ qua các đoạn chưa xử lý
    ) -> List[Segment]:
        """
        Tổng hợp nhiều đoạn song song với tự động thử lại khi thất bại.
        - segment_cb(seg, success): gọi ngay khi mỗi đoạn hoàn thành
        - retry_cb(seg, attempt, max_retries): gọi trước mỗi lần thử lại
        """
        import concurrent.futures
        import threading as _threading

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        total = len(segments)
        _lock = _threading.Lock()
        done_count = [0]  # dùng list để tránh race condition với nonlocal

        def _do(seg: Segment) -> tuple:
            """Chạy trong worker thread — trả về (seg, success) ngay khi xong."""
            # Nếu stop_event được set thì bỏ qua đoạn này
            if stop_event and stop_event.is_set():
                seg.audio_path = ""
                return seg, False
            if prefix:
                filename = f"{prefix}_{seg.index:04d}.mp3"
            else:
                filename = f"{seg.index:03d}.mp3"
            out = str(Path(output_dir) / filename)

            success = False
            for attempt in range(1, max_retries + 1):
                try:
                    if Path(out).exists():
                        Path(out).unlink()
                except OSError:
                    pass

                ok = self.synthesize(seg.text, out)
                if ok and Path(out).exists() and Path(out).stat().st_size > 0:
                    success = True
                    break

                if attempt < max_retries:
                    if retry_cb:
                        retry_cb(seg, attempt, max_retries)
                    time.sleep(min(attempt * 0.5, 3.0))

            seg.audio_path = out if success else ""
            if rate_limit > 0:
                time.sleep(1.0 / rate_limit)
            return seg, success

        # Dùng submit + as_completed để callback fire NGAY khi từng đoạn xong,
        # không chờ theo thứ tự submit như ex.map()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_map = {ex.submit(_do, seg): seg for seg in segments}
            results_dict: dict = {}
            for fut in concurrent.futures.as_completed(future_map):
                seg, success = fut.result()
                results_dict[seg.index] = seg
                with _lock:
                    done_count[0] += 1
                    current = done_count[0]
                if progress_cb:
                    progress_cb(current, total)
                if segment_cb:
                    segment_cb(seg, success)

        # Trả về theo thứ tự gốc
        return [results_dict[seg.index] for seg in segments]


# ── Edge TTS (Microsoft, miễn phí) ───────────────────────────────────────────

class EdgeTTSEngine(TTSEngine):
    """
    Dùng thư viện edge-tts (gọi API Microsoft Edge miễn phí).
    Không cần API key. 300+ giọng, bao gồm tiếng Việt.
    """

    def __init__(self, voice: str = "vi-VN-HoaiMyNeural",
                 rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz"):
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self.pitch = pitch

    def _run_async(self, coro):
        """Chạy coroutine trong một event loop mới (thread-safe)"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    return pool.submit(asyncio.run, coro).result()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def synthesize(self, text: str, output_path: str, **kwargs) -> bool:
        try:
            import edge_tts  # type: ignore

            voice = kwargs.get("voice", self.voice)
            rate = kwargs.get("rate", self.rate)
            volume = kwargs.get("volume", self.volume)
            pitch = kwargs.get("pitch", self.pitch)

            async def _gen():
                communicate = edge_tts.Communicate(
                    text, voice, rate=rate, volume=volume, pitch=pitch
                )
                await communicate.save(output_path)

            self._run_async(_gen())
            return Path(output_path).exists()
        except Exception as e:
            print(f"[EdgeTTS] Lỗi: {e}")
            return False

    def list_voices(self, lang_filter: str = "") -> List[dict]:
        try:
            import edge_tts  # type: ignore

            async def _list():
                return await edge_tts.list_voices()

            raw = self._run_async(_list())
            voices = [
                {
                    "name": v["ShortName"],
                    "locale": v.get("Locale", ""),
                    "gender": v.get("Gender", ""),
                    "friendly_name": v.get("FriendlyName", v["ShortName"]),
                }
                for v in raw
            ]
            if lang_filter:
                voices = [v for v in voices if lang_filter.lower() in v["locale"].lower()]
            return sorted(voices, key=lambda x: x["locale"])
        except Exception as e:
            print(f"[EdgeTTS] list_voices lỗi: {e}")
            return []


class GoogleTTSEngine(TTSEngine):
    """
    Google Cloud Text-to-Speech.
    Cần service account credentials JSON.
    """

    def __init__(self, credentials: dict,
                 voice: str = "vi-VN-Wavenet-A", language_code: str = "vi-VN",
                 speaking_rate: float = 1.0, pitch: float = 0.0):
        self.credentials = credentials
        self.voice = voice
        self.language_code = language_code
        self.speaking_rate = speaking_rate
        self.pitch = pitch
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import json, tempfile
            from google.cloud import texttospeech  # type: ignore
            from google.oauth2 import service_account  # type: ignore

            # Ghi credentials ra file tạm
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            )
            json.dump(self.credentials, tmp)
            tmp.close()
            creds = service_account.Credentials.from_service_account_file(
                tmp.name,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            os.unlink(tmp.name)
            self._client = texttospeech.TextToSpeechClient(credentials=creds)
        except Exception as e:
            print(f"[GoogleTTS] Khởi tạo client lỗi: {e}")
        return self._client

    def synthesize(self, text: str, output_path: str, **kwargs) -> bool:
        try:
            from google.cloud import texttospeech  # type: ignore

            client = self._get_client()
            if not client:
                return False

            voice_name = kwargs.get("voice", self.voice)
            lang = kwargs.get("language_code", self.language_code)

            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice_params = texttospeech.VoiceSelectionParams(
                language_code=lang, name=voice_name
            )
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=kwargs.get("speaking_rate", self.speaking_rate),
                pitch=kwargs.get("pitch", self.pitch),
            )
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice_params,
                audio_config=audio_config,
            )
            Path(output_path).write_bytes(response.audio_content)
            return True
        except Exception as e:
            print(f"[GoogleTTS] Lỗi: {e}")
            return False

    def list_voices(self, lang_filter: str = "") -> List[dict]:
        try:
            from google.cloud import texttospeech  # type: ignore

            client = self._get_client()
            if not client:
                return []
            resp = client.list_voices(language_code=lang_filter or "")
            return [
                {
                    "name": v.name,
                    "locale": v.language_codes[0] if v.language_codes else "",
                    "gender": texttospeech.SsmlVoiceGender(v.ssml_gender).name,
                    "friendly_name": v.name,
                }
                for v in resp.voices
            ]
        except Exception as e:
            print(f"[GoogleTTS] list_voices lỗi: {e}")
            return []


# ── Factory ───────────────────────────────────────────────────────────────────

def create_engine(config) -> TTSEngine:
    """
    Factory: tạo engine phù hợp từ ConfigManager.
    config: instance của ConfigManager
    Hỗ trợ: "edge" | "google" | "omnivoice"
    """
    engine_type = config.get("tts_engine", "edge")

    # ── OmniVoice Colab (k2-fsa, self-hosted qua ngrok/Cloudflare tunnel) ─
    if engine_type == "omnivoice":
        creds = config.get_omnivoice_creds()
        if not creds:
            print("[Engine] OmniVoice endpoint trống, fallback sang Edge TTS")
            engine_type = "edge"
        else:
            from .omnivoice_engine import OmniVoiceColabEngine
            return OmniVoiceColabEngine(
                endpoint=creds.get("endpoint", ""),
                voice_kind=creds.get("voice_kind", "preset"),
                voice_id=config.get("voice_id", ""),
            )

    # ── Google Cloud TTS ──────────────────────────────────────────────────
    if engine_type == "google":
        creds = config.get_google_creds()
        if not creds:
            print("[Engine] Google credentials không hợp lệ, fallback sang Edge TTS")
            engine_type = "edge"
        else:
            return GoogleTTSEngine(
                credentials=creds,
                voice=config.get("voice_id", "vi-VN-Wavenet-A"),
                speaking_rate=float(config.get("speed", "1.0") or 1.0),
            )

    # ── Edge TTS (default / fallback) ─────────────────────────────────────
    return EdgeTTSEngine(
        voice=config.get("voice_id", "vi-VN-HoaiMyNeural"),
        rate=config.get("speed", "+0%"),
        volume=config.get("volume", "+0%"),
        pitch=config.get("pitch", "+0Hz"),
    )
