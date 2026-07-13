/**
 * PT AI Voice — Google Apps Script (License Validation API)
 *
 * HƯỚNG DẪN SETUP:
 * ─────────────────────────────────────────────────────────────────────────────
 * 1. Tạo Google Sheet mới tại sheets.google.com
 *    Đặt tên sheet tab đầu tiên là "Licenses"
 *
 * 2. Tạo header ở hàng 1:
 *    A1: License Key | B1: Tên | C1: Email | D1: Status | E1: Ngày cấp
 *    F1: Số thiết bị | G1: Max thiết bị
 *
 * 3. Thêm dữ liệu từ hàng 2 trở đi, ví dụ:
 *    A2: PTAV-ABCD-1234-EFGH | B2: Nguyễn A | C2: a@gmail.com | D2: active | E2: 2026-07-13 | F2: (tự cập nhật) | G2: 2
 *    A3: PTAV-EFGH-5678-IJKL | B3: Trần B   | C3: b@gmail.com | D3: revoked | E3: 2026-07-13 | F3: (tự cập nhật) | G3: 3
 *
 *    Status hợp lệ: "active" (cho dùng) | "revoked" (bị chặn)
 *    G (Max thiết bị): Số lượng tối đa thiết bị. Để trống = không giới hạn. 0 = chặn tất cả.
 *
 * 4. Script sẽ tự tạo sheet tab "Devices" khi có request đầu tiên.
 *    Sheet "Devices" lưu: License Key | Device ID | Hostname | Last Seen
 *
 * 5. Vào menu Extensions → Apps Script → Paste toàn bộ code này vào
 *
 * 6. Click Deploy → New Deployment:
 *    - Type: Web app
 *    - Execute as: Me
 *    - Who has access: Anyone     ← QUAN TRỌNG
 *    → Copy URL được cấp
 *
 * 7. Paste URL vào core/license.py:
 *    LICENSE_API_URL = "https://script.google.com/macros/s/YOUR_ID/exec"
 * ─────────────────────────────────────────────────────────────────────────────
 */

// Số ngày không hoạt động → tự xóa device khỏi danh sách
var INACTIVE_DAYS = 30;

// ── HMAC signing key (must match core/license.py _get_signing_key) ───────────
// Static prefix bytes spell out "PTAIVoiceLicSign" (ASCII).
// Suffix = first 16 bytes of SHA-256("PTAIVoiceV1"), computed at runtime via
// Utilities.computeDigest so value matches Python side exactly.
var _SIGNING_PREFIX = [0x50,0x54,0x41,0x49, 0x56,0x6f,0x69,0x63,
                       0x65, 0x4c,0x69,0x63, 0x53,0x69,0x67,0x6e];

/**
 * Reconstruct signing key as signed-byte array (GAS HMAC convention).
 * prefix("PTAIVoiceLicSign") + first16(SHA-256("PTAIVoiceV1"))
 * Matches Python: b''.join(parts) + hashlib.sha256(b'PTAIVoiceV1').digest()[:16]
 */
function _getSigningKey() {
  var hashBytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.SHA_256,
    "PTAIVoiceV1",
    Utilities.Charset.US_ASCII
  ).slice(0, 16);

  var prefix = _SIGNING_PREFIX.map(function(b) { return b > 127 ? b - 256 : b; });

  return prefix.concat(hashBytes);
}

/**
 * Verify HMAC-SHA256 signature from client.
 * message = key + device_id + timestamp (all strings, concatenated)
 */
function _verifySignature(key, deviceId, timestamp, signature) {
  var message = Utilities.newBlob(key + deviceId + String(timestamp)).getBytes();
  var keyBytes = _getSigningKey();
  var computed = Utilities.computeHmacSha256Signature(message, keyBytes);
  var hex = computed.map(function(b) {
    return ('0' + (b & 0xff).toString(16)).slice(-2);
  }).join('');
  return hex === signature;
}


/**
 * Handle POST requests (primary entry point).
 * Includes HMAC verification + replay-attack protection (5-minute window).
 */
function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return _json({ status: "error", name: "", message: "Invalid JSON body" });
  }

  var key       = (String(body.key       || "")).toUpperCase().trim();
  var deviceId  = (String(body.device_id || "")).trim();
  var hostname  = (String(body.hostname  || "")).trim();
  var timestamp = parseInt(body.timestamp) || 0;
  var signature = (String(body.signature || "")).trim();

  // ── Replay-attack protection: reject requests older than 5 minutes ──
  var now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - timestamp) > 300) {
    return _json({ status: "error", name: "", message: "Request expired" });
  }

  // ── HMAC verification ──
  if (!key || !signature || !_verifySignature(key, deviceId, timestamp, signature)) {
    return _json({ status: "error", name: "", message: "Invalid signature" });
  }

  return _processLicenseRequest(key, deviceId, hostname);
}

/**
 * GET handler — kept for backward compatibility (browser test, manual debug).
 * Does NOT require HMAC; production client uses doPost with signing.
 */
function doGet(e) {
  var key      = ((e.parameter && e.parameter.key) || "").toString().toUpperCase().trim();
  var deviceId = ((e.parameter && e.parameter.device_id) || "").toString().trim();
  var hostname = ((e.parameter && e.parameter.hostname) || "").toString().trim();

  if (!key) {
    return _json({ status: "not_found", name: "" });
  }
  return _processLicenseRequest(key, deviceId, hostname);
}

/**
 * Core license-check logic shared by doGet and doPost.
 */
function _processLicenseRequest(key, deviceId, hostname) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var licSheet = ss.getSheetByName("Licenses") || ss.getSheets()[0];
    var licData  = licSheet.getDataRange().getValues();

    var foundRow   = -1;
    var name       = "";
    var status     = "not_found";
    var maxDevices = 0;

    for (var i = 1; i < licData.length; i++) {
      var rowKey = String(licData[i][0]).toUpperCase().trim();
      if (rowKey === key) {
        foundRow   = i;
        name       = String(licData[i][1] || "").trim();
        status     = String(licData[i][3] || "").toLowerCase().trim();
        var rawMax = licData[i][6];
        maxDevices = (rawMax === "" || rawMax === null || rawMax === undefined)
                     ? -1 : (parseInt(rawMax) || 0);
        break;
      }
    }

    if (foundRow === -1) {
      return _json({ status: "not_found", name: "" });
    }

    if (status !== "active" && status !== "revoked") {
      status = "not_found";
    }

    if (status !== "active") {
      return _json({ status: status, name: name, device_count: 0 });
    }

    var deviceCount = 0;

    if (deviceId) {
      var devSheet = _getOrCreateDevicesSheet(ss);
      deviceCount = _upsertDevice(devSheet, key, deviceId, hostname, maxDevices);

      if (deviceCount === -1) {
        var realCount = _countDevices(devSheet, key);
        licSheet.getRange(foundRow + 1, 6).setValue(realCount);
        return _json({ status: "max_devices", name: name, device_count: realCount, max_devices: maxDevices });
      }

      licSheet.getRange(foundRow + 1, 6).setValue(deviceCount);
    }

    return _json({ status: "active", name: name, device_count: deviceCount });

  } catch (err) {
    return _json({ status: "error", name: "", message: err.toString() });
  }
}


// ═══════════════════════════════════════════════════════════════════════════
// DEVICES SHEET MANAGEMENT
// ═══════════════════════════════════════════════════════════════════════════

function _getOrCreateDevicesSheet(ss) {
  var sheet = ss.getSheetByName("Devices");
  if (!sheet) {
    sheet = ss.insertSheet("Devices");
    sheet.appendRow(["License Key", "Device ID", "Hostname", "Last Seen"]);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/**
 * Upsert device: cập nhật Last Seen nếu đã tồn tại, hoặc thêm mới.
 * Đồng thời dọn device không hoạt động quá INACTIVE_DAYS ngày.
 * Trả về số device hiện tại cho key đó, hoặc -1 nếu vượt giới hạn.
 */
function _upsertDevice(devSheet, key, deviceId, hostname, maxDevices) {
  var data = devSheet.getDataRange().getValues();
  var now  = new Date();
  var cutoff = new Date(now.getTime() - INACTIVE_DAYS * 24 * 3600 * 1000);

  var existingRow = -1;
  var countForKey = 0;
  var rowsToDelete = [];

  for (var i = 1; i < data.length; i++) {
    var rKey = String(data[i][0]).toUpperCase().trim();
    var rDev = String(data[i][1]).trim();
    var rDate = data[i][3];

    if (rDate instanceof Date && rDate < cutoff) {
      rowsToDelete.push(i + 1);
      continue;
    }

    if (rKey === key) {
      if (rDev === deviceId) {
        existingRow = i + 1;
      } else {
        countForKey++;
      }
    }
  }

  for (var d = rowsToDelete.length - 1; d >= 0; d--) {
    devSheet.deleteRow(rowsToDelete[d]);
    if (existingRow > rowsToDelete[d]) {
      existingRow--;
    }
  }

  if (existingRow > 0) {
    if (maxDevices === 0) {
      return -1;
    }
    devSheet.getRange(existingRow, 3).setValue(hostname);
    devSheet.getRange(existingRow, 4).setValue(now);
    return countForKey + 1;
  }

  if (maxDevices === 0 || (maxDevices > 0 && countForKey >= maxDevices)) {
    return -1;
  }

  devSheet.appendRow([key, deviceId, hostname, now]);
  return countForKey + 1;
}

function _countDevices(devSheet, key) {
  var data = devSheet.getDataRange().getValues();
  var count = 0;
  for (var i = 1; i < data.length; i++) {
    if (String(data[i][0]).toUpperCase().trim() === key) {
      count++;
    }
  }
  return count;
}


// ═══════════════════════════════════════════════════════════════════════════
// CẬP NHẬT SỐ THIẾT BỊ
// ═══════════════════════════════════════════════════════════════════════════

function refreshDeviceCounts() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var licSheet = ss.getSheetByName("Licenses") || ss.getSheets()[0];
  var devSheet = ss.getSheetByName("Devices");

  if (!devSheet) {
    var licData = licSheet.getDataRange().getValues();
    for (var i = 1; i < licData.length; i++) {
      licSheet.getRange(i + 1, 6).setValue(0);
    }
    return;
  }

  var devData = devSheet.getDataRange().getValues();
  var now = new Date();
  var cutoff = new Date(now.getTime() - INACTIVE_DAYS * 24 * 3600 * 1000);
  var rowsToDelete = [];

  for (var i = 1; i < devData.length; i++) {
    var rDate = devData[i][3];
    if (rDate instanceof Date && rDate < cutoff) {
      rowsToDelete.push(i + 1);
    }
  }
  for (var d = rowsToDelete.length - 1; d >= 0; d--) {
    devSheet.deleteRow(rowsToDelete[d]);
  }

  var freshDevData = devSheet.getDataRange().getValues();
  var countMap = {};

  for (var i = 1; i < freshDevData.length; i++) {
    var k = String(freshDevData[i][0]).toUpperCase().trim();
    if (k) {
      countMap[k] = (countMap[k] || 0) + 1;
    }
  }

  var licData = licSheet.getDataRange().getValues();
  for (var i = 1; i < licData.length; i++) {
    var licKey = String(licData[i][0]).toUpperCase().trim();
    var count = countMap[licKey] || 0;
    licSheet.getRange(i + 1, 6).setValue(count);
  }
}

/**
 * Tạo menu tùy chỉnh trong Google Sheet.
 */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("⚙️ PT AI Voice")
    .addItem("🔄 Cập nhật số thiết bị + dọn inactive", "refreshDeviceCounts")
    .addSeparator()
    .addItem("⏰ Bật tự động cập nhật mỗi giờ", "setupHourlyTrigger")
    .addItem("❌ Tắt tự động cập nhật", "removeTriggers")
    .addToUi();
}

function setupHourlyTrigger() {
  removeTriggers();
  ScriptApp.newTrigger("refreshDeviceCounts")
    .timeBased()
    .everyHours(1)
    .create();
  SpreadsheetApp.getUi().alert("✅ Đã bật tự động cập nhật số thiết bị mỗi giờ.");
}

function removeTriggers() {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === "refreshDeviceCounts") {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
}


// ═══════════════════════════════════════════════════════════════════════════

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
