import os
import json
import io
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import requests
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from PIL import Image

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

DB_SPREADSHEET_ID = "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8"
CONTRACT_FOLDER_ID = "1l91dAXDQNrW-tZMFJz0v0o7XAXlbxVnn"
OWNER_SIGN_PATH = "owner_sign.png"

CONTRACT_HEADERS = [
    "계약ID", "계약유형", "직원명", "근로개시일", "근로종료일", "업무내용",
    "근무시작", "근무종료", "휴게시간(분)", "주근무일수", "주휴요일",
    "임금구분", "금액", "상여금", "기타급여", "사회보험",
    "상태", "생성일시", "서명일시",
    "주민번호", "은행명", "계좌번호", "주소", "연락처", "이메일",
    "CCTV동의", "보건증제출일", "드라이브PDF링크"
]


def _register_korean_font():
    candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
    ]
    reg_font = "Helvetica"
    bold_font = "Helvetica-Bold"
    for p in candidates:
        if os.path.exists(p):
            pdfmetrics.registerFont(TTFont("KorFont", p))
            reg_font = "KorFont"
            break
    for p in bold_candidates:
        if os.path.exists(p):
            pdfmetrics.registerFont(TTFont("KorFontBold", p))
            bold_font = "KorFontBold"
            break
    if reg_font == "KorFont" and bold_font == "Helvetica-Bold":
        bold_font = "KorFont"
    return reg_font, bold_font


def get_google_creds(secrets_dict):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if "gcp_service_account" in secrets_dict:
        return Credentials.from_service_account_info(
            dict(secrets_dict["gcp_service_account"]), scopes=scopes
        )
    return Credentials.from_service_account_file("credentials.json", scopes=scopes)


def get_contract_worksheet(secrets_dict):
    creds = get_google_creds(secrets_dict)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(DB_SPREADSHEET_ID)
    try:
        ws = ss.worksheet("근로계약서")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title="근로계약서", rows=500, cols=len(CONTRACT_HEADERS))
        ws.append_row(CONTRACT_HEADERS, value_input_option="USER_ENTERED")
    return ws, ss


def load_all_contracts(secrets_dict):
    ws, _ = get_contract_worksheet(secrets_dict)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return []
    headers = rows[0]
    result = []
    for idx, r in enumerate(rows[1:], start=2):
        padded = r + [""] * (len(headers) - len(r))
        item = dict(zip(headers, padded))
        item["_row_idx"] = idx
        result.append(item)
    return result


def get_contract_by_id(secrets_dict, contract_id: str):
    contracts = load_all_contracts(secrets_dict)
    for c in contracts:
        if c.get("계약ID", "").strip() == contract_id.strip():
            return c
    return None


def create_new_contract(secrets_dict, data: dict) -> str:
    ws, _ = get_contract_worksheet(secrets_dict)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cid = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    row = [
        cid,
        data.get("계약유형", "기간의 정함이 없는 경우"),
        data.get("직원명", ""),
        data.get("근로개시일", ""),
        data.get("근로종료일", ""),
        data.get("업무내용", "홀 서빙 및 주방 보조 등 매장 운영 전반"),
        data.get("근무시작", "17:00"),
        data.get("근무종료", "22:00"),
        str(data.get("휴게시간(분)", 30)),
        str(data.get("주근무일수", 5)),
        data.get("주휴요일", "월"),
        data.get("임금구분", "시급"),
        str(data.get("금액", 12000)),
        data.get("상여금", "없음"),
        data.get("기타급여", "없음"),
        data.get("사회보험", "고용보험, 산재보험"),
        "서명대기",
        now_str,
        "", "", "", "", "", "", "", "", "", ""
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return cid


def _draw_wrapped(c, text, x, y, max_width, line_height, font_name, font_size):
    c.setFont(font_name, font_size)
    words = text.split(" ")
    line = ""
    for w in words:
        test = f"{line} {w}".strip()
        if c.stringWidth(test, font_name, font_size) <= max_width:
            line = test
        else:
            c.drawString(x, y, line)
            y -= line_height
            line = w
    if line:
        c.drawString(x, y, line)
        y -= line_height
    return y


def generate_contract_pdf(contract: dict, emp_sign_img: Image.Image) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    reg_f, bold_f = _register_korean_font()

    ctype = contract.get("계약유형", "기간의 정함이 없는 경우")
    emp_name = contract.get("직원명", "")
    s_date = contract.get("근로개시일", "")
    e_date = contract.get("근로종료일", "")
    job_desc = contract.get("업무내용", "")
    w_start = contract.get("근무시작", "")
    w_end = contract.get("근무종료", "")
    break_m = contract.get("휴게시간(분)", "30")
    work_days = contract.get("주근무일수", "5")
    rest_day = contract.get("주휴요일", "월")
    pay_type = contract.get("임금구분", "시급")
    pay_amt = f"{int(float(str(contract.get('금액', '0')).replace(',', '') or 0)):,}"
    bonus = contract.get("상여금", "없음")
    other_pay = contract.get("기타급여", "없음")
    insurances = contract.get("사회보험", "")

    bank = contract.get("은행명", "")
    account = contract.get("계좌번호", "")
    addr = contract.get("주소", "")
    phone = contract.get("연락처", "")
    cctv_agree = contract.get("CCTV동의", "동의함")
    health_date = contract.get("보건증제출일", "")
    sign_dt = contract.get("서명일시", datetime.datetime.now().strftime("%Y-%m-%d"))
    sign_date_parts = sign_dt.split(" ")[0].split("-")
    sy, sm, sd = (sign_date_parts + ["", "", ""])[:3]

    # --- 1페이지 ---
    c.setLineWidth(1.2)
    c.rect(36, 36, w - 72, h - 72)

    title = f"표준근로계약서({ctype})"
    c.setFont(bold_f, 17)
    tw = c.stringWidth(title, bold_f, 17)
    c.rect((w - tw) / 2 - 18, h - 82, tw + 36, 30)
    c.drawString((w - tw) / 2, h - 73, title)

    y = h - 114
    y = _draw_wrapped(
        c,
        f'분 당 그 릴 (이하 "사업주"라 함)과(와)  {emp_name} (이하 "근로자"라 함)은 다음과 같이 근로계약을 체결한다.',
        50, y, w - 100, 17, bold_f, 10.5
    )
    y -= 10

    if ctype == "기간의 정함이 있는 경우":
        c1 = f"1. 근로계약기간 :  {s_date} 부터    {e_date} 까지"
    else:
        c1 = f"1. 근로개시일 :  {s_date} 부터"

    lines_p1 = [
        c1,
        "2. 근 무 장 소 : 경기도 성남시 분당구 미금일로 74번길 13-3 1층",
        f"3. 업무의 내용 : {job_desc}",
        f"4. 소정근로시간(변동있음) : {w_start} 부터  {w_end} 까지 (휴게시간 : {break_m}분)",
        f"5. 근무일/휴일 : 매주 {work_days}일(또는 매일단위)근무, 주휴일 매주 {rest_day}요일",
        f"6. 임  금 [입금은행명: {bank}  /  계좌번호: {account}]",
        f"   - {pay_type} :  {pay_amt} 원",
        f"   - 상여금 : {bonus}    /    기타급여(제수당 등) : {other_pay}",
        "   - 임금지급일 : 매월(매주 또는 매일)  5 일(휴일의 경우는 휴일 지급)",
        "   - 지급방법 : 근로자 명의 예금통장에 입금( O )",
        "7. 연차유급휴가 : 연차유급휴가는 근로기준법에서 정하는 바에 따라 부여함",
        f"8. 사회보험 적용여부 : [ {insurances} ]",
        "9. 근로계약서 교부 : 사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의 교부 요구와 관계없이 근로자에게 교부함(근로기준법 제17조 이행)",
        "10. 근로계약, 취업규칙 등의 성실한 이행의무 : 사업주와 근로자는 각자가 근로계약, 취업규칙, 단체협약을 지키고 성실하게 이행하여야 함",
        "11. 위생 관리 및 보건증 제출",
        "   - 근로자는 식품위생법에 따라 입사 시 유효한 보건증(건강진단결과서)을 제출해야 하며, 근무 기간 중 유효기간 만료 전 갱신하여 제출할 의무가 있다.",
        "   - 보건증 미제출 또는 위생 관련 법령 위반으로 발생한 불이익에 대해 근로자는 필요한 조치에 적극 협조한다.",
        "12. 복무 규율 및 사직 통보",
        "   - 근로자는 부득이한 사정으로 결근·지각·조퇴할 경우 최소 근무 시작 24시간 전에 당사자(업주)에게 사전 승인을 받아야 한다.",
        "   - 근로자가 사직하고자 할 경우에는 인수인계 및 대체 인력 채용을 위해 최소 30일 전에 사업주에게 서면 또는 메시지로 사직 의사를 통보해야 한다.",
    ]

    for line in lines_p1:
        is_head = line[0].isdigit() and "." in line[:4]
        y = _draw_wrapped(c, line, 50, y, w - 100, 17.5, bold_f if is_head else reg_f, 10.3)
        y -= 6 if is_head else 3

    c.setFont(reg_f, 9)
    c.drawCentredString(w / 2, 46, "- 1 / 2 -")
    c.showPage()

    # --- 2페이지 ---
    c.setLineWidth(1.2)
    c.rect(36, 36, w - 72, h - 72)

    y = h - 68
    lines_p2 = [
        "13. 수습기간",
        "   - 입사 후 3개월(최대 3개월)간은 수습기간으로 정한다.",
        "   - 수습기간 중 근로 태도, 업무 적응도, 위생 수칙 준수 여부 등이 현저히 미달할 경우 근로기준법 제26조, 제27조 및 제35조에 따라 본 계약을 즉시 해지할 수 있다. (단, 근로계약기간이 1년 미만인 경우 수습기간 중이라도 임금을 감액하지 아니하고 100% 지급한다)",
        "14. 비밀유지 의무",
        "   - 근로자는 재직 중은 물론 퇴직 후에도 업무상 알게 된 매장의 영업 비밀, 조리 노하우, 고객 정보 등을 제3자에게 누설하거나 부당하게 활용해서는 안 된다.",
        "15. 비품 반납 및 손해배상",
        "   - 근로자는 퇴사 시 지급받은 유니폼, 명찰, 매장 비품 및 장비를 즉시 반납하여야 한다.",
        "   - 고의 또는 중대한 과실로 매장 시설물이나 기물을 손괴하거나 손실을 입힌 경우 관련 법령에 따라 배상 책임을 질 수 있다.",
        "16. 영상정보(CCTV) 수집 및 이용 동의",
        "   - 수집 목적: 매장 내 시설 안전, 화재 및 도난 범죄 예방, 고객 결제 분쟁 처리",
        "   - 수집 항목: 매장 내 CCTV에 촬영되는 영상정보 (홀, 카운터, 주방 등)",
        "   - 보유 및 이용 기간: 촬영일로부터 30일 (보존기간 경과 시 자동 파기)",
        "   - 동의 거부 안내: 귀하는 영상 수집에 대한 동의를 거부할 권리가 있으나, 매장 보안 및 안전 관리 목적상 채용 또는 근무 수행에 제한이 있을 수 있습니다.",
        f"   ▶ 위 개인영상정보 수집 및 이용에 동의하십니까?   [ {cctv_agree} ]",
        "17. 기  타 : 이 계약에 정함이 없는 사항은 근로기준법령에 의함",
    ]

    for line in lines_p2:
        is_head = line[:2].isdigit() and "." in line[:4]
        y = _draw_wrapped(c, line, 50, y, w - 100, 17, bold_f if is_head else reg_f, 10.2)
        y -= 5 if is_head else 2.5

    # 구분선 및 계약 체결일
    y -= 14
    c.setLineWidth(0.6)
    c.line(48, y, w - 48, y)
    y -= 28
    c.setFont(bold_f, 12.5)
    date_line = f"{sy} 년    {sm} 월    {sd} 일"
    c.drawCentredString(w / 2, y, date_line)

    # 사업주 정보 및 대표자 서명 이미지
    y -= 42
    c.setFont(bold_f, 10.5)
    c.drawString(52, y, "(사업주)  사업체명 :  분 당 그 릴        (전화 : 031-713-0342 )")
    y -= 21
    c.setFont(reg_f, 10)
    c.drawString(102, y, "주    소 :  경기도 성남시 분당구 미금일로 74번길 13-3 1층")
    y -= 23
    c.drawString(102, y, "대 표 자 :  이   용   석      (서명)")

    if os.path.exists(OWNER_SIGN_PATH):
        try:
            owner_img = Image.open(OWNER_SIGN_PATH).convert("RGBA")
            c.drawImage(ImageReader(owner_img), 255, y - 14, width=68, height=35, mask="auto")
        except Exception:
            pass

    # 근로자 정보 및 직원 서명 이미지 (글씨 겹침 방지 배치)
    y -= 44
    c.setFont(bold_f, 10.5)
    c.drawString(52, y, f"(근로자)  주    소 :  {addr}")
    y -= 21
    c.setFont(reg_f, 10)
    c.drawString(102, y, f"연 락 처 :  {phone}            - 근로계약서 배부일 : {sy}.{sm}.{sd}")
    y -= 23
    c.drawString(102, y, f"성    명 :  {emp_name}      (서명)")
    c.drawString(335, y, f"- 보건증 제출일 : {health_date}")

    if emp_sign_img is not None:
        try:
            c.drawImage(ImageReader(emp_sign_img), 232, y - 14, width=68, height=34, mask="auto")
        except Exception:
            pass

    c.setFont(reg_f, 9)
    c.drawCentredString(w / 2, 46, "- 2 / 2 -")
    c.save()
    return buf.getvalue()


def upload_pdf_to_drive(secrets_dict, filename: str, pdf_bytes: bytes) -> str:
    import base64, json
    webapp_url = secrets_dict.get("DRIVE_UPLOAD_WEBAPP_URL", "").strip()
    if not webapp_url:
        return ""

    payload = {
        "folderId": CONTRACT_FOLDER_ID,
        "filename": filename,
        "base64Data": base64.b64encode(pdf_bytes).decode("utf-8"),
    }
    res = requests.post(
        webapp_url,
        data=json.dumps(payload),
        headers={"Content-Type": "text/plain; charset=utf-8"},
        allow_redirects=True,
        timeout=30,
    )
    try:
        res_json = res.json()
    except Exception:
        raise RuntimeError(
            f"Apps Script가 JSON이 아닌 페이지를 반환했습니다 (HTTP {res.status_code}). "
            f"배포 권한을 '모든 사용자'로 설정했는지 확인해 주세요. 응답일부: {res.text[:150]}"
        )
    if not res_json.get("ok"):
        raise RuntimeError(f"구글 드라이브 저장 실패: {res_json.get('error')}")
    return res_json.get("url", "")


def send_contract_email(secrets_dict, to_email: str, emp_name: str, filename: str, pdf_bytes: bytes):
    if not to_email or "@" not in to_email:
        return False, "이메일 주소 없음"
    sender = secrets_dict.get("GMAIL_SENDER", "")
    app_pw = secrets_dict.get("GMAIL_APP_PASSWORD", "")
    if not sender or not app_pw:
        return False, "GMAIL 시크릿 미설정"

    msg = MIMEMultipart()
    msg["Subject"] = f"[분당그릴] {emp_name}님 전자 근로계약서 사본 교부"
    msg["From"] = sender
    msg["To"] = to_email

    body = (
        f"안녕하세요, {emp_name}님.\n\n"
        f"분당그릴과 체결하신 표준근로계약서(전자서명 완료본) 사본을 보내드립니다.\n"
        f"첨부된 PDF 파일을 보관해 주시기 바랍니다.\n\n"
        f"감사합니다.\n분당그릴 드림"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))

    part = MIMEApplication(pdf_bytes, Name=filename)
    part["Content-Disposition"] = f'attachment; filename="{filename}"'
    msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, app_pw)
        server.send_message(msg)
    return True, "발송 완료"


def complete_employee_signature(secrets_dict, contract: dict, emp_inputs: dict, emp_sign_img: Image.Image):
    ws, ss = get_contract_worksheet(secrets_dict)
    row_idx = contract["_row_idx"]
    sign_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_tag = datetime.datetime.now().strftime("%Y%m%d")

    merged = dict(contract)
    merged.update(emp_inputs)
    merged["상태"] = "서명완료"
    merged["서명일시"] = sign_dt

    pdf_bytes = generate_contract_pdf(merged, emp_sign_img)
    emp_name = merged.get("직원명", "직원").strip()
    filename = f"{date_tag}_{emp_name}_근로계약서.pdf"

    drive_link = upload_pdf_to_drive(secrets_dict, filename, pdf_bytes)
    merged["드라이브PDF링크"] = drive_link

    # 시트 업데이트
    updated_row = [merged.get(h, "") for h in CONTRACT_HEADERS]
    ws.update(f"A{row_idx}:AB{row_idx}", [updated_row], value_input_option="USER_ENTERED")

    # 직원 명부(파트타임 / 정규직) 자동 등록 또는 업데이트
    target_tab = "정규직" if merged.get("임금구분") == "월급" else "파트타임"
    try:
        staff_ws = ss.worksheet(target_tab)
        s_rows = staff_ws.get_all_values()
        found_row = None
        for idx, r in enumerate(s_rows[1:], start=2):
            if r and r[0].strip() == emp_name:
                found_row = idx
                break
        pay_val = int(float(str(merged.get("금액", "0")).replace(",", "") or 0))
        new_staff_row = [
            emp_name,
            emp_inputs.get("주민번호", ""),
            emp_inputs.get("은행명", ""),
            emp_inputs.get("계좌번호", ""),
            emp_inputs.get("이메일", ""),
            pay_val,
            "재직",
            merged.get("근로개시일", ""),
            f"전자계약서 완료({date_tag})",
            ""
        ]
        if found_row:
            staff_ws.update(f"A{found_row}:J{found_row}", [new_staff_row], value_input_option="USER_ENTERED")
        else:
            staff_ws.append_row(new_staff_row, value_input_option="USER_ENTERED")
    except Exception:
        pass

    # 이메일 발송
    email_ok, email_msg = send_contract_email(
        secrets_dict, emp_inputs.get("이메일", ""), emp_name, filename, pdf_bytes
    )

    # 대표님 텔레그램 알림
    bot_token = secrets_dict.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = secrets_dict.get("TELEGRAM_CHAT_ID", "")
    if bot_token and chat_id:
        tele_text = (
            f"📝 [전자 근로계약서 서명 완료]\n"
            f"• 직원명: {emp_name} ({merged.get('계약유형')})\n"
            f"• 근무조건: {merged.get('임금구분')} {merged.get('금액')}원 / {merged.get('근로개시일')} 입사\n"
            f"• 이메일 교부: {email_msg}\n"
            f"• 구글 드라이브 저장 완료"
        )
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": tele_text},
                timeout=5,
            )
        except Exception:
            pass

    return pdf_bytes, filename, drive_link, email_ok, email_msg
