# License Setup Guide — PT AI Voice

Hướng dẫn deploy hệ thống License validation (Google Sheet + Apps Script) cho PT AI Voice.

## Kiến trúc

```
┌──────────────┐   HMAC-signed POST    ┌─────────────────┐   Read/write   ┌──────────────┐
│  PT AI Voice │ ────────────────────▶│  Apps Script    │◀──────────────▶│ Google Sheet │
│  (client)    │                       │  (Web App)      │                │              │
└──────────────┘                       └─────────────────┘                └──────────────┘
      ▲                                                                          │
      │ ⛔ Xóa row / set status=revoked                                         │
      └──────────────────────────────────────────────────────────────────────────┘
                              → App detect trong 24h → force re-activate
```

- Client encrypt license key bằng Fernet (AES-128), bind vào machine ID → `license.dat` không portable
- HMAC-SHA256 sign mọi request → chống replay attack, chặn client giả
- Sheet 2 tab: `Licenses` (admin manage) + `Devices` (auto-track thiết bị active)
- Cache offline 7 ngày — mất mạng vẫn dùng được

## 1. Tạo Google Sheet

1. Vào [sheets.google.com](https://sheets.google.com) → tạo Sheet mới
2. Đổi tên tab đầu tiên thành **`Licenses`**
3. Header hàng 1:

| A | B | C | D | E | F | G |
|---|---|---|---|---|---|---|
| License Key | Tên | Email | Status | Ngày cấp | Số thiết bị | Max thiết bị |

4. Thêm sample data:

| License Key | Tên | Email | Status | Ngày cấp | Số thiết bị | Max thiết bị |
|---|---|---|---|---|---|---|
| PTAV-ABCD-1234-EFGH | Nguyễn A | a@gmail.com | active | 2026-07-13 | (auto) | 2 |
| PTAV-EFGH-5678-IJKL | Trần B | b@gmail.com | revoked | 2026-07-13 | (auto) | 3 |

**Status:** `active` (cho dùng) hoặc `revoked` (bị chặn)
**Max thiết bị:** để trống = không giới hạn, `0` = chặn tất cả, `N` = giới hạn N máy

Tab `Devices` sẽ tự tạo khi có request đầu tiên.

## 2. Deploy Apps Script

1. Trong Sheet: **Extensions → Apps Script**
2. Xóa code mẫu, paste toàn bộ [docs/google-apps-script.js](google-apps-script.js)
3. Save (Ctrl+S) → đặt tên project (VD: "PT AI Voice License")
4. Click **Deploy → New Deployment**:
   - **Type:** Web app
   - **Description:** PT AI Voice License API
   - **Execute as:** Me (chủ Sheet)
   - **Who has access:** **Anyone** ⚠ QUAN TRỌNG
5. Click **Deploy** → authorize khi được hỏi
6. Copy URL kiểu `https://script.google.com/macros/s/AKfyc.../exec`

## 3. Gắn URL vào code

Edit `core/license.py` dòng 43:

```python
LICENSE_API_URL = "https://script.google.com/macros/s/YOUR_ID/exec"
```

Paste URL vừa copy. Rebuild `.exe` và ship cho user.

**Dev mode:** để URL rỗng (`""`) → `verify_online()` return `("active", "Dev Mode")` → bypass license, không cần Sheet khi phát triển.

## 4. Cấp key cho user

1. Mở Sheet → thêm row mới với key format `PTAV-XXXX-XXXX-XXXX`
2. Status = `active`, Max thiết bị = số máy user được dùng
3. Gửi key cho user qua email/chat

## 5. Thu hồi key

**Cách 1 (nhẹ):** đổi Status cột D từ `active` → `revoked`
**Cách 2 (mạnh):** xóa cả row

Client sẽ phát hiện trong tối đa 24h (period check) HOẶC lần startup tiếp theo. Khi phát hiện → messagebox "License đã bị thu hồi" → app tự đóng.

## 6. Quản lý thiết bị

- Trong Sheet: menu **⚙️ PT AI Voice** (tự tạo lúc mở Sheet)
- Chọn **🔄 Cập nhật số thiết bị** → refresh cột F ngay
- Chọn **⏰ Bật tự động cập nhật mỗi giờ** → trigger cron chạy hourly
- Device không request > 30 ngày → tự xóa khỏi tab Devices

**Cấp lại slot:** vào tab `Devices` → xóa row của device cũ → user machine mới có thể activate.

## 7. Client lifecycle

| Trạng thái | Hành vi |
|---|---|
| **no_key** (chưa activate) | Hiện ActivationWindow, block app |
| **active** (cache < 7 ngày) | Vào app ngay, verify background |
| **expired** (cache > 7 ngày) | Blocking online verify trước khi vào app |
| **revoked** | ActivationWindow + msg "Tài khoản bị vô hiệu hóa" |
| **not_found** | ActivationWindow + msg "Key không tồn tại" |
| **max_devices** | ActivationWindow + msg "Vượt giới hạn thiết bị" |
| **offline** (cache hết hạn + mất mạng) | ActivationWindow + msg "Cần internet" |
| **active_offline** (cache còn hạn + mất mạng) | Vào app bình thường |

## 8. Storage local (client)

- Windows: `%APPDATA%\PT-AI-Voice\license.dat`
- macOS: `~/Library/Application Support/PT-AI-Voice/license.dat`
- Linux: `~/.config/PT-AI-Voice/license.dat`

File chứa: encrypted key + status + last_check timestamp.
`stable_id.txt` cùng thư mục — machine ID persistent (fix macOS MAC randomization).

Xóa 2 file này = reset license → user cần re-activate.

## Troubleshooting

**"Invalid signature" trên Apps Script log:**
- HMAC namespace client/server không khớp. Verify:
  - Python `_get_signing_key()` prefix "PTAIVoiceLicSign" + SHA256("PTAIVoiceV1")[:16]
  - JS `_SIGNING_PREFIX` byte array giống hệt + `Utilities.computeDigest("PTAIVoiceV1")`

**"Request expired":** client timestamp lệch server > 5 phút. Đồng bộ NTP client.

**Verify_online return "error":** không mạng / URL sai / Apps Script quota exceeded. Client fallback dùng cache 7 ngày.

**User dùng chung Sheet với Auto-YTB:** không được — HMAC namespace khác nhau (`AutoReupV1` vs `PTAIVoiceV1`). Cần Sheet riêng.
