"""
================================================================================
[파일명] contract_utils.py
[역할] 전자 근로계약서 시스템의 백엔드 핵심 유틸리티 모듈
[주요 기능]
  1. 구글 시트('근로계약서', '파트타임', '정규직') 데이터 조회 및 동기화
  2. ReportLab을 이용한 A4 2페이지 표준근로계약서 PDF 생성 (대표자/근로자 서명 합성)
  3. Google Apps Script 웹앱과 통신하여 구글 드라이브 PDF 자동 저장
  4. Google Apps Script 웹앱과 통신하여 근로자 이메일로 계약서 PDF 자동 발송
  5. 서명 완료 시 대표님 텔레그램으로 실시간 알림 전송
================================================================================
"""

import os
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

# ------------------------------------------------------------------------------
# 기본 설정 상수 (통합근태DB 시트 ID, 구글 드라이브 폴더 ID, 대표자 서명 이미지 경로)
# ------------------------------------------------------------------------------
DB_SPREADSHEET_ID = "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8"
CONTRACT_FOLDER_ID = "1I91dAXDQNrW-tZMFJz0v0o7XAXlbxVnn"
OWNER_SIGN_PATH = "owner_sign.png"

# '근로계약서' 탭의 열(Column) 헤더 순서 정의 (A열 ~ AB열, 총 28개 컬럼)
CONTRACT_HEADERS = [
    "계약ID", "계약유형", "직원명", "근로개시일", "근로종료일", "업무내용",
    "근무시작", "근무종료", "휴게시간(분)", "주근무일수", "주휴요일",
    "임금구분", "금액", "상여금", "기타급여", "사회보험",
    "상태", "생성일시", "서명일시",
    "주민번호", "은행명", "계좌번호", "주소", "연락처", "이메일",
    "CCTV동의", "보건증제출일", "드라이브PDF링크"
]


# ------------------------------------------------------------------------------
# [함수 1] PDF 한글 폰트 등록
# - Streamlit Cloud(리눅스 나눔고딕) 및 로컬 PC(윈도우 맑은고딕) 환경 자동 감지
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# [함수 2] 구글 서비스 계정 인증 객체 생성
# - Streamlit Secrets 또는 로컬 credentials.json 파일에서 인증 정보 로드
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# [함수 3] '근로계약서' 워크시트 열기 (없으면 헤더와 함께 자동 생성)
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# [함수 4] 등록된 재직 직원 명부 불러오기 ('파트타임' 및 '정규직' 시트)
# - 각 시트의 서로 다른 컬럼 구조에 맞춰 기본정보를 읽어와 리스트로 반환
# ------------------------------------------------------------------------------
def load_registered_employees(secrets_dict):
    _, ss = get_contract_worksheet(secrets_dict)
    employees = []

    # 1) 파트타임 시트 조회 (A:입사일자, B:이름, C:주민번호, D:은행명, E:계좌번호, F:시급, G:상태, H:메모, I:이메일, J:텔레그램ID)
    try:
        pt_ws = ss.worksheet("파트타임")
        pt_rows = pt_ws.get_all_values()
        for idx, r in enumerate(pt_rows[1:], start=2):
            padded = r + [""] * (10 - len(r))
            name = padded[1].strip()
            status = padded[6].strip()
            if not name or status == "퇴사":
                continue
            raw_pay = padded[5].replace(",", "").strip()
            pay_int = int(float(raw_pay)) if raw_pay.replace(".", "").isdigit() else 12000
            employees.append({
                "구분": "파트타임",
                "임금구분": "시급",
                "직원명": name,
                "근로개시일": padded[0].strip(),
                "주민번호": padded[2].strip(),
                "은행명": padded[3].strip(),
                "계좌번호": padded[4].strip(),
                "금액": pay_int,
                "상태": status or "재직",
                "메모": padded[7].strip(),
                "이메일": padded[8].strip(),
                "텔레그램ID": padded[9].strip(),
                "_row_idx": idx,
            })
    except Exception:
        pass

    # 2) 정규직 시트 조회 (A:이름, B:주민번호, C:은행명, D:계좌번호, E:계약급여, F:최종급여, G:텔레그램ID, H:이메일)
    try:
        ft_ws = ss.worksheet("정규직")
        ft_rows = ft_ws.get_all_values()
        for idx, r in enumerate(ft_rows[1:], start=2):
            padded = r + [""] * (10 - len(r))
            name = padded[0].strip()
            if not name:
                continue
            raw_pay = padded[4].replace(",", "").strip()
            pay_int = int(float(raw_pay)) if raw_pay.replace(".", "").isdigit() else 3000000
            employees.append({
                "구분": "정규직",
                "임금구분": "월급",
                "직원명": name,
                "근로개시일": "",
                "주민번호": padded[1].strip(),
                "은행명": padded[2].strip(),
                "계좌번호": padded[3].strip(),
                "금액": pay_int,
                "상태": "재직",
                "메모": "",
                "텔레그램ID": padded[6].strip(),
                "이메일": padded[7].strip(),
                "_row_idx": idx,
            })
    except Exception:
        pass

    return employees


# ------------------------------------------------------------------------------
# [함수 5] 전체 근로계약서 발급 내역 불러오기
# ------------------------------------------------------------------------------
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
        item["_row_idx"] = idx  # 추후 서명 완료 시 해당 행만 정확히 업데이트하기 위한 행 번호 저장
        result.append(item)
    return result


# ------------------------------------------------------------------------------
# [함수 6] 특정 계약ID(URL 파라미터)로 단일 계약서 데이터 조회
# ------------------------------------------------------------------------------
def get_contract_by_id(secrets_dict, contract_id: str):
    contracts = load_all_contracts(secrets_dict)
    for c in contracts:
        if c.get("계약ID", "").strip() == contract_id.strip():
            return c
    return None


# ------------------------------------------------------------------------------
# [함수 7] 신규 근로계약서 생성 ('서명대기' 상태로 시트에 저장 후 계약ID 반환)
# - 선택한 직원의 기존 기본정보(주민번호, 은행명, 계좌번호, 이메일)도 함께 기록하여
#   직원이 링크를 열었을 때 자동으로 입력란이 채워지도록 처리
# ------------------------------------------------------------------------------
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
        "",  # 서명일시 (서명 전이므로 빈칸)
        data.get("주민번호", ""),
        data.get("은행명", ""),
        data.get("계좌번호", ""),
        data.get("주소", ""),
        data.get("연락처", ""),
        data.get("이메일", ""),
        "", "", ""  # CCTV동의, 보건증제출일, 드라이브PDF링크
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return cid


# ------------------------------------------------------------------------------
# [함수 8] PDF 긴 문장 자동 줄바꿈(Word-Wrap) 출력 보조 함수
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# [함수 9] 표준근로계약서 A4 2페이지 PDF 생성
# - 1페이지: 외곽 테두리, 제목 박스, 제1조 ~ 제12조
# - 2페이지: 외곽 테두리, 제13조 ~ 제17조, 계약일자, 사업주/근로자 인적사항 및 서명 이미지 합성
# ------------------------------------------------------------------------------
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

    # === [1페이지 그리기] ===
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

    # === [2페이지 그리기] ===
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

    # 사업주 정보 및 대표자 서명 이미지(owner_sign.png) 날인
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

    # 근로자 정보 및 직원 서명 이미지 날인
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


# ------------------------------------------------------------------------------
# [함수 10] 구글 드라이브에 PDF 파일 업로드 (Apps Script 웹앱 연동)
# - 서비스 계정의 용량 제한(Quota) 문제를 우회하기 위해 대표님 드라이브 권한의 웹앱 사용
# ------------------------------------------------------------------------------
def upload_pdf_to_drive(secrets_dict, filename: str, pdf_bytes: bytes) -> str:
    webapp_url = secrets_dict.get("DRIVE_UPLOAD_WEBAPP_URL", "").strip()
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


# ------------------------------------------------------------------------------
# [함수 11] 직원 이메일로 계약서 PDF 사본 자동 발송 (Apps Script 웹앱 연동)
# - Streamlit 서버의 SMTP 포트 차단 문제를 우회하여 GmailApp으로 안정적 발송
# ------------------------------------------------------------------------------
def send_contract_email(secrets_dict, to_email: str, emp_name: str, filename: str, pdf_bytes: bytes):
    if not to_email or "@" not in to_email:
        return False, "이메일 주소 없음"

    webapp_url = secrets_dict.get("DRIVE_UPLOAD_WEBAPP_URL", "").strip()
    if not webapp_url:
        return False, "웹앱 URL 미설정"

    payload = {
        "action": "send_email",
        "toEmail": to_email.strip(),
        "subject": f"[분당그릴] {emp_name}님 전자 근로계약서 사본 교부",
        "body": (
            f"안녕하세요, {emp_name}님.\n\n"
            f"분당그릴과 체결하신 표준근로계약서(전자서명 완료본) 사본을 보내드립니다.\n"
            f"첨부된 PDF 파일을 보관해 주시기 바랍니다.\n\n"
            f"감사합니다.\n분당그릴 드림"
        ),
        "filename": filename,
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


# ------------------------------------------------------------------------------
# [함수 12] 서명 완료 시 직원 명부('파트타임' 또는 '정규직') 시트 동기화
# - 파트타임(10개 컬럼)과 정규직(8개 컬럼)의 서로 다른 열 순서에 맞춰 데이터 밀림 없이 반영
# ------------------------------------------------------------------------------
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

    if merged.get("임금구분") == "월급":
        # 정규직 시트 열 구조: A:이름, B:주민번호, C:은행명, D:계좌번호, E:계약급여, F:최종급여, G:텔레그램ID, H:이메일
        ws = ss.worksheet("정규직")
        rows = ws.get_all_values()
        found_idx = None
        existing = ["", "", "", "", "", "", "", ""]
        for idx, r in enumerate(rows[1:], start=2):
            if r and r[0].strip() == emp_name:
                found_idx = idx
                existing = (r + [""] * 8)[:8]
                break
        final_pay = existing[5] if existing[5] else pay_val
        tele_id = existing[6]
        new_row = [emp_name, rrn, bank, acct, pay_val, final_pay, tele_id, email]
        if found_idx:
            ws.update(f"A{found_idx}:H{found_idx}", [new_row], value_input_option="USER_ENTERED")
        else:
            ws.append_row(new_row, value_input_option="USER_ENTERED")
    else:
        # 파트타임 시트 열 구조: A:입사일자, B:이름, C:주민번호, D:은행명, E:계좌번호, F:시급, G:상태, H:메모, I:이메일, J:텔레그램ID
        ws = ss.worksheet("파트타임")
        rows = ws.get_all_values()
        found_idx = None
        existing = ["", "", "", "", "", "", "재직", "", "", ""]
        for idx, r in enumerate(rows[1:], start=2):
            if len(r) > 1 and r[1].strip() == emp_name:
                found_idx = idx
                existing = (r + [""] * 10)[:10]
                break
        entry_date = existing[0] if existing[0] else s_date
        status = existing[6] if existing[6] else "재직"
        memo = existing[7]
        tele_id = existing[9]
        new_row = [entry_date, emp_name, rrn, bank, acct, pay_val, status, memo, email, tele_id]
        if found_idx:
            ws.update(f"A{found_idx}:J{found_idx}", [new_row], value_input_option="USER_ENTERED")
        else:
            ws.append_row(new_row, value_input_option="USER_ENTERED")


# ------------------------------------------------------------------------------
# [함수 13] 근로자 최종 서명 제출 통합 처리 함수
# - PDF 생성 -> 드라이브 업로드 -> 근로계약서 시트 업데이트 -> 직원 명부 동기화
#   -> 직원 이메일 발송 -> 대표님 텔레그램 알림 발송을 순차 실행
# ------------------------------------------------------------------------------
def complete_employee_signature(secrets_dict, contract: dict, emp_inputs: dict, emp_sign_img: Image.Image):
    ws, ss = get_contract_worksheet(secrets_dict)
    row_idx = contract["_row_idx"]
    sign_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_tag = datetime.datetime.now().strftime("%Y%m%d")

    merged = dict(contract)
    merged.update(emp_inputs)
    merged["상태"] = "서명완료"
    merged["서명일시"] = sign_dt

    # 1) 계약서 PDF 생성
    pdf_bytes = generate_contract_pdf(merged, emp_sign_img)
    emp_name = merged.get("직원명", "직원").strip()
    filename = f"{date_tag}_{emp_name}_근로계약서.pdf"

    # 2) 구글 드라이브에 PDF 업로드
    drive_link = upload_pdf_to_drive(secrets_dict, filename, pdf_bytes)
    merged["드라이브PDF링크"] = drive_link

    # 3) '근로계약서' 탭 해당 행 상태 및 상세정보 업데이트
    updated_row = [merged.get(h, "") for h in CONTRACT_HEADERS]
    ws.update(f"A{row_idx}:AB{row_idx}", [updated_row], value_input_option="USER_ENTERED")

    # 4) '파트타임' 또는 '정규직' 직원 명부 시트 최신 정보 동기화
    try:
        _sync_employee_sheet(ss, merged, emp_inputs)
    except Exception:
        pass

    # 5) 근로자 이메일로 계약서 PDF 발송
    email_ok, email_msg = send_contract_email(
        secrets_dict, emp_inputs.get("이메일", ""), emp_name, filename, pdf_bytes
    )

    # 6) 대표님 텔레그램으로 체결 완료 알림 전송
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
