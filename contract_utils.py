"""
================================================================================
[파일명] contract_utils.py
[역할] 전자 근로계약서 · 비밀유지 서약서 · 연소근로자(만 18세 미만) 친권자 동의서 백엔드 모듈
================================================================================
"""

import os
import re
import json
import io
import base64
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
from PIL import Image

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from store_registry import get_secret

DB_SPREADSHEET_ID = "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8"
CONTRACT_FOLDER_ID = "1I91dAXDQNrW-tZMFJz0v0o7XAXlbxVnn"
OWNER_SIGN_PATH = "owner_sign.png"

CONTRACT_HEADERS = [
    "계약ID", "계약유형", "직원명", "근로개시일", "근로종료일", "업무내용",
    "근무시작", "근무종료", "휴게시간(분)", "주근무일수", "주휴요일",
    "임금구분", "금액", "상여금", "기타급여", "사회보험",
    "상태", "생성일시", "서명일시",
    "주민번호", "은행명", "계좌번호", "주소", "연락처", "이메일",
    "CCTV동의", "보건증제출일", "드라이브PDF링크", "비밀유지서약",
    "연소근로자여부", "친권자성명", "친권자생년월일", "친권자주소", "친권자연락처", "친권자관계"
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

def load_runtime_settings(secrets_dict, ss=None) -> dict:
    """구글 시트 '환경설정' 탭과 Secrets를 통합해 최신 설정값을 반환합니다."""
    cfg = {
        "store_title": "분당그릴",
        "owner_name": "이용석",
        "store_phone": "031-713-0342",
        "store_address": "경기도 성남시 분당구 미금일로 74번길 13-3 1층",
        "default_work_start": "17:00",
        "default_work_end": "22:00",
        "default_break_min": "30",
        "default_job_desc": "홀 서빙 및 주방 보조 등 매장 운영 전반",
        "payroll_start_day": "5",
        "drive_webapp_url": get_secret("DRIVE_UPLOAD_WEBAPP_URL", "").strip(),
        "telegram_bot_token": get_secret("TELEGRAM_BOT_TOKEN", "").strip(),
        "telegram_chat_id": get_secret("TELEGRAM_CHAT_ID", "").strip(),
        "tg_alert_contract": "TRUE",
    }
    try:
        if ss is None:
            creds = get_google_creds(secrets_dict)
            gc = gspread.authorize(creds)
            ss = gc.open_by_key(DB_SPREADSHEET_ID)
        titles = [ws.title.strip() for ws in ss.worksheets()]
        if "환경설정" in titles:
            ws = ss.worksheet("환경설정")
            for r in ws.get_all_values()[1:]:
                if len(r) >= 2 and r[0].strip() and r[1].strip():
                    cfg[r[0].strip()] = r[1].strip()
    except Exception:
        pass
    return cfg


def get_contract_worksheet(secrets_dict):
    creds = get_google_creds(secrets_dict)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(DB_SPREADSHEET_ID)
    try:
        ws = ss.worksheet("근로계약서")
        first_row = ws.row_values(1)
        if len(first_row) < len(CONTRACT_HEADERS):
            ws.update("A1:AI1", [CONTRACT_HEADERS], value_input_option="RAW")
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title="근로계약서", rows=500, cols=len(CONTRACT_HEADERS))
        ws.append_row(CONTRACT_HEADERS, value_input_option="RAW")
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


def delete_contract_by_id(secrets_dict, contract_id: str) -> bool:
    ws, _ = get_contract_worksheet(secrets_dict)
    rows = ws.get_all_values()
    for idx, r in enumerate(rows[1:], start=2):
        if r and str(r[0]).strip() == str(contract_id).strip():
            ws.delete_rows(idx)
            return True
    return False


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
        "",
        data.get("주민번호", ""),
        data.get("은행명", ""),
        data.get("계좌번호", ""),
        data.get("주소", ""),
        data.get("연락처", ""),
        data.get("이메일", ""),
        "",
        "",
        "",
        "Y" if data.get("비밀유지서약") in ("Y", "TRUE", True) else "N",
        "Y" if data.get("연소근로자여부") in ("Y", "TRUE", True) else "N",
        "", "", "", "", ""
    ]
    ws.append_row(row, value_input_option="RAW")
    return cid


def extract_birth_and_age_from_rrn(rrn_str: str, ref_date: datetime.date = None):
    """주민번호 앞자리로 생년월일(YYYY.MM.DD)과 만 나이를 계산합니다."""
    digits = re.sub(r"\D", "", str(rrn_str))
    if len(digits) < 6:
        return "", None
    try:
        yy = int(digits[:2])
        mm = int(digits[2:4])
        dd = int(digits[4:6])
        gender_digit = digits[6] if len(digits) >= 7 else ""
        if gender_digit in ("3", "4", "7", "8"):
            year = 2000 + yy
        elif gender_digit in ("1", "2", "5", "6"):
            year = 1900 + yy
        else:
            year = (2000 + yy) if yy <= 26 else (1900 + yy)
        b_date = datetime.date(year, mm, dd)
        today = ref_date or datetime.date.today()
        age = today.year - b_date.year - ((today.month, today.day) < (b_date.month, b_date.day))
        return f"{year}.{mm:02d}.{dd:02d}", age
    except Exception:
        return "", None


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


def generate_contract_pdf(
    contract: dict,
    emp_sign_img: Image.Image,
    runtime_cfg: dict = None,
    guardian_sign_img: Image.Image = None,
) -> bytes:
    """표준근로계약서(1~2p) + 선택적 친권자 동의서(3p) + 선택적 비밀유지 서약서 합본 PDF 생성"""
    cfg = runtime_cfg or {}
    store_title = cfg.get("store_title", "분당그릴").strip() or "분당그릴"
    spaced_store = " ".join(list(store_title)) if len(store_title) <= 5 else store_title
    owner_name = cfg.get("owner_name", "이용석").strip() or "이용석"
    spaced_owner = "   ".join(list(owner_name)) if len(owner_name) <= 4 else owner_name
    store_phone = cfg.get("store_phone", "031-713-0342").strip() or "031-713-0342"
    store_address = cfg.get("store_address", "경기도 성남시 분당구 미금일로 74번길 13-3 1층").strip()
    pay_day = cfg.get("payroll_start_day", "5").strip() or "5"

    is_minor = str(contract.get("연소근로자여부", "N")).strip().upper() in ("Y", "TRUE", "1")
    include_nda = str(contract.get("비밀유지서약", "N")).strip().upper() in ("Y", "TRUE", "1")
    total_pages = 2 + (1 if is_minor else 0) + (1 if include_nda else 0)

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

    rrn = contract.get("주민번호", "")
    bank = contract.get("은행명", "")
    account = contract.get("계좌번호", "")
    addr = contract.get("주소", "")
    phone = contract.get("연락처", "")
    cctv_agree = contract.get("CCTV동의", "동의함")
    health_date = contract.get("보건증제출일", "")
    sign_dt = contract.get("서명일시", datetime.datetime.now().strftime("%Y-%m-%d"))
    sign_date_parts = sign_dt.split(" ")[0].split("-")
    sy, sm, sd = (sign_date_parts + ["", "", ""])[:3]

    # === 1페이지 ===
    c.setLineWidth(1.2)
    c.rect(36, 36, w - 72, h - 72)

    title = (
        "연소근로자(18세 미만인 자) 표준근로계약서"
        if is_minor
        else f"표준근로계약서({ctype})"
    )
    c.setFont(bold_f, 16 if is_minor else 17)
    tw = c.stringWidth(title, bold_f, 16 if is_minor else 17)
    c.rect((w - tw) / 2 - 18, h - 82, tw + 36, 30)
    c.drawString((w - tw) / 2, h - 73, title)

    y = h - 112
    y = _draw_wrapped(
        c,
        f'{spaced_store} (이하 "사업주"라 함)과(와)  {emp_name} (이하 "근로자"라 함)은 다음과 같이 근로계약을 체결한다.',
        50, y, w - 100, 16.5, bold_f, 10.5
    )
    y -= 8

    if ctype == "기간의 정함이 있는 경우":
        c1 = f"1. 근로계약기간 :  {s_date} 부터    {e_date} 까지"
    else:
        c1 = f"1. 근로개시일 :  {s_date} 부터"

    if is_minor:
        lines_p1 = [
            c1,
            f"2. 근 무 장 소 : {store_address}",
            f"3. 업무의 내용 : {job_desc}",
            f"4. 소정근로시간(변동있음) : {w_start} 부터  {w_end} 까지 (휴게시간 : {break_m}분)",
            f"5. 근무일/휴일 : 매주 {work_days}일(또는 매일단위)근무, 주휴일 매주 {rest_day}요일",
            f"6. 임  금 [입금은행명: {bank}  /  계좌번호: {account}]",
            f"   - {pay_type} :  {pay_amt} 원",
            f"   - 상여금 : {bonus}    /    기타급여(제수당 등) : {other_pay}",
            f"   - 임금지급일 : 매월(매주 또는 매일)  {pay_day} 일(휴일의 경우는 전일 지급)",
            "   - 지급방법 : 근로자 명의 예금통장에 입금( O )",
            "7. 연차유급휴가 : 연차유급휴가는 근로기준법에서 정하는 바에 따라 부여함",
            "8. 가족관계증명서 및 동의서",
            "   - 가족관계기록사항에 관한 증명서 제출 여부 : 제출함( O )",
            "   - 친권자 또는 후견인의 동의서 구비 여부 : 구비함( O ) (별첨 전자동의서 첨부)",
            f"9. 사회보험 적용여부 : [ {insurances} ]",
            "10. 근로계약서 교부 : 사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의 교부 요구와 관계없이 근로자에게 교부함(근로기준법 제17조, 제67조 이행)",
            "11. 위생 관리 및 보건증 제출",
            "   - 근로자는 식품위생법에 따라 입사 시 유효한 보건증(건강진단결과서)을 제출해야 하며, 근무 기간 중 유효기간 만료 전 갱신하여 제출할 의무가 있다.",
            "12. 복무 규율 및 사직 통보",
            "   - 근로자는 부득이한 사정으로 결근·지각·조퇴할 경우 최소 근무 시작 24시간 전에 당사자(업주)에게 사전 승인을 받아야 하며, 사직 시 최소 30일 전에 통보해야 한다.",
        ]
    else:
        lines_p1 = [
            c1,
            f"2. 근 무 장 소 : {store_address}",
            f"3. 업무의 내용 : {job_desc}",
            f"4. 소정근로시간(변동있음) : {w_start} 부터  {w_end} 까지 (휴게시간 : {break_m}분)",
            f"5. 근무일/휴일 : 매주 {work_days}일(또는 매일단위)근무, 주휴일 매주 {rest_day}요일",
            f"6. 임  금 [입금은행명: {bank}  /  계좌번호: {account}]",
            f"   - {pay_type} :  {pay_amt} 원",
            f"   - 상여금 : {bonus}    /    기타급여(제수당 등) : {other_pay}",
            f"   - 임금지급일 : 매월(매주 또는 매일)  {pay_day} 일(휴일의 경우는 휴일 지급)",
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
        y = _draw_wrapped(c, line, 50, y, w - 100, 17, bold_f if is_head else reg_f, 10.1)
        y -= 5.5 if is_head else 2.5

    c.setFont(reg_f, 9)
    c.drawCentredString(w / 2, 46, f"- 1 / {total_pages} -")
    c.showPage()

    # === 2페이지 ===
    c.setLineWidth(1.2)
    c.rect(36, 36, w - 72, h - 72)

    y = h - 68
    clause17_text = (
        "17. 기  타 : 13세 이상 15세 미만인 자에 대해서는 고용노동부장관으로부터 취직인허증을 교부받아야 하며, 이 계약에 정함이 없는 사항은 근로기준법령에 의함"
        if is_minor
        else "17. 기  타 : 이 계약에 정함이 없는 사항은 근로기준법령에 의함"
    )
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
        clause17_text,
    ]

    for line in lines_p2:
        is_head = line[:2].isdigit() and "." in line[:4]
        y = _draw_wrapped(c, line, 50, y, w - 100, 16.8, bold_f if is_head else reg_f, 10.1)
        y -= 4.8 if is_head else 2.5

    y -= 12
    c.setLineWidth(0.6)
    c.line(48, y, w - 48, y)
    y -= 26
    c.setFont(bold_f, 12.5)
    c.drawCentredString(w / 2, y, f"{sy} 년    {sm} 월    {sd} 일")

    y -= 40
    c.setFont(bold_f, 10.5)
    c.drawString(52, y, f"(사업주)  사업체명 :  {spaced_store}        (전화 : {store_phone} )")
    y -= 21
    c.setFont(reg_f, 10)
    c.drawString(102, y, f"주    소 :  {store_address}")
    y -= 23
    c.drawString(102, y, f"대 표 자 :  {spaced_owner}      (서명)")

    if os.path.exists(OWNER_SIGN_PATH):
        try:
            owner_img = Image.open(OWNER_SIGN_PATH).convert("RGBA")
            c.drawImage(ImageReader(owner_img), 255, y - 14, width=68, height=35, mask="auto")
        except Exception:
            pass

    y -= 42
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
    c.drawCentredString(w / 2, 46, f"- 2 / {total_pages} -")

    curr_page = 2

    # === 3페이지 (연소근로자 친권자/후견인 동의서) ===
    if is_minor:
        curr_page += 1
        c.showPage()
        c.setLineWidth(1.2)
        c.rect(36, 36, w - 72, h - 72)

        g_title = "친권자(후견인) 동의서"
        c.setFont(bold_f, 18)
        gtw = c.stringWidth(g_title, bold_f, 18)
        c.rect((w - gtw) / 2 - 22, h - 86, gtw + 44, 34)
        c.drawString((w - gtw) / 2, h - 75, g_title)

        g_name = contract.get("친권자성명", "")
        g_birth = contract.get("친권자생년월일", "")
        g_addr = contract.get("친권자주소", "")
        g_phone = contract.get("친권자연락처", "")
        g_rel = contract.get("친권자관계", "")

        emp_birth, emp_age = extract_birth_and_age_from_rrn(rrn)
        age_str = f"만 {emp_age} 세" if emp_age is not None else "만     세"

        y = h - 132
        c.setFont(bold_f, 11.5)
        c.drawString(56, y, "○ 친권자(후견인) 인적사항")
        y -= 24
        c.setFont(reg_f, 10.8)
        c.drawString(72, y, f"성       명 :  {g_name}")
        y -= 22
        c.drawString(72, y, f"생년월일 :  {g_birth}")
        y -= 22
        y = _draw_wrapped(c, f"주       소 :  {g_addr}", 72, y, w - 120, 18, reg_f, 10.8)
        y -= 4
        c.drawString(72, y, f"연  락  처 :  {g_phone}")
        y -= 22
        c.drawString(72, y, f"연소근로자와의 관계 :  {g_rel}")

        y -= 36
        c.setFont(bold_f, 11.5)
        c.drawString(56, y, "○ 연소근로자 인적사항")
        y -= 24
        c.setFont(reg_f, 10.8)
        c.drawString(72, y, f"성       명 :  {emp_name}          ( {age_str} )")
        y -= 22
        c.drawString(72, y, f"생년월일 :  {emp_birth}")
        y -= 22
        y = _draw_wrapped(c, f"주       소 :  {addr}", 72, y, w - 120, 18, reg_f, 10.8)
        y -= 4
        c.drawString(72, y, f"연  락  처 :  {phone}")

        y -= 36
        c.setFont(bold_f, 11.5)
        c.drawString(56, y, "○ 사업장 개요")
        y -= 24
        c.setFont(reg_f, 10.8)
        c.drawString(72, y, f"회  사  명 :  {store_title}")
        y -= 22
        y = _draw_wrapped(c, f"회사주소 :  {store_address}", 72, y, w - 120, 18, reg_f, 10.8)
        y -= 4
        c.drawString(72, y, f"대  표  자 :  {spaced_owner}")
        y -= 22
        c.drawString(72, y, f"회사전화 :  {store_phone}")

        y -= 44
        c.setFont(bold_f, 11.5)
        c.drawCentredString(w / 2, y, f"본인은 위 연소근로자  {emp_name}  가 위 사업장에서 근로를 하는 것에 대하여 동의합니다.")

        y -= 46
        c.setFont(bold_f, 13)
        c.drawCentredString(w / 2, y, f"{sy} 년    {sm} 월    {sd} 일")

        y -= 46
        c.setFont(bold_f, 11.5)
        c.drawString(245, y, f"친권자(후견인) :   {g_name}      (서명 또는 인)")
        if guardian_sign_img is not None:
            try:
                c.drawImage(ImageReader(guardian_sign_img), 415, y - 14, width=68, height=34, mask="auto")
            except Exception:
                pass

        y -= 48
        c.setFont(reg_f, 10.5)
        c.drawString(56, y, "첨   부 : 가족관계증명서 1부 (별도 제출 및 비치)")

        c.setFont(reg_f, 9)
        c.drawCentredString(w / 2, 46, f"- {curr_page} / {total_pages} -")

    # === 마지막 페이지 (선택적 비밀유지 및 경업금지 서약서) ===
    if include_nda:
        curr_page += 1
        c.showPage()
        c.setLineWidth(1.2)
        c.rect(36, 36, w - 72, h - 72)

        nda_title = "서   약   서 (비밀유지 및 경업금지)"
        c.setFont(bold_f, 18)
        ntw = c.stringWidth(nda_title, bold_f, 18)
        c.drawString((w - ntw) / 2, h - 78, nda_title)

        birth_str, _ = extract_birth_and_age_from_rrn(rrn)

        y = h - 116
        rx = 310
        c.setFont(bold_f, 10.5)
        c.drawString(rx, y, "서약자 (근로자)")
        y -= 18
        c.setFont(reg_f, 10)
        c.drawString(rx + 6, y, f"• 성명: {emp_name}")
        y -= 17
        c.drawString(rx + 6, y, f"• 생년월일: {birth_str}")
        y -= 17
        y = _draw_wrapped(c, f"• 주소: {addr}", rx + 6, y, w - rx - 46, 15, reg_f, 9.5)

        y -= 8
        c.setFont(bold_f, 10.5)
        c.drawString(rx, y, "귀중")
        y -= 18
        c.setFont(reg_f, 10)
        c.drawString(rx + 6, y, f"• 상호명: {store_title}")
        y -= 17
        c.drawString(rx + 6, y, f"• 대표자: {spaced_owner}")

        y -= 28
        y = _draw_wrapped(
            c,
            f"본인은 {store_title}(이하 '당사'라 함)에 채용되어 근무함에 있어, 당사의 영업비밀 및 업무상 알게 된 제반 지식과 정보를 보호하기 위해 아래의 사항을 준수할 것을 엄숙히 서약합니다.",
            50, y, w - 100, 17, reg_f, 10.3,
        )
        y -= 12

        nda_clauses = [
            ("제1조 (비밀유지의 의무)", [
                "1. 본인은 직무 수행 여부를 막론하고 재직 중은 물론 퇴직 후 2년 동안 당사의 사전 서면 승인 없이 다음 각 호에 해당하는 정보를 외부에 유출, 공개, 누설하거나 개인적인 목적으로 사용하지 않는다.",
                "2. 당사 고유의 고기 숙성법, 소스 및 양념(갈비 등) 배합 비율, 조리 레시피 및 주방 운영 매뉴얼 및 당사의 원부재료 매입 원가, 거래처 정보(육류 및 식자재 공급업체 목록) 및 거래 조건, 당사의 매출 정보, 마진율, 주방 내부 설비 및 기기 배치 도면, 기타 당사가 보안을 요청하거나 객관적으로 비밀로 유지되어야 할 영업 및 기술상의 정보",
            ]),
            ("제2조 (정보 및 자료의 반환)", [
                "본인은 퇴직 시 또는 당사의 요청이 있을 때에는 당사의 영업비밀이 포함된 서류, 메모, 데이터(주방 매뉴얼, 조리법 기록 등) 및 관련 물품 일체를 즉시 당사에 반환하며, 어떠한 형태로도 복사본이나 사본을 보유하지 않는다.",
            ]),
            ("제3조 (경업금지 의무)", [
                "본인은 당사의 핵심 기술 및 레시피 보호를 위하여, 퇴직 후 2년 동안 당사의 주요 상권(분당구 및 인근 지역) 내에서 경쟁 관계에 있는 동일 업종(육류 구이 전문점)을 창업하거나, 해당 업체에 취업(동업 포함)하여 당사의 영업비밀을 부당하게 활용하지 않는다.",
            ]),
            ("제4조 (서약 위반 시의 책임)", [
                "본인이 본 서약서의 의무를 위반하여 당사에 손해를 입힌 경우, 본인은 관련 법령(부정경쟁방지 및 영업비밀보호에 관한 법률 등)에 따른 민·형사상의 책임을 전적으로 지며, 당사가 입은 실질적 손해액 전액을 배상할 것을 서약합니다.",
            ]),
        ]

        for head_txt, body_list in nda_clauses:
            c.setFont(bold_f, 10.5)
            c.drawString(50, y, head_txt)
            y -= 18
            for b_txt in body_list:
                y = _draw_wrapped(c, b_txt, 54, y, w - 104, 16.5, reg_f, 10.0)
                y -= 4
            y -= 8

        y -= 14
        c.setFont(bold_f, 13)
        c.drawCentredString(w / 2, y, f"{sy} 년    {sm} 월    {sd} 일")

        y -= 42
        c.setFont(bold_f, 10.5)
        c.drawString(215, y, f"서약자 (근로자) :   {emp_name}        (서명 또는 인)")
        if emp_sign_img is not None:
            try:
                c.drawImage(ImageReader(emp_sign_img), 385, y - 14, width=68, height=34, mask="auto")
            except Exception:
                pass

        y -= 34
        c.drawString(215, y, f"{store_title} 대표 :   {spaced_owner}        (서명 또는 인)")
        if os.path.exists(OWNER_SIGN_PATH):
            try:
                owner_img = Image.open(OWNER_SIGN_PATH).convert("RGBA")
                c.drawImage(ImageReader(owner_img), 385, y - 14, width=68, height=35, mask="auto")
            except Exception:
                pass

        c.setFont(reg_f, 9)
        c.drawCentredString(w / 2, 46, f"- {curr_page} / {total_pages} -")

    c.save()
    return buf.getvalue()


def upload_pdf_to_drive(secrets_dict, filename: str, pdf_bytes: bytes, runtime_cfg: dict = None) -> str:
    cfg = runtime_cfg or load_runtime_settings(secrets_dict)
    webapp_url = cfg.get("drive_webapp_url", "").strip()
    if not webapp_url:
        return ""

    payload = {
        "action": "upload_pdf",
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
            f"Apps Script가 JSON이 아닌 페이지를 반환했습니다 (HTTP {res.status_code})."
        )
    if not res_json.get("ok"):
        raise RuntimeError(f"구글 드라이브 저장 실패: {res_json.get('error')}")
    return res_json.get("url", "")


def send_contract_email(secrets_dict, to_email: str, emp_name: str, filename: str, pdf_bytes: bytes, runtime_cfg: dict = None):
    if not to_email or "@" not in to_email:
        return False, "이메일 주소 없음"

    cfg = runtime_cfg or load_runtime_settings(secrets_dict)
    webapp_url = cfg.get("drive_webapp_url", "").strip()
    store_title = cfg.get("store_title", "분당그릴").strip() or "분당그릴"
    if not webapp_url:
        return False, "웹앱 URL 미설정"

    payload = {
        "action": "send_email",
        "toEmail": to_email.strip(),
        "subject": f"[{store_title}] {emp_name}님 전자 근로계약서 사본 교부",
        "body": (
            f"안녕하세요, {emp_name}님.\n\n"
            f"{store_title}과 체결하신 표준근로계약서(전자서명 완료본) 사본을 보내드립니다.\n"
            f"첨부된 PDF 파일을 보관해 주시기 바랍니다.\n\n"
            f"감사합니다.\n{store_title} 드림"
        ),
        "filename": filename,
        "mimeType": "application/pdf",
        "base64Data": base64.b64encode(pdf_bytes).decode("utf-8"),
    }
    try:
        res = requests.post(
            webapp_url,
            data=json.dumps(payload),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            allow_redirects=True,
            timeout=30,
        )
        res_json = res.json()
        if res_json.get("ok"):
            return True, "발송 완료"
        return False, res_json.get("error", "알 수 없는 오류")
    except Exception as e:
        return False, str(e)


def _sync_employee_sheet(ss, merged: dict, emp_inputs: dict):
    emp_name = merged.get("직원명", "").strip()
    if not emp_name:
        return
    pay_val = int(float(str(merged.get("금액", "0")).replace(",", "") or 0))
    rrn = emp_inputs.get("주민번호", "") or merged.get("주민번호", "")
    bank = emp_inputs.get("은행명", "") or merged.get("은행명", "")
    acct = emp_inputs.get("계좌번호", "") or merged.get("계좌번호", "")
    email = emp_inputs.get("이메일", "") or merged.get("이메일", "")
    s_date = merged.get("근로개시일", "")

    h_sub_str = emp_inputs.get("보건증제출일", "")
    calc_expiry = ""
    if h_sub_str:
        try:
            h_dt = datetime.date.fromisoformat(h_sub_str[:10])
            calc_expiry = (h_dt + datetime.timedelta(days=365)).strftime("%Y-%m-%d")
        except Exception:
            pass

    is_regular = (merged.get("임금구분") == "월급")
    tab_name = "정규직" if is_regular else "파트타임"
    default_headers = (
        ["입사일자", "이름", "주민번호", "은행명", "계좌번호", "계약급여", "제세금", "계산급여", "상태", "메모", "이메일", "텔레그램ID", "보건증만료일"]
        if is_regular
        else ["입사일자", "이름", "주민번호", "은행명", "계좌번호", "시급", "상태", "메모", "이메일", "텔레그램ID", "보건증만료일"]
    )

    ws = ss.worksheet(tab_name)
    rows = ws.get_all_values()
    headers = [c.strip() for c in rows[0]] if rows else default_headers
    if not rows:
        ws.append_row(headers, value_input_option="RAW")

    name_idx = headers.index("이름") if "이름" in headers else (1 if "입사일자" in headers else 0)
    found_idx = None
    existing_dict = {}

    for idx, r in enumerate(rows[1:], start=2):
        if len(r) > name_idx and r[name_idx].strip() == emp_name:
            found_idx = idx
            existing_dict = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
            break

    updated_dict = dict(existing_dict)
    updated_dict["이름"] = emp_name
    updated_dict["주민번호"] = rrn
    updated_dict["은행명"] = bank
    updated_dict["계좌번호"] = acct
    updated_dict["이메일"] = email
    updated_dict["입사일자"] = existing_dict.get("입사일자") or s_date
    updated_dict["상태"] = existing_dict.get("상태") or "재직"
    updated_dict["메모"] = existing_dict.get("메모", "")
    updated_dict["텔레그램ID"] = existing_dict.get("텔레그램ID", "")
    if "보건증만료일" in headers:
        updated_dict["보건증만료일"] = existing_dict.get("보건증만료일") or calc_expiry

    if is_regular:
        updated_dict["계약급여"] = pay_val
        raw_tax = str(existing_dict.get("제세금", "0")).replace(",", "").strip()
        tax_int = int(float(raw_tax)) if raw_tax.replace(".", "").isdigit() else 0
        updated_dict["제세금"] = tax_int
        updated_dict["계산급여"] = max(0, pay_val - tax_int)
        if "최종급여" in headers:
            updated_dict["최종급여"] = max(0, pay_val - tax_int)
    else:
        updated_dict["시급"] = pay_val

    new_row = [updated_dict.get(h, "") for h in headers]
    end_col_letter = chr(ord("A") + len(headers) - 1)

    if found_idx:
        ws.update(f"A{found_idx}:{end_col_letter}{found_idx}", [new_row], value_input_option="RAW")
    else:
        ws.append_row(new_row, value_input_option="RAW")


def complete_employee_signature(
    secrets_dict,
    contract: dict,
    emp_inputs: dict,
    emp_sign_img: Image.Image,
    guardian_sign_img: Image.Image = None,
):
    ws, ss = get_contract_worksheet(secrets_dict)
    runtime_cfg = load_runtime_settings(secrets_dict, ss)

    row_idx = contract["_row_idx"]
    sign_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_tag = datetime.datetime.now().strftime("%Y%m%d")

    merged = dict(contract)
    merged.update(emp_inputs)
    merged["상태"] = "서명완료"
    merged["서명일시"] = sign_dt

    pdf_bytes = generate_contract_pdf(merged, emp_sign_img, runtime_cfg, guardian_sign_img)
    emp_name = merged.get("직원명", "직원").strip()
    is_minor = str(merged.get("연소근로자여부", "N")).strip().upper() in ("Y", "TRUE", "1")
    include_nda = str(merged.get("비밀유지서약", "N")).strip().upper() in ("Y", "TRUE", "1")

    tags = []
    if is_minor:
        tags.append("연소자_친권자동의포함")
    if include_nda:
        tags.append("비밀유지서약포함")
    suffix = f"_{'_'.join(tags)}" if tags else ""
    filename = f"{date_tag}_{emp_name}_근로계약서{suffix}.pdf"

    drive_link = upload_pdf_to_drive(secrets_dict, filename, pdf_bytes, runtime_cfg)
    merged["드라이브PDF링크"] = drive_link

    updated_row = [merged.get(h, "") for h in CONTRACT_HEADERS]
    ws.update(f"A{row_idx}:AI{row_idx}", [updated_row], value_input_option="RAW")

    try:
        _sync_employee_sheet(ss, merged, emp_inputs)
    except Exception:
        pass

    email_ok, email_msg = send_contract_email(
        secrets_dict, emp_inputs.get("이메일", ""), emp_name, filename, pdf_bytes, runtime_cfg
    )

    if runtime_cfg.get("tg_alert_contract", "TRUE").upper() == "TRUE":
        bot_token = runtime_cfg.get("telegram_bot_token", "")
        chat_id = runtime_cfg.get("telegram_chat_id", "")
        store_title = runtime_cfg.get("store_title", "분당그릴")
        extra_info = f" ({', '.join(tags)})" if tags else ""
        if bot_token and chat_id:
            tele_text = (
                f"📝 [{store_title} 전자 근로계약서{extra_info} 서명 완료]\n"
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
