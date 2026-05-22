"""
Voice loader helper — dùng chung cho cả 3 tab (Settings/SRT/Text).

Tải danh sách giọng theo engine hiện tại trong config:
  - "omnivoice" → query OmniVoice server, filter theo voice_kind (preset/clone)
  - khác (edge/azure/google) → Edge list_voices() filter theo language code

Return: list[(label_to_display, voice_id_for_synth)]
"""
from typing import List, Tuple


def _label_omnivoice(v: dict) -> str:
    """'♀ Giảng đạo phật  (vi)' từ OmniVoice voice dict."""
    _id = v.get("id", "")
    _name = v.get("name", _id)
    _gender = (v.get("gender") or "").lower()
    _lang = v.get("lang", "")
    _icon = {"female": "♀", "male": "♂"}.get(_gender, "◆")
    return f"{_icon} {_name}" + (f"  ({_lang})" if _lang else "")


def _label_edge(v: dict) -> str:
    """'♀ HoaiMy  (vi-VN)' từ Edge voice dict."""
    gender_icon = {"Female": "♀", "Male": "♂"}.get(v.get("gender", ""), "◆")
    name_id = v["name"]
    locale = v.get("locale", "")
    parts = name_id.split("-")
    short = "-".join(parts[2:]) if len(parts) > 2 else name_id
    short = short.replace("Neural", "").replace("neural", "").strip()
    return f"{gender_icon} {short}  ({locale})"


def load_voices_for_config(config, lang_code: str = "vi-VN") -> List[Tuple[str, str]]:
    """Tải voices theo engine config. Trả list[(label, voice_id)] đã sort.

    OmniVoice: filter theo voice_kind đã chọn trong Settings.
    Edge/Azure/Google: filter theo lang_code (Edge API cho cả 3 vì list_voices của Edge
    bao trùm các locale chuẩn — engine SaaS khác cũng dùng cùng voice naming).
    """
    engine_type = config.get("tts_engine", "edge")

    if engine_type == "omnivoice":
        creds = config.get("omnivoice_credentials") or {}
        endpoint = (creds.get("endpoint") or "").strip()
        if not endpoint:
            print("[VoiceLoader] OmniVoice endpoint trống — chưa load được giọng")
            return []
        try:
            from core.omnivoice_engine import OmniVoiceColabEngine
            engine = OmniVoiceColabEngine(endpoint=endpoint)
            # Luôn fetch "all" từ server (server kind=preset có thể strict trả 0
            # nếu server chỉ có clones), filter client-side bằng _kind marker.
            kind_filter = creds.get("voice_kind", "preset")
            raw = engine.list_voices(kind="all")
            items: List[Tuple[str, str]] = []
            for v in raw:
                if v.get("_kind") != kind_filter:
                    continue
                _id = v.get("id", "")
                if not _id:
                    continue
                items.append((_label_omnivoice(v), _id))
            items.sort(key=lambda x: (0 if "♀" in x[0] else 1 if "♂" in x[0] else 2, x[0]))
            if not items:
                print(f"[VoiceLoader] OmniVoice trả 0 voices cho kind='{kind_filter}' "
                      f"(tổng raw: {len(raw)}) — thử switch voice_kind sang loại khác.")
            return items
        except Exception as e:
            print(f"[VoiceLoader] OmniVoice load fail: {e}")
            return []

    # Default path: Edge TTS list (cả Azure/Google cũng dùng được — naming chuẩn locale)
    try:
        from core.tts_engine import EdgeTTSEngine
        engine = EdgeTTSEngine()
        all_voices = engine.list_voices(lang_filter=lang_code)
        items = []
        for v in all_voices:
            if v.get("locale", "").lower() == lang_code.lower():
                items.append((_label_edge(v), v["name"]))
        items.sort(key=lambda x: (0 if "♀" in x[0] else 1 if "♂" in x[0] else 2, x[0]))
        return items
    except Exception as e:
        print(f"[VoiceLoader] Edge load fail: {e}")
        return []
