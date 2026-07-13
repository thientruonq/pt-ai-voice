#!/usr/bin/env python3
"""
PT AI Voice — License Key Generator (Admin Tool)

Sinh random License Key format PTAV-XXXX-XXXX-XXXX (12 hex chars uppercase).
Copy vào clipboard sẵn để paste vào Google Sheet.

Usage:
    python tools/gen-license.py                        # 1 key, copy clipboard
    python tools/gen-license.py --count 5              # 5 keys 1 lượt
    python tools/gen-license.py --name "Nguyễn A" \\
                               --max 2                 # in ra TSV row cho Sheet
    python tools/gen-license.py --no-clip              # không copy clipboard

Sheet paste TSV: mỗi row 6 cột (Key/Tên/Status/Ngày/Số/Max) — copy TSV
xong click ô A2 trong Sheet → paste → tự fill 6 cột.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import secrets
import subprocess
import sys

# Force UTF-8 stdout (Windows console default cp1252 phá box-drawing chars)
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


_PREFIX = "PTAV"
_GROUPS = 3          # số nhóm sau prefix
_GROUP_LEN = 4       # chars per group
_ALPHABET = "0123456789ABCDEF"  # uppercase hex → dễ đọc, dễ gõ tay


def _gen_key() -> str:
    """Sinh key format PTAV-XXXX-XXXX-XXXX (mỗi X là hex uppercase)."""
    groups = []
    for _ in range(_GROUPS):
        chars = ''.join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN))
        groups.append(chars)
    return f"{_PREFIX}-{'-'.join(groups)}"


def _copy_to_clipboard(text: str) -> bool:
    """Copy text vào clipboard. Trả True nếu OK."""
    if sys.platform == "win32":
        try:
            proc = subprocess.run(
                ["clip"], input=text, text=True, encoding="utf-8", check=True,
            )
            return proc.returncode == 0
        except Exception:
            return False
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["pbcopy"], input=text, text=True, encoding="utf-8", check=True,
            )
            return proc.returncode == 0
        except Exception:
            return False
    # Linux
    for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        try:
            proc = subprocess.run(cmd, input=text, text=True, encoding="utf-8", check=True)
            if proc.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _format_tsv_row(key: str, name: str, max_devices) -> str:
    """Format 1 row TSV theo schema Sheet: Key/Tên/Status/Ngày/Số/Max.
    Cột Số (E) để trống → server tự update.
    """
    today = _dt.datetime.now().strftime("%Y-%m-%d")
    max_str = str(max_devices) if max_devices not in (None, "") else ""
    return "\t".join([key, name, "active", today, "", max_str])


def main():
    ap = argparse.ArgumentParser(
        description="Sinh License Key cho PT AI Voice.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--count", "-n", type=int, default=1,
                    help="Số key sinh ra (default 1)")
    ap.add_argument("--name", default="", help="Tên user (cột B trong Sheet)")
    ap.add_argument("--max", dest="max_devices", default="",
                    help="Max thiết bị (cột F — để trống = không giới hạn)")
    ap.add_argument("--no-clip", action="store_true",
                    help="KHÔNG copy vào clipboard")
    ap.add_argument("--tsv", action="store_true",
                    help="In TSV row ready to paste vào Sheet (ngầm ON nếu có --name)")
    args = ap.parse_args()

    if args.count < 1 or args.count > 100:
        print("[Error] --count phải trong [1, 100]", file=sys.stderr)
        sys.exit(1)

    keys = [_gen_key() for _ in range(args.count)]

    # Nếu có metadata → format TSV row cho từng key
    want_tsv = args.tsv or bool(args.name) or bool(args.max_devices)

    if want_tsv:
        rows = [_format_tsv_row(k, args.name, args.max_devices) for k in keys]
        clip_content = "\n".join(rows)
        print("┌" + "─" * 78 + "┐")
        print("│ TSV rows (paste ô A2 trong Sheet):" + " " * 43 + "│")
        print("└" + "─" * 78 + "┘")
        for r in rows:
            print(r)
    else:
        clip_content = "\n".join(keys)
        print("┌" + "─" * 78 + "┐")
        print("│ License keys sinh mới:" + " " * 55 + "│")
        print("└" + "─" * 78 + "┘")
        for k in keys:
            print(f"  {k}")

    if not args.no_clip:
        if _copy_to_clipboard(clip_content):
            what = "TSV rows" if want_tsv else f"{len(keys)} key(s)"
            print(f"\n✓ Đã copy {what} vào clipboard.")
        else:
            print("\n⚠ Không copy được clipboard (thiếu tool clip/pbcopy/xclip).")

    if not want_tsv:
        print("\nBước tiếp: paste key vào Google Sheet cột A, điền Tên/Email/Status=active.")
    else:
        print("\nBước tiếp: mở Sheet → click ô A của row trống → Ctrl+V.")


if __name__ == "__main__":
    main()
