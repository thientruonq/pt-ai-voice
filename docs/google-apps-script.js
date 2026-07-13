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
    .addItem("➕ Tạo license key mới", "generateNewLicense")
    .addSeparator()
    .addItem("🔄 Cập nhật số thiết bị + dọn inactive", "refreshDeviceCounts")
    .addSeparator()
    .addItem("⏰ Bật tự động cập nhật mỗi giờ", "setupHourlyTrigger")
    .addItem("❌ Tắt tự động cập nhật", "removeTriggers")
    .addToUi();
}


// ═══════════════════════════════════════════════════════════════════════════
// TẠO LICENSE KEY MỚI (admin bấm menu để cấp)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Sinh 1 key random format PTAV-XXXX-XXXX-XXXX (hex uppercase).
 * 16^12 ≈ 2.8e14 → collision không đáng lo.
 */
function _genLicenseKey() {
  var alphabet = "0123456789ABCDEF";
  var groups = [];
  for (var g = 0; g < 3; g++) {
    var s = "";
    for (var i = 0; i < 4; i++) {
      s += alphabet.charAt(Math.floor(Math.random() * 16));
    }
    groups.push(s);
  }
  return "PTAV-" + groups.join("-");
}

/**
 * Menu "➕ Tạo license key mới" → prompt name/email/max → append row Licenses
 * → show dialog có nút Copy để admin gửi key cho user.
 */
function generateNewLicense() {
  var ui = SpreadsheetApp.getUi();

  // Prompt name (bắt buộc)
  var nameResp = ui.prompt(
    "Tạo License Key mới",
    "Tên người dùng (bắt buộc):",
    ui.ButtonSet.OK_CANCEL
  );
  if (nameResp.getSelectedButton() !== ui.Button.OK) return;
  var name = nameResp.getResponseText().trim();
  if (!name) {
    ui.alert("⚠️ Tên không được để trống.");
    return;
  }

  // Prompt email (optional — Cancel = bỏ qua)
  var emailResp = ui.prompt(
    "Tạo License Key mới",
    "Email (tùy chọn — bỏ trống được):",
    ui.ButtonSet.OK_CANCEL
  );
  if (emailResp.getSelectedButton() !== ui.Button.OK) return;
  var email = emailResp.getResponseText().trim();

  // Prompt max devices (optional — trống = không giới hạn)
  var maxResp = ui.prompt(
    "Tạo License Key mới",
    "Max thiết bị (số nguyên; trống = không giới hạn; 0 = chặn):",
    ui.ButtonSet.OK_CANCEL
  );
  if (maxResp.getSelectedButton() !== ui.Button.OK) return;
  var maxRaw = maxResp.getResponseText().trim();
  var maxDev = "";
  if (maxRaw !== "") {
    var parsed = parseInt(maxRaw, 10);
    if (isNaN(parsed) || parsed < 0) {
      ui.alert("⚠️ Max thiết bị phải là số nguyên >= 0.");
      return;
    }
    maxDev = parsed;
  }

  // Kiểm tra collision (rất hiếm nhưng để chắc)
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var licSheet = ss.getSheetByName("Licenses") || ss.getSheets()[0];
  var existing = licSheet.getRange("A:A").getValues()
    .map(function(r) { return String(r[0]).toUpperCase().trim(); });

  var key = "";
  for (var attempt = 0; attempt < 10; attempt++) {
    key = _genLicenseKey();
    if (existing.indexOf(key) === -1) break;
  }

  // Append row: [key, name, email, active, ngày, số (blank), max]
  var today = Utilities.formatDate(new Date(), Session.getScriptTimeZone() || "GMT", "yyyy-MM-dd");
  licSheet.appendRow([key, name, email, "active", today, "", maxDev]);

  // Show dialog có nút Copy
  _showKeyDialog(key, name, email, maxDev);
}

/**
 * Hiện HTML dialog với key + nút Copy (dùng clipboard API).
 */
function _showKeyDialog(key, name, email, maxDev) {
  var maxStr = (maxDev === "" || maxDev === null) ? "Không giới hạn" : String(maxDev);
  var html = ''
    + '<style>'
    + '  body { font-family: Segoe UI, Arial, sans-serif; padding: 16px; color: #1e293b; }'
    + '  .key-box { background: #f1f5f9; border: 2px dashed #64748b; padding: 14px;'
    + '             border-radius: 8px; text-align: center; margin: 12px 0; }'
    + '  .key { font-family: Consolas, monospace; font-size: 22px; font-weight: 700;'
    + '         color: #2563eb; letter-spacing: 1px; user-select: all; }'
    + '  .info { font-size: 13px; color: #475569; margin: 4px 0; }'
    + '  .info b { color: #1e293b; }'
    + '  button { background: #16a34a; color: white; border: none; padding: 10px 18px;'
    + '           border-radius: 6px; font-size: 14px; cursor: pointer; font-weight: 600; }'
    + '  button:hover { background: #15803d; }'
    + '  button.close { background: #64748b; margin-left: 8px; }'
    + '  button.close:hover { background: #475569; }'
    + '  #status { font-size: 12px; color: #16a34a; margin-left: 10px; font-weight: 600; }'
    + '</style>'
    + '<div>'
    + '  <div class="info"><b>Tên:</b> ' + _escapeHtml(name) + '</div>'
    + (email ? '  <div class="info"><b>Email:</b> ' + _escapeHtml(email) + '</div>' : '')
    + '  <div class="info"><b>Max thiết bị:</b> ' + _escapeHtml(maxStr) + '</div>'
    + '  <div class="key-box">'
    + '    <div class="key" id="key">' + key + '</div>'
    + '  </div>'
    + '  <div>'
    + '    <button onclick="doCopy()">📋 Copy Key</button>'
    + '    <button class="close" onclick="google.script.host.close()">Đóng</button>'
    + '    <span id="status"></span>'
    + '  </div>'
    + '</div>'
    + '<script>'
    + '  function doCopy() {'
    + '    var text = document.getElementById("key").textContent;'
    + '    navigator.clipboard.writeText(text).then(function() {'
    + '      document.getElementById("status").textContent = "✓ Đã copy!";'
    + '    }, function() {'
    + '      var r = document.createRange(); r.selectNode(document.getElementById("key"));'
    + '      window.getSelection().removeAllRanges();'
    + '      window.getSelection().addRange(r);'
    + '      document.execCommand("copy");'
    + '      document.getElementById("status").textContent = "✓ Đã copy!";'
    + '    });'
    + '  }'
    + '</script>';

  var htmlOutput = HtmlService.createHtmlOutput(html)
    .setWidth(420)
    .setHeight(280);
  SpreadsheetApp.getUi().showModalDialog(htmlOutput, "✅ License Key đã tạo");
}

function _escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
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
