/**
 * ============================================================================
 * [파일명] apps_script_webapp.gs
 * [역할] 매장 통합 관리 시스템 Google Apps Script 웹앱 (통합 백엔드)
 * [지원 액션]
 *   1. upload_pdf    : 전자 근로계약서 PDF 구글 드라이브 업로드
 *   2. send_email    : 근로계약서 사본 · 세무사 보고 · 직원 급여명세서 이메일 발송
 *   3. payment_alert : 갤럭시(MacroDroid) 우리은행 입금 / chak 지역상품권 결제
 *                      알림 수신 → 잔액·계좌번호 자동 제거 → 시트 기록 → 텔레그램 방 발송
 * [배포 방법]
 *   Apps Script 편집기 → 배포 → 새 배포(또는 배포 관리 수정) → 유형: 웹 앱
 *   → 다음 사용자 권한으로 실행: 나 / 액세스 권한이 있는 사용자: 모든 사용자
 * ============================================================================
 */

var DEFAULT_DB_ID = "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8";

function doPost(e) {
  try {
    var data = parseRequestPayload_(e);
    var action = String(data.action || "").trim();

    if (action === "upload_pdf") {
      return jsonResponse_(handleUploadPdf_(data));
    }
    if (action === "send_email") {
      return jsonResponse_(handleSendEmail_(data));
    }
    if (action === "payment_alert") {
      return jsonResponse_(handlePaymentAlert_(data));
    }
    return jsonResponse_({ ok: false, error: "지원하지 않는 action입니다: " + action });
  } catch (err) {
    return jsonResponse_({ ok: false, error: String(err) });
  }
}

function doGet() {
  return jsonResponse_({ ok: true, status: "running" });
}

function jsonResponse_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * JSON(Streamlit)과 Form Parameters(MacroDroid x-www-form-urlencoded)를 모두 안전하게 파싱합니다.
 */
function parseRequestPayload_(e) {
  if (!e) return {};
  if (e.parameter && e.parameter.action) {
    return e.parameter;
  }
  if (e.postData && e.postData.contents) {
    var raw = String(e.postData.contents);
    try {
      return JSON.parse(raw);
    } catch (jsonErr) {
      // MacroDroid 등에서 JSON 문자열 안에 줄바꿈이 그대로 들어온 경우 보정
      var sanitized = raw.replace(/\r?\n/g, " ");
      try {
        return JSON.parse(sanitized);
      } catch (err2) {
        if (e.parameter && Object.keys(e.parameter).length > 0) {
          return e.parameter;
        }
        throw jsonErr;
      }
    }
  }
  return e.parameter || {};
}

// ============================================================================
// 1. 구글 드라이브 PDF 업로드 (계약서)
// ============================================================================
function handleUploadPdf_(data) {
  var folderId = String(data.folderId || "").trim();
  var filename = String(data.filename || "contract.pdf").trim();
  var base64Data = String(data.base64Data || "");
  if (!folderId || !base64Data) {
    return { ok: false, error: "folderId 또는 base64Data가 비어 있습니다." };
  }
  var bytes = Utilities.base64Decode(base64Data);
  var blob = Utilities.newBlob(bytes, "application/pdf", filename);
  var folder = DriveApp.getFolderById(folderId);
  var file = folder.createFile(blob);
  return { ok: true, url: file.getUrl(), fileId: file.getId() };
}

// ============================================================================
// 2. 이메일 발송 (계약서 / 세무사 / 급여명세서 / 테스트)
// ============================================================================
function handleSendEmail_(data) {
  var toEmail = String(data.toEmail || "").trim();
  var subject = String(data.subject || "").trim();
  var body = String(data.body || "");
  if (!toEmail || !subject) {
    return { ok: false, error: "toEmail 또는 subject가 비어 있습니다." };
  }

  var options = {};
  if (data.base64Data && data.filename) {
    var mimeType = String(data.mimeType || "application/octet-stream");
    var bytes = Utilities.base64Decode(String(data.base64Data));
    var blob = Utilities.newBlob(bytes, mimeType, String(data.filename));
    options.attachments = [blob];
  }
  MailApp.sendEmail(toEmail, subject, body, options);
  return { ok: true };
}

// ============================================================================
// 3. 실시간 우리은행 입금 · chak 지역상품권 결제 알림 처리
// ============================================================================
function handlePaymentAlert_(data) {
  var dbId = String(data.dbId || DEFAULT_DB_ID).trim() || DEFAULT_DB_ID;
  var ss = SpreadsheetApp.openById(dbId);
  var cfg = loadStoreConfigMap_(ss);

  // 1) 웹훅 보안키 검증
  var expectedSecret = String(cfg.payment_webhook_secret || "").trim();
  var providedSecret = String(data.secretKey || "").trim();
  if (expectedSecret && providedSecret !== expectedSecret) {
    return { ok: false, error: "웹훅 보안키(secretKey)가 일치하지 않습니다." };
  }

  // 1-2) 영업시간 내 수신 여부 체크 (영업시간 외 개인 입금·정산 입금 등 자동 무시)
  var now = new Date();
  var ignoreBiz = String(data.ignoreBusinessHours || "").trim().toUpperCase() === "TRUE";
  var bizOnly = String(cfg.payment_biz_hours_only || "TRUE").trim().toUpperCase() === "TRUE";
  var bizStart = String(cfg.payment_biz_start || "11:00").trim();
  var bizEnd = String(cfg.payment_biz_end || "23:00").trim();
  if (!ignoreBiz && bizOnly && !isWithinBusinessHours_(now, bizStart, bizEnd)) {
    return {
      ok: true,
      skipped: "outside_business_hours",
      businessHours: bizStart + "~" + bizEnd,
    };
  }

  var storeTitle = String(cfg.store_title || data.storeName || "매장").trim();
  var source = String(data.source || "").trim();
  var title = String(data.title || "").trim();
  var body = String(data.body || "").trim();
  var combined = (title + " " + body).replace(/\s+/g, " ").trim();

  if (!combined) {
    return { ok: true, skipped: "empty" };
  }

  // 2) 입금 / chak 결제 여부 판별 (출금·광고·일반 알림 원천 차단)
  var isChak =
    /chak|착|상품권/i.test(source) ||
    /chak|성남사랑|지역화폐|지역상품권|상품권/i.test(combined);

  var category = "";
  if (isChak) {
    if (/취소/.test(combined)) {
      category = "chak취소";
    } else if (/결제|승인|완료|입금|원/.test(combined)) {
      category = "chak결제";
    } else {
      return { ok: true, skipped: "chak_non_payment" };
    }
  } else {
    // 우리은행 푸시: '[출금]' 원천 차단, '입출금알림' 제목 문구 제거 후 '입금' 여부 판별
    if (/\[출금\]/.test(combined)) {
      return { ok: true, skipped: "withdrawal" };
    }
    var checkText = combined.replace(/입출금알림/g, " ");
    if (/출금|송금/.test(checkText) && !/입금/.test(checkText)) {
      return { ok: true, skipped: "withdrawal" };
    }
    if (!/입금/.test(checkText)) {
      return { ok: true, skipped: "non_deposit" };
    }
    category = "계좌입금";
  }

  // 3) 잔액 및 계좌번호 민감 정보 완전 제거 (금액 추출 전 선행 필수!)
  var safeText = stripSensitiveBankInfo_(combined);

  // 4) 금액 추출 (잔액 제거 후 첫 번째 원화 금액)
  var amount = extractWonAmount_(safeText);
  if (amount <= 0) {
    return { ok: true, skipped: "no_amount" };
  }

  // 5) 입금자명 / 상세 내용 정제
  var detail = extractPayerOrDetail_(safeText, category);

  // 5-2) 대표 본인 등 제외 입금자명 필터 (우리은행 계좌입금 전용)
  var excludedRaw =
    cfg.payment_excluded_senders !== undefined
      ? String(cfg.payment_excluded_senders)
      : "이용석";
  if (!isChak && isExcludedSender_(detail, safeText, excludedRaw)) {
    return { ok: true, skipped: "excluded_sender", detail: detail };
  }

  // 6) 시트 '입금확인로그' 탭 준비 및 15초 내 중복 방지 (푸시+SMS 동시 수신 대비)
  var ws = getOrCreatePaymentLogSheet_(ss);
  var nowStr = Utilities.formatDate(now, "Asia/Seoul", "yyyy-MM-dd HH:mm:ss");
  var timeOnly = Utilities.formatDate(now, "Asia/Seoul", "HH:mm:ss");

  if (isRecentDuplicate_(ws, now, category, amount, detail, 15)) {
    return { ok: true, skipped: "duplicate", category: category, amount: amount };
  }

  ws.appendRow([nowStr, category, detail, amount, safeText, "대기"]);

  // 7) 매장 입금확인 전용 텔레그램 방으로 즉시 알림 발송
  var botToken = String(cfg.telegram_bot_token || "").trim();
  var payChatIdsRaw = String(cfg.payment_telegram_chat_id || "").trim();
  var sentCount = 0;

  if (botToken && payChatIdsRaw) {
    var icon = category === "chak취소" ? "⚠️" : (isChak ? "🎫" : "💰");
    var detailLabel = isChak ? "내용" : "입금자";
    var amountFormatted = Number(amount).toLocaleString("en-US") + "원";
    var tgMsg =
      icon + " [" + storeTitle + " " + category + " 확인]\n" +
      "• 금액: " + amountFormatted + "\n" +
      "• " + detailLabel + ": " + detail + "\n" +
      "• 시각: " + timeOnly;

    var chatIds = payChatIdsRaw.split(/[,;\s]+/).filter(function (x) {
      return x && x.trim().length > 0;
    });
    var seen = {};
    for (var i = 0; i < chatIds.length; i++) {
      var cid = chatIds[i].trim();
      if (seen[cid]) continue;
      seen[cid] = true;
      try {
        UrlFetchApp.fetch("https://api.telegram.org/bot" + botToken + "/sendMessage", {
          method: "post",
          contentType: "application/json",
          payload: JSON.stringify({ chat_id: cid, text: tgMsg }),
          muteHttpExceptions: true,
        });
        sentCount++;
      } catch (tgErr) {
        // 개별 전송 오류 무시
      }
    }
  }

  return {
    ok: true,
    category: category,
    amount: amount,
    detail: detail,
    telegramSent: sentCount,
  };
}

function loadStoreConfigMap_(ss) {
  var cfg = {};
  var ws = ss.getSheetByName("환경설정");
  if (!ws) return cfg;
  var rows = ws.getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    var k = String(rows[i][0] || "").trim();
    var v = String(rows[i][1] || "").trim();
    if (k && v !== "") {
      cfg[k] = v;
    }
  }
  return cfg;
}

function getOrCreatePaymentLogSheet_(ss) {
  var ws = ss.getSheetByName("입금확인로그");
  if (!ws) {
    ws = ss.insertSheet("입금확인로그");
    ws.appendRow(["수신일시", "구분", "입금자_상세", "금액", "원문요약", "확인여부"]);
  } else if (ws.getLastRow() === 0) {
    ws.appendRow(["수신일시", "구분", "입금자_상세", "금액", "원문요약", "확인여부"]);
  }
  return ws;
}

function stripSensitiveBankInfo_(text) {
  var s = String(text || "");
  // 잔액 / 가용잔액 / 거래후잔액 문구 제거
  s = s.replace(/(?:현재|거래후|거래 후|출금가능|가용)?\s*잔액\s*[:：]?\s*-?[\d,]+\s*원?/g, " ");
  // chak 금일누적 결제금액 제거 (직원에게 일 매출 누적액 노출 방지)
  s = s.replace(/(?:금일\s*)?누적\s*결제\s*금액\s*[:：]?\s*[\d,]+\s*원?/g, " ");
  s = s.replace(/금일\s*누적\s*[:：]?\s*[\d,]+\s*원?/g, " ");
  // 계좌번호 형태 제거 (예: 1002-132-672***계좌, 1002-***-123456, ****1234, ***계좌)
  s = s.replace(/\d{3,4}[-*]+[\d*]{2,5}[-*]+[\d*]{2,6}\s*계좌?/g, " ");
  s = s.replace(/\*+\d{2,6}\s*계좌?/g, " ");
  s = s.replace(/\*+\s*계좌?/g, " ");
  s = s.replace(/\s+/g, " ").trim();
  return s;
}

function extractWonAmount_(safeText) {
  // '입금 68,000원', '68,000원', '입금 68,000' 순서로 금액 추출
  var m = safeText.match(/(?:입금|결제|승인|취소)?\s*([\d,]{2,})\s*원/);
  if (!m) {
    m = safeText.match(/(?:입금|결제|승인|취소)\s*[:：]?\s*([\d,]{3,})/);
  }
  if (!m) return 0;
  var num = parseInt(m[1].replace(/,/g, ""), 10);
  return isNaN(num) ? 0 : num;
}

function extractPayerOrDetail_(safeText, category) {
  var s = String(safeText || "");
  s = s.replace(/\[?\s*(?:Web발신|우리은행|우리WON뱅킹|우리WON기업|우리WON|WON뱅킹|지역상품권\s*chak|입출금알림|입출금|알림)\s*\]?/gi, " ");
  s = s.replace(/\[\s*(?:입금|출금)\s*\]/g, " ");
  // 날짜/시간 제거 (2026-11-23, 11/23, 17:14, 18:44:31)
  s = s.replace(/\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b/g, " ");
  s = s.replace(/\b\d{1,2}[./-]\d{1,2}\b/g, " ");
  s = s.replace(/\b\d{1,2}:\d{2}(?::\d{2})?\b/g, " ");
  // 금액 문구 제거
  s = s.replace(/(?:입금|결제|승인|취소)?\s*[\d,]+\s*원/g, " ");
  s = s.replace(/(?:결제완료|결제취소|취소완료|결제가|결제|취소가|취소|안내|완료되었습니다\.?|취소되었습니다\.?|되었습니다\.?)/g, " ");
  s = s.replace(/(^|\s)입금(\s|$)/g, " ");
  s = s.replace(/[()\[\]\/|·:]/g, " ");
  s = s.replace(/\s+/g, " ").trim();

  // 제목+본문 합산으로 중복된 토큰 제거 (예: "분당그릴 분당그릴" -> "분당그릴")
  if (s) {
    var parts = s.split(" ");
    var uniq = [];
    for (var i = 0; i < parts.length; i++) {
      if (parts[i] && uniq.indexOf(parts[i]) === -1) {
        uniq.push(parts[i]);
      }
    }
    s = uniq.join(" ");
  }

  if (!s) {
    if (category === "chak결제") return "지역상품권 결제 완료";
    if (category === "chak취소") return "지역상품권 결제 취소";
    return "입금자 미표기";
  }
  return s.length > 40 ? s.substring(0, 40) : s;
}

function isRecentDuplicate_(ws, nowDate, category, amount, detail, windowSec) {
  var lastRow = ws.getLastRow();
  if (lastRow < 2) return false;
  var startRow = Math.max(2, lastRow - 4);
  var numRows = lastRow - startRow + 1;
  var recent = ws.getRange(startRow, 1, numRows, 4).getValues();

  for (var i = recent.length - 1; i >= 0; i--) {
    var rowTimeStr = String(recent[i][0] || "").trim();
    var rowCat = String(recent[i][1] || "").trim();
    var rowDetail = String(recent[i][2] || "").trim();
    var rowAmt = Number(recent[i][3] || 0);
    if (rowCat !== category || rowAmt !== Number(amount) || rowDetail !== detail) {
      continue;
    }
    var parsedTime = new Date(rowTimeStr.replace(" ", "T") + "+09:00");
    if (!isNaN(parsedTime.getTime())) {
      var diffSec = Math.abs(nowDate.getTime() - parsedTime.getTime()) / 1000;
      if (diffSec <= windowSec) {
        return true;
      }
    }
  }
  return false;
}

function parseHHMMToMinutes_(str) {
  var m = String(str || "").trim().match(/^(\d{1,2}):(\d{2})$/);
  if (!m) return -1;
  var h = parseInt(m[1], 10);
  var min = parseInt(m[2], 10);
  if (isNaN(h) || isNaN(min) || h < 0 || h > 24 || min < 0 || min > 59) return -1;
  if (h === 24 && min === 0) return 1440;
  if (h === 24) return -1;
  return h * 60 + min;
}

function isWithinBusinessHours_(nowDate, startHHMM, endHHMM, currentHHMMOverride) {
  var sMin = parseHHMMToMinutes_(startHHMM);
  var eMin = parseHHMMToMinutes_(endHHMM);
  if (sMin < 0 || eMin < 0) return true;

  var curHHMM = currentHHMMOverride || Utilities.formatDate(nowDate, "Asia/Seoul", "HH:mm");
  var curMin = parseHHMMToMinutes_(curHHMM);
  if (curMin < 0) return true;

  if (sMin <= eMin) {
    // 일반 영업시간 (예: 11:00 ~ 23:00)
    return curMin >= sMin && curMin <= eMin;
  }
  // 자정 넘김 영업시간 (예: 16:00 ~ 02:00)
  return curMin >= sMin || curMin <= eMin;
}

function isExcludedSender_(detail, safeText, excludedRaw) {
  var raw = String(excludedRaw || "").trim();
  if (!raw) return false;
  var names = raw.split(/[,;\n]+/);
  var normDetail = String(detail || "").replace(/\s+/g, "");
  var normSafe = String(safeText || "").replace(/\s+/g, "");

  for (var i = 0; i < names.length; i++) {
    var ex = names[i].replace(/\s+/g, "").trim();
    if (!ex) continue;
    if (normDetail.indexOf(ex) !== -1 || normSafe.indexOf(ex) !== -1) {
      return true;
    }
  }
  return false;
}
