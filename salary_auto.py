import os
import io
import re
import json
import datetime
import smtplib
import requests
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from dotenv import load_dotenv

load_dotenv()

# =========================================================================
# 0. 매장별 설정 및 환경 변수 (매장 추가 시 아래 STORES에 4줄만 복붙하세요!)
# =========================================================================
def get_secret(key: str, default: str = ""):
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


STORES = {
    "분당그릴": {
        "att_id": "1-E43JK8yCMrLSW4t5zSlIeV4ptl2EltfZwDLsQlA88Y",    # 출퇴근기록지 시트 ID
        "info_id": "1oLO0aH2UQhiwOfaSPGnxFLmQ8wDqEal3wm7NGSkyUpU",   # 직원인적사항 시트 ID
        "hist_id": get_secret("HIST_SHEET_BUNDANG", ""),             # 분당그릴_급여히스토리 시트 ID
        "tax_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
    },
    # 향후 감동한점 오픈 시 주석(#)을 풀고 시트 ID만 채우면 즉시 활성화됩니다.
    # "감동한점": {
    #     "att_id": "여기에_감동한점_출퇴근기록지_ID",
    #     "info_id": "여기에_감동한점_직원인적사항_ID",
    #     "hist_id": get_secret("HIST_SHEET_GAMDONG", ""),
    #     "tax_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
    # },
}

CREDENTIALS_FILE = "credentials.json"
EXCLUDE_TABS = ["목록", "퇴사자백업", "서식"]

SENDER_EMAIL = get_secret("SENDER_EMAIL", "bdgrill0524@gmail.com")
SENDER_APP_PASSWORD = get_secret("SENDER_APP_PASSWORD", "")
TELEGRAM_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = get_secret("TELEGRAM_CHAT_ID", "")
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "0524")  # 웹 접속 비밀번호

st.set_page_config(page_title="매장 통합 급여 정산 & 추이 분석", page_icon="🥩", layout="wide")


# =========================================================================
# 커스텀 스타일 (깔끔한 폰트, 카드 그리드, 버튼 높이/여백 정돈)
# =========================================================================
def apply_clean_style():
    st.markdown(
        """
        <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

        html, body, [class*="css"] {
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
        }

        /* 상단 불필요한 공백 축소 및 최대 폭 정돈 */
        .block-container {
            padding-top: 1.8rem;
            padding-bottom: 3rem;
            max-width: 1280px;
        }

        /* 상단 타이틀 헤더 */
        .app-header {
            padding: 0.2rem 0 0.6rem 0;
        }
        .app-title {
            font-size: 1.65rem;
            font-weight: 700;
            color: #1E293B;
            margin: 0;
            letter-spacing: -0.02em;
        }
        .app-subtitle {
            font-size: 0.9rem;
            color: #64748B;
            margin-top: 0.2rem;
        }

        /* 섹션 제목 스타일 */
        .section-title {
            font-size: 1.12rem;
            font-weight: 700;
            color: #1E293B;
            margin: 1.2rem 0 0.6rem 0;
            padding-left: 0.6rem;
            border-left: 4px solid #334155;
        }

        /* KPI 메트릭 카드 정돈 */
        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 1rem 1.2rem;
        }
        div[data-testid="stMetric"] label {
            font-size: 0.88rem;
            font-weight: 600;
            color: #475569;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.55rem;
            font-weight: 700;
            color: #0F172A;
        }

        /* 탭 버튼 가독성 개선 */
        button[data-baseweb="tab"] {
            font-size: 0.98rem;
            font-weight: 600;
            padding: 0.6rem 1.2rem;
        }

        /* 일반/다운로드 버튼 모서리 및 높이 통일 */
        .stButton > button, .stDownloadButton > button {
            border-radius: 8px;
            font-weight: 600;
            min-height: 2.75rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_clean_style()


# =========================================================================
# 1. 보안 로그인 잠금 (중앙 정렬 카드)
# =========================================================================
def check_login():
    if st.session_state.get("authenticated", False):
        return True

    st.write("")
    st.write("")
    _, col_center, _ = st.columns([1.2, 1.3, 1.2])
    with col_center:
        with st.container(border=True):
            st.markdown("#### 🔒 관리자 인증")
            st.caption("매장 급여 정산 시스템에 접속하려면 비밀번호를 입력하세요.")
            pwd = st.text_input("접속 비밀번호", type="password", key="login_pwd", label_visibility="collapsed", placeholder="비밀번호 입력")
            if st.button("로그인", type="primary", use_container_width=True):
                if pwd == ADMIN_PASSWORD:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    return False


if not check_login():
    st.stop()


# =========================================================================
# 2. 구글 API 인증 및 유틸리티 함수
# =========================================================================
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    # 1순위: Streamlit Cloud Secrets의 GCP 서비스 계정 정보
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(creds)
    except Exception:
        pass

    # 2순위: 로컬 credentials.json 파일
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def get_settlement_period(base_date: datetime.date):
    """기준일(예: 11월 5일) 기준 전월 5일 ~ 당월 4일 반환"""
    if base_date.day >= 5:
        end_date = base_date.replace(day=4)
        first_of_this_month = base_date.replace(day=1)
        prev_month_last = first_of_this_month - datetime.timedelta(days=1)
        start_date = prev_month_last.replace(day=5)
    else:
        first_of_this_month = base_date.replace(day=1)
        prev_month_last = first_of_this_month - datetime.timedelta(days=1)
        end_date = prev_month_last.replace(day=4)
        prev_prev_last = prev_month_last.replace(day=1) - datetime.timedelta(days=1)
        start_date = prev_prev_last.replace(day=5)
    return start_date, end_date


def parse_sheet_date(val):
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%y-%m-%d", "%Y-%m-%d", "%Y. %m. %d", "%y.%m.%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_hhmm_to_minutes(val):
    if pd.isna(val) or val is None:
        return 0
    s = str(val).strip()
    if not s or s == "0":
        return 0
    if ":" in s:
        parts = s.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return 0
    m_kor = re.search(r"(?:(\d+)\s*시간)?\s*(?:(\d+)\s*분)?", s)
    if m_kor and (m_kor.group(1) or m_kor.group(2)):
        h = int(m_kor.group(1) or 0)
        m = int(m_kor.group(2) or 0)
        return h * 60 + m
    return 0


def minutes_to_hhmm(total_min: int):
    total_min = int(round(total_min))
    h = total_min // 60
    m = total_min % 60
    return f"{h:02d}:{m:02d}"


def clean_int(val):
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0
    digits = re.sub(r"[^\d.-]", "", str(val))
    try:
        return int(round(float(digits)))
    except ValueError:
        return 0


def parse_rate(val):
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0.0
    s = str(val).strip().replace("%", "")
    try:
        num = float(s)
        return num / 100.0 if num >= 0.5 else num
    except ValueError:
        return 0.0


def format_ssn(ssn_str):
    digits = re.sub(r"\D", "", str(ssn_str).strip())
    if len(digits) == 13:
        return f"{digits[:6]}-{digits[6:]}"
    return str(ssn_str).strip()


# =========================================================================
# 3. 구글 시트 데이터 로드 및 근태 집계
# =========================================================================
@st.cache_data(ttl=60, show_spinner="구글 시트에서 최신 출퇴근 및 직원 데이터를 불러오는 중...")
def fetch_and_calculate_salary(att_id: str, info_id: str, start_date: datetime.date, end_date: datetime.date):
    gc = get_gspread_client()
    att_ss = gc.open_by_key(att_id)
    info_ss = gc.open_by_key(info_id)

    warnings = []
    attendance_map = {}

    for ws in att_ss.worksheets():
        emp_name = ws.title.strip()
        if emp_name in EXCLUDE_TABS:
            continue

        rows = ws.get_all_values()
        if len(rows) < 3:
            continue

        total_min = 0
        valid_dates = []

        for idx, r in enumerate(rows[2:], start=3):
            if len(r) < 4 or not str(r[0]).strip():
                continue

            d_obj = parse_sheet_date(r[0])
            if not d_obj:
                warnings.append(f"⚠️ [{emp_name}] {r[0]} ({idx}행): 날짜 형식 오류")
                continue

            if d_obj.year not in (start_date.year, end_date.year):
                try:
                    adjusted_date = d_obj.replace(year=end_date.year)
                except ValueError:
                    adjusted_date = None
                if not (adjusted_date and start_date <= adjusted_date <= end_date):
                    try:
                        adjusted_date = d_obj.replace(year=start_date.year)
                    except ValueError:
                        adjusted_date = None

                if adjusted_date and start_date <= adjusted_date <= end_date:
                    warnings.append(
                        f"🚨 [{emp_name}] {r[0]} ({idx}행): 연도 오타 의심! ({d_obj.year}년으로 입력됨, 근무시간 {r[3]})"
                    )
                continue

            if start_date <= d_obj <= end_date:
                mins = parse_hhmm_to_minutes(r[3])
                if mins <= 0:
                    warnings.append(f"⚠️ [{emp_name}] {d_obj.strftime('%m-%d')} ({idx}행): 근무시간 누락/오류 ({r[3]})")
                    continue

                is_checked = str(r[4]).strip().upper() == "TRUE" if len(r) > 4 else False
                if not is_checked:
                    warnings.append(f"⚠️ [{emp_name}] {d_obj.strftime('%m-%d')} ({idx}행): 매니저 미승인 ({r[3]})")

                total_min += mins
                valid_dates.append(d_obj.strftime("%m-%d"))

        unique_dates = sorted(list(set(valid_dates)))
        attendance_map[emp_name] = {
            "total_min": total_min,
            "total_hhmm": minutes_to_hhmm(total_min),
            "work_dates": ", ".join(unique_dates),
        }

    def get_records_auto_header(ws):
        all_rows = ws.get_all_values()
        header_idx = 0
        for i, r in enumerate(all_rows[:5]):
            if "이름" in [c.strip() for c in r]:
                header_idx = i
                break
        if len(all_rows) <= header_idx + 1:
            return []
        headers = [c.strip() for c in all_rows[header_idx]]
        records = []
        for r in all_rows[header_idx + 1:]:
            row_dict = {headers[j]: (r[j] if j < len(r) else "") for j in range(len(headers)) if headers[j]}
            records.append(row_dict)
        return records

    part_records = []
    sheet_titles = [s.title.strip() for s in info_ss.worksheets()]
    if "파트타임" in sheet_titles:
        part_ws = info_ss.worksheet("파트타임")
        part_records = get_records_auto_header(part_ws)

    part_list = []
    for rec in part_records:
        report_name = str(rec.get("이름", "")).strip()
        if not report_name:
            continue

        remark = str(rec.get("비고", "")).strip()
        lookup_name = report_name
        match = re.search(r"\(실근무\)\s*([가-힣a-zA-Z0-9_]+)", remark)
        if match:
            lookup_name = match.group(1).strip()
            if lookup_name not in attendance_map:
                warnings.append(f"🚨 [{report_name}] 실근무자 '{lookup_name}' 탭을 출퇴근기록지에서 찾을 수 없습니다.")

        att = attendance_map.get(lookup_name, {"total_min": 0, "total_hhmm": "00:00", "work_dates": ""})
        if att["total_min"] == 0:
            continue

        wage = clean_int(rec.get("시급", 0))
        gross_pay = int(round(wage * (att["total_min"] / 60.0)))
        rate_float = 0.033 if gross_pay >= 1_000_000 else 0.009
        rate_str = f"{rate_float * 100:g}%"
        net_pay = int(round(gross_pay * (1.0 - rate_float)))

        part_list.append({
            "이름": report_name,
            "주민번호": format_ssn(rec.get("주민번호", "")),
            "은행명": str(rec.get("은행명", "")).strip(),
            "계좌번호": str(rec.get("계좌번호", "")).strip(),
            "시급": wage,
            "총시간": att["total_hhmm"],
            "총급여": gross_pay,
            "공제율": rate_str,
            "그외비용": 0,
            "그외비용사유": "",
            "최종급여": net_pay,
            "비고": remark,
            "근무일자": att["work_dates"],
            "텔레그램ID": str(rec.get("텔레그램ID", "")).strip(),
            "이메일": str(rec.get("이메일", "")).strip(),
        })

    ins_list = []
    if "4대보험" in sheet_titles:
        ins_ws = info_ss.worksheet("4대보험")
        ins_records = get_records_auto_header(ins_ws)
        for rec in ins_records:
            name = str(rec.get("이름", "")).strip()
            if not name:
                continue
            ins_list.append({
                "이름": name,
                "주민번호": format_ssn(rec.get("주민번호", "")),
                "은행명": str(rec.get("은행명", "")).strip(),
                "계좌번호": str(rec.get("계좌번호", "")).strip(),
                "계약급여": clean_int(rec.get("계약급여", 0)),
                "그외비용": 0,
                "그외비용사유": "",
                "최종급여": clean_int(rec.get("최종급여", 0)),
                "비고": str(rec.get("비고", "")).strip(),
                "텔레그램ID": str(rec.get("텔레그램ID", "")).strip(),
                "이메일": str(rec.get("이메일", "")).strip(),
            })

    return pd.DataFrame(ins_list), pd.DataFrame(part_list), warnings


# =========================================================================
# 4. 구글 시트 기반 히스토리 저장 / 전월 비교 / 추이 분석
# =========================================================================
def _parse_grid_values(all_rows: list):
    """2차원 리스트(구글 시트 또는 엑셀 탭)에서 4대보험/파트타임 데이터 파싱"""
    ins_sum, part_sum = 0, 0
    staff_items = []
    mode = None
    col_map = {}

    for r in all_rows:
        vals = [str(v).strip() if v is not None else "" for v in r]
        if "이름" in vals and "계약급여" in vals:
            mode = "4대보험"
            col_map = {v: i for i, v in enumerate(vals) if v}
            continue
        elif "이름" in vals and "시급" in vals:
            mode = "파트타임"
            col_map = {v: i for i, v in enumerate(vals) if v}
            continue

        if mode and "이름" in col_map and "최종급여" in col_map:
            name_val = vals[col_map["이름"]] if col_map["이름"] < len(vals) else ""
            if not name_val or name_val in ("소계", "합계", "실지급총계"):
                continue

            net_val = clean_int(vals[col_map["최종급여"]]) if col_map["최종급여"] < len(vals) else 0
            if net_val == 0:
                continue

            if mode == "4대보험":
                ins_sum += net_val
                gross_val = clean_int(vals[col_map["계약급여"]]) if ("계약급여" in col_map and col_map["계약급여"] < len(vals)) else net_val
                wage_val, mins_val = 0, 0
            else:
                part_sum += net_val
                gross_val = clean_int(vals[col_map["총급여"]]) if ("총급여" in col_map and col_map["총급여"] < len(vals)) else net_val
                wage_val = clean_int(vals[col_map["시급"]]) if ("시급" in col_map and col_map["시급"] < len(vals)) else 0
                mins_val = parse_hhmm_to_minutes(vals[col_map["총시간"]]) if ("총시간" in col_map and col_map["총시간"] < len(vals)) else 0

            staff_items.append({
                "구분": mode,
                "이름": name_val,
                "시급": wage_val,
                "근무분": mins_val,
                "총급여": gross_val,
                "최종급여": net_val,
            })

    return {"ins": ins_sum, "part": part_sum, "total": ins_sum + part_sum, "staff": staff_items}


def save_history_to_gsheet(hist_id: str, df_ins: pd.DataFrame, df_part: pd.DataFrame, end_date: datetime.date):
    """구글 시트 히스토리 파일에 'YY.MM' 탭 생성/덮어쓰기 + 다운로드용 엑셀 바이트 반환"""
    sheet_name = end_date.strftime("%y.%m")

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        start_row = 0
        if not df_ins.empty:
            df_ins.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)
            start_row += len(df_ins) + 3
        if not df_part.empty:
            df_part.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)
    excel_bytes = buf.getvalue()

    if not hist_id:
        return "구글 히스토리 시트 ID 미설정 (엑셀 다운로드만 가능)", excel_bytes

    gc = get_gspread_client()
    ss = gc.open_by_key(hist_id)

    grid_rows = []
    if not df_ins.empty:
        grid_rows.append(df_ins.columns.tolist())
        grid_rows.extend(df_ins.fillna("").astype(str).values.tolist())
        grid_rows.append([])
        grid_rows.append([])
    if not df_part.empty:
        grid_rows.append(df_part.columns.tolist())
        grid_rows.extend(df_part.fillna("").astype(str).values.tolist())

    existing_titles = [ws.title.strip() for ws in ss.worksheets()]
    if sheet_name in existing_titles:
        ws = ss.worksheet(sheet_name)
        ws.clear()
    else:
        ws = ss.add_worksheet(title=sheet_name, rows=max(len(grid_rows) + 10, 50), cols=20)

    if grid_rows:
        ws.update(range_name="A1", values=grid_rows)

    return f"구글 시트 탭 [{sheet_name}] 저장 완료", excel_bytes


@st.cache_data(ttl=60, show_spinner="구글 히스토리 시트에서 누적 추이를 분석하는 중...")
def load_gsheet_history(hist_id: str):
    if not hist_id:
        return pd.DataFrame(), pd.DataFrame()
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(hist_id)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    monthly_rows = []
    staff_rows = []

    for ws in ss.worksheets():
        sname = ws.title.strip()
        if not re.match(r"^\d{2}\.\d{2}$", sname):
            continue
        parsed = _parse_grid_values(ws.get_all_values())
        if parsed["total"] > 0:
            monthly_rows.append({
                "정산월": sname,
                "4대보험": parsed["ins"],
                "파트타임": parsed["part"],
                "총인건비": parsed["total"],
            })
            for item in parsed["staff"]:
                staff_rows.append({"정산월": sname, **item})

    df_m = pd.DataFrame(monthly_rows)
    if not df_m.empty:
        df_m = df_m.drop_duplicates(subset=["정산월"], keep="last").sort_values("정산월").reset_index(drop=True)

    df_s = pd.DataFrame(staff_rows)
    if not df_s.empty:
        df_s = df_s.drop_duplicates(subset=["정산월", "구분", "이름"], keep="last").sort_values(["정산월", "구분", "이름"]).reset_index(drop=True)

    return df_m, df_s


# =========================================================================
# 5. 은행 대량이체 / 세무사 양식 / 개별 급여명세서 / 발송 함수
# =========================================================================
def build_bulk_transfer_excel(store_name: str, df_ins: pd.DataFrame, df_part: pd.DataFrame, end_date: datetime.date):
    rows = []
    memo = f"{store_name}{end_date.month}월급여"

    for df_tmp in [df_ins, df_part]:
        if df_tmp.empty:
            continue
        for _, r in df_tmp.iterrows():
            name = str(r.get("이름", "")).strip()
            amount = clean_int(r.get("최종급여", 0))
            if not name or amount <= 0:
                continue
            acct = re.sub(r"[^0-9]", "", str(r.get("계좌번호", "")))
            rows.append({
                "입금은행": str(r.get("은행명", "")).strip(),
                "입금계좌번호": acct,
                "이체금액": amount,
                "받는분통장표기": memo,
                "보내는분통장표기": name,
            })

    df_transfer = pd.DataFrame(rows)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_transfer.to_excel(writer, sheet_name="대량이체", index=False)
    return buf.getvalue()


def build_tax_accountant_text(df_ins: pd.DataFrame, df_part: pd.DataFrame):
    output_lines = []

    if not df_ins.empty:
        for _, row in df_ins.iterrows():
            name = str(row.get("이름", "")).strip()
            if not name:
                continue
            line = (
                f"이름: {name}\n"
                f"주민번호: {format_ssn(row.get('주민번호', ''))}\n"
                f"은행명: {row.get('은행명', '')}\n"
                f"계좌번호: {row.get('계좌번호', '')}\n"
                f"근무일자: \n"
                f"시급: \n"
                f"총시간 :\n"
                f"*총급여: {clean_int(row.get('계약급여', 0)):,}원\n"
                f"*최종급여: {clean_int(row.get('최종급여', 0)):,}원\n"
            )
            output_lines.append(line)

    if not df_part.empty:
        for _, row in df_part.iterrows():
            name = str(row.get("이름", "")).strip()
            if not name:
                continue
            rate_str = str(row.get("공제율", "0%")).strip()
            if not rate_str.endswith("%"):
                rate_str += "%"
            line = (
                f"이름: {name}\n"
                f"주민번호: {format_ssn(row.get('주민번호', ''))}\n"
                f"은행명: {row.get('은행명', '')}\n"
                f"계좌번호: {row.get('계좌번호', '')}\n"
                f"근무일자: {row.get('근무일자', '')}\n"
                f"시급: {clean_int(row.get('시급', 0)):,}원\n"
                f"총시간 : {row.get('총시간', '')}\n"
                f"*총급여: {clean_int(row.get('총급여', 0)):,}원\n"
                f"*최종급여({rate_str} 차감지급액): {clean_int(row.get('최종급여', 0)):,}원\n"
            )
            output_lines.append(line)

    return "\n".join(output_lines)


def build_individual_payslip_text(store_name: str, row: pd.Series, is_part_time: bool, start_dt: datetime.date, end_dt: datetime.date):
    name = str(row.get("이름", "")).strip()
    period_str = f"{start_dt.strftime('%Y.%m.%d')} ~ {end_dt.strftime('%Y.%m.%d')}"
    bank_info = f"{row.get('은행명', '')} {row.get('계좌번호', '')}".strip()

    if is_part_time:
        gross = clean_int(row.get("총급여", 0))
        net = clean_int(row.get("최종급여", 0))
        deduct = gross - net
        rate_str = str(row.get("공제율", "")).strip()
        return (
            f"🥩 [{store_name}] {end_dt.year}년 {end_dt.month}월분 급여명세서\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• 성명: {name} 님\n"
            f"• 정산기간: {period_str}\n"
            f"• 입금계좌: {bank_info}\n"
            f"• 시급: {clean_int(row.get('시급', 0)):,}원\n"
            f"• 총 근무시간: {row.get('총시간', '')}\n"
            f"• 세전 총급여: {gross:,}원\n"
            f"• 세금 공제({rate_str}): -{deduct:,}원\n"
            f"• 실수령액: {net:,}원\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• 근무일자: {row.get('근무일자', '')}\n\n"
            f"이번 달도 {store_name}과 함께해 주셔서 진심으로 감사합니다."
        )
    else:
        contract = clean_int(row.get("계약급여", 0))
        net = clean_int(row.get("최종급여", 0))
        deduct = contract - net
        return (
            f"🥩 [{store_name}] {end_dt.year}년 {end_dt.month}월분 급여명세서\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• 성명: {name} 님\n"
            f"• 정산기간: {period_str}\n"
            f"• 입금계좌: {bank_info}\n"
            f"• 계약급여: {contract:,}원\n"
            f"• 4대보험/세금 공제: -{deduct:,}원\n"
            f"• 실수령액: {net:,}원\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"이번 달도 {store_name}과 함께해 주셔서 진심으로 감사합니다."
        )


def send_email_simple(to_email: str, subject: str, body_text: str, attachment_bytes=None, attachment_name=None):
    if not SENDER_APP_PASSWORD:
        raise ValueError("SENDER_APP_PASSWORD(구글 앱 비밀번호)가 설정되지 않았습니다.")
    if not to_email:
        raise ValueError("수신자 이메일 주소가 비어 있습니다.")

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    if attachment_bytes and attachment_name:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{attachment_name}"')
        msg.attach(part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.send_message(msg)


def send_telegram_to_chat(chat_id: str, message: str):
    if not TELEGRAM_TOKEN or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": str(chat_id).strip(), "text": message}, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


# =========================================================================
# 6. Streamlit 메인 대시보드 UI (깔끔한 그리드 및 버튼 정렬)
# =========================================================================
head_c1, head_c2 = st.columns([3.2, 1], vertical_alignment="center")
with head_c1:
    st.markdown(
        """
        <div class="app-header">
            <div class="app-title">🥩 매장 통합 급여 정산 & 인건비 분석</div>
            <div class="app-subtitle">출퇴근 시트 자동 집계 · 세무사 보고 · 대량이체 · 급여명세서 일괄 발송</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with head_c2:
    selected_store = st.selectbox("정산 매장", list(STORES.keys()), index=0)

store_cfg = STORES[selected_store]

tab_calc, tab_trend = st.tabs([f"💰 {selected_store} 월별 급여 정산", f"📈 {selected_store} 인건비 변동 추이"])

with tab_calc:
    # 상단 정산 컨트롤 바 (기준일 + 대상기간 + 새로고침 버튼 한 줄 정렬)
    with st.container(border=True):
        ctrl_1, ctrl_2, ctrl_3 = st.columns([1.3, 2.2, 1.1], vertical_alignment="bottom")
        with ctrl_1:
            base_date = st.date_input("정산 기준일 (매월 5일 기준)", value=datetime.date.today())
        start_dt, end_dt = get_settlement_period(base_date)
        with ctrl_2:
            st.markdown(
                f"""
                <div style="background:#F1F5F9; border-radius:8px; padding:0.58rem 0.9rem; font-size:0.93rem; color:#1E293B;">
                    📅 <b>집계 기간:</b> {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}
                </div>
                """,
                unsafe_allow_html=True,
            )
        with ctrl_3:
            if st.button("🔄 시트 새로고침", use_container_width=True):
                st.cache_data.clear()
                st.rerun()

    try:
        df_ins_raw, df_part_raw, warnings = fetch_and_calculate_salary(
            store_cfg["att_id"], store_cfg["info_id"], start_dt, end_dt
        )

        # 근태 이상 알림 (있을 때만 깔끔한 박스로 표시)
        if warnings:
            st.error(f"🚨 근태 및 날짜 이상 내역이 **{len(warnings)}건** 발견되었습니다. 정산 확정 전 확인해 주세요.")
            with st.expander(f"이상 내역 상세 보기 ({len(warnings)}건)", expanded=True):
                for w in warnings:
                    st.markdown(f"- {w}")

        # 1. 4대보험 직원 테이블
        st.markdown('<div class="section-title">1. 4대보험 직원 급여 내역</div>', unsafe_allow_html=True)
        if df_ins_raw.empty:
            st.caption("ℹ️ '직원인적사항' 스프레드시트에 '4대보험' 탭을 추가하면 자동으로 불러옵니다.")
            df_ins_edited = pd.DataFrame(
                columns=["이름", "주민번호", "은행명", "계좌번호", "계약급여", "그외비용", "그외비용사유", "최종급여", "비고", "텔레그램ID", "이메일"]
            )
        else:
            df_ins_edited = st.data_editor(
                df_ins_raw,
                num_rows="dynamic",
                use_container_width=True,
                key=f"editor_ins_{selected_store}",
                column_config={
                    "계약급여": st.column_config.NumberColumn("계약급여", format="%,d"),
                    "그외비용": st.column_config.NumberColumn("그외비용", format="%,d"),
                    "최종급여": st.column_config.NumberColumn("최종급여", format="%,d"),
                },
            )
            for idx, row in df_ins_edited.iterrows():
                orig_row = df_ins_raw.loc[idx] if idx in df_ins_raw.index else None
                extra_pay = clean_int(row.get("그외비용", 0))
                if orig_row is not None and clean_int(row.get("계약급여", 0)) == clean_int(orig_row.get("계약급여", 0)):
                    df_ins_edited.at[idx, "계약급여"] = clean_int(row.get("계약급여", 0)) + extra_pay
                if orig_row is not None and clean_int(row.get("최종급여", 0)) == clean_int(orig_row.get("최종급여", 0)):
                    df_ins_edited.at[idx, "최종급여"] = clean_int(row.get("최종급여", 0)) + extra_pay

        # 2. 파트타임 직원 테이블
        st.markdown('<div class="section-title">2. 파트타임 직원 급여 내역</div>', unsafe_allow_html=True)
        df_part_edited = st.data_editor(
            df_part_raw,
            num_rows="dynamic",
            use_container_width=True,
            key=f"editor_part_{selected_store}",
            column_config={
                "시급": st.column_config.NumberColumn("시급", format="%,d"),
                "총급여": st.column_config.NumberColumn("총급여", format="%,d"),
                "그외비용": st.column_config.NumberColumn("그외비용", format="%,d"),
                "최종급여": st.column_config.NumberColumn("최종급여", format="%,d"),
            },
        )

        if not df_part_edited.empty:
            for idx, row in df_part_edited.iterrows():
                orig_row = df_part_raw.loc[idx] if idx in df_part_raw.index else None
                wage = clean_int(row.get("시급", 0))
                mins = parse_hhmm_to_minutes(row.get("총시간", "00:00"))
                extra_pay = clean_int(row.get("그외비용", 0))
                calc_gross = int(round(wage * (mins / 60.0))) + extra_pay

                if orig_row is not None and clean_int(row.get("총급여", 0)) != clean_int(orig_row.get("총급여", 0)):
                    gross_pay = clean_int(row.get("총급여", 0))
                else:
                    gross_pay = calc_gross

                if orig_row is not None and str(row.get("공제율", "")).strip() != str(orig_row.get("공제율", "")).strip():
                    rate_float = parse_rate(row.get("공제율", 0))
                else:
                    rate_float = 0.033 if gross_pay >= 1_000_000 else 0.009

                net_pay = int(round(gross_pay * (1.0 - rate_float)))

                df_part_edited.at[idx, "총급여"] = gross_pay
                df_part_edited.at[idx, "공제율"] = f"{rate_float * 100:g}%"
                df_part_edited.at[idx, "최종급여"] = net_pay

        # 3. 정산 합계 KPI 3열 그리드
        sum_ins = df_ins_edited["최종급여"].apply(clean_int).sum() if not df_ins_edited.empty else 0
        sum_part = df_part_edited["최종급여"].apply(clean_int).sum() if not df_part_edited.empty else 0
        total_payout = sum_ins + sum_part

        df_hist_m, _ = load_gsheet_history(store_cfg["hist_id"])
        prev_ym = (end_dt.replace(day=1) - datetime.timedelta(days=1)).strftime("%y.%m")
        prev_row = df_hist_m[df_hist_m["정산월"] == prev_ym] if not df_hist_m.empty else pd.DataFrame()

        st.write("")
        m1, m2, m3 = st.columns(3)
        if not prev_row.empty:
            p_ins = int(prev_row.iloc[0]["4대보험"])
            p_part = int(prev_row.iloc[0]["파트타임"])
            p_tot = int(prev_row.iloc[0]["총인건비"])
            m1.metric("4대보험 실지급 소계(A)", f"{sum_ins:,}원", delta=f"{sum_ins - p_ins:+,}원 (전월 대비)", delta_color="inverse")
            m2.metric("파트타임 실지급 소계(B)", f"{sum_part:,}원", delta=f"{sum_part - p_part:+,}원 (전월 대비)", delta_color="inverse")
            m3.metric("총 이체 합계(A+B)", f"{total_payout:,}원", delta=f"{total_payout - p_tot:+,}원 (전월 대비)", delta_color="inverse")
        else:
            m1.metric("4대보험 실지급 소계(A)", f"{sum_ins:,}원")
            m2.metric("파트타임 실지급 소계(B)", f"{sum_part:,}원")
            m3.metric("총 이체 합계(A+B)", f"{total_payout:,}원")

        # 4. 세무사 보고 · 다운로드 · 정산 확정 패널 (좌측 입력 / 우측 버튼 그리드)
        st.markdown('<div class="section-title">3. 세무사 전달 및 정산 확정</div>', unsafe_allow_html=True)
        generated_txt = build_tax_accountant_text(df_ins_edited, df_part_edited)

        today_str = datetime.datetime.now().strftime("%Y%m%d")
        txt_filename = f"{selected_store}_급여내역_{today_str}.txt"
        default_subject = f"[{selected_store}] {end_dt.year}년 {end_dt.month}월분 인건비 급여 내역"
        bulk_excel_bytes = build_bulk_transfer_excel(selected_store, df_ins_edited, df_part_edited, end_dt)
        bulk_filename = f"{selected_store}_{end_dt.strftime('%Y%m')}_은행대량이체.xlsx"

        panel_left, panel_right = st.columns([2.2, 1.1])

        with panel_left:
            with st.container(border=True):
                email_subject = st.text_input("이메일 제목", value=default_subject)
                raw_emails = st.text_input(
                    "수신자 이메일 (여러 곳일 경우 쉼표 , 로 구분)",
                    value=store_cfg["tax_email"],
                    placeholder="예: tax@example.com, bdgrill0524@gmail.com",
                )
                edited_txt = st.text_area(
                    "세무사 전달용 본문 및 첨부(.txt) 내용 (발송 전 직접 수정 가능)",
                    value=generated_txt,
                    height=260,
                )

        with panel_right:
            with st.container(border=True):
                st.markdown("**📥 파일 다운로드**")
                st.download_button(
                    label="세무사용 .txt 다운로드",
                    data=edited_txt.encode("utf-8"),
                    file_name=txt_filename,
                    mime="text/plain",
                    use_container_width=True,
                )
                st.download_button(
                    label="은행 대량이체 엑셀 (.xlsx)",
                    data=bulk_excel_bytes,
                    file_name=bulk_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

                st.divider()
                st.markdown("**🚀 일괄 정산 확정**")
                send_to_staff = st.checkbox(
                    "직원 개별 급여명세서 동시 발송 (이메일/텔레그램)",
                    value=True,
                )
                if warnings:
                    st.caption(f"⚠️ 미확인 근태 알림 {len(warnings)}건 있음")

                confirm_clicked = st.button(
                    "정산 확정 및 발송하기",
                    type="primary",
                    use_container_width=True,
                )

        if confirm_clicked:
            recipient_list = [e.strip() for e in re.split(r"[,;\n]+", raw_emails) if e.strip()]
            if not recipient_list:
                st.error("수신자 이메일 주소를 최소 1개 이상 입력해 주세요.")
            else:
                with st.spinner("구글 시트 히스토리 저장, 세무사 보고 및 직원 개별 명세서 발송 중..."):
                    save_msg, _ = save_history_to_gsheet(store_cfg["hist_id"], df_ins_edited, df_part_edited, end_dt)
                    st.cache_data.clear()

                    intro = f"안녕하세요, {selected_store}입니다.\n{email_subject} 전달드립니다.\n\n========================================\n\n"
                    for recipient in recipient_list:
                        send_email_simple(
                            to_email=recipient,
                            subject=email_subject,
                            body_text=intro + edited_txt,
                            attachment_bytes=edited_txt.encode("utf-8"),
                            attachment_name=txt_filename,
                        )

                    staff_sent_logs = []
                    if send_to_staff:
                        for is_part, df_target in [(False, df_ins_edited), (True, df_part_edited)]:
                            if df_target.empty:
                                continue
                            for _, r in df_target.iterrows():
                                emp_name = str(r.get("이름", "")).strip()
                                emp_email = str(r.get("이메일", "")).strip()
                                emp_tg = str(r.get("텔레그램ID", "")).strip()
                                if not emp_email and not emp_tg:
                                    continue

                                slip_text = build_individual_payslip_text(selected_store, r, is_part, start_dt, end_dt)
                                channels = []

                                if emp_email:
                                    try:
                                        send_email_simple(
                                            to_email=emp_email,
                                            subject=f"[{selected_store}] {end_dt.year}년 {end_dt.month}월분 급여명세서 ({emp_name} 님)",
                                            body_text=slip_text,
                                        )
                                        channels.append("이메일")
                                    except Exception as mail_err:
                                        channels.append(f"이메일실패({mail_err})")

                                if emp_tg:
                                    ok = send_telegram_to_chat(emp_tg, slip_text)
                                    channels.append("텔레그램" if ok else "텔레그램실패")

                                if channels:
                                    staff_sent_logs.append(f"{emp_name}({', '.join(channels)})")

                    recipients_str = ", ".join(recipient_list)
                    transfer_lines = [
                        f"✅ {email_subject} 발송 완료",
                        f"• 세무사/지정 수신처({len(recipient_list)}곳): {recipients_str}",
                        f"• 총 이체합계: {total_payout:,}원\n",
                    ]
                    for df_tmp in [df_ins_edited, df_part_edited]:
                        if not df_tmp.empty:
                            for _, r in df_tmp.iterrows():
                                extra_val = clean_int(r.get("그외비용", 0))
                                extra_rsn = str(r.get("그외비용사유", "")).strip()
                                extra_note = f" [그외비용 {extra_val:+,}원: {extra_rsn}]" if extra_val != 0 else ""
                                transfer_lines.append(
                                    f"- {r['이름']} ({r['은행명']} {r['계좌번호']}): {clean_int(r['최종급여']):,}원{extra_note}"
                                )

                    if staff_sent_logs:
                        transfer_lines.append(f"\n📨 직원 개별 명세서 발송: {', '.join(staff_sent_logs)}")

                    send_telegram_to_chat(TELEGRAM_CHAT_ID, "\n".join(transfer_lines))

                msg_done = f"완료되었습니다! ({save_msg}) 및 `{recipients_str}` 발송이 끝났습니다."
                if staff_sent_logs:
                    msg_done += f" (직원 명세서 발송: {', '.join(staff_sent_logs)})"
                st.success(msg_done)

    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")

with tab_trend:
    df_monthly, df_staff = load_gsheet_history(store_cfg["hist_id"])

    if df_monthly.empty:
        st.info(
            "ℹ️ 구글 히스토리 시트에 `YY.MM` 탭(`25.10`, `25.11` 등)이 있으면 자동으로 분석 그래프가 표시됩니다.\n"
            "(기존 엑셀 파일의 탭들을 히스토리 구글 시트로 복사해 두시면 과거 추이까지 바로 연결됩니다.)"
        )
    else:
        avg_total = int(df_monthly["총인건비"].mean())
        max_row = df_monthly.loc[df_monthly["총인건비"].idxmax()]
        min_row = df_monthly.loc[df_monthly["총인건비"].idxmin()]
        part_ratio = (df_monthly["파트타임"].sum() / df_monthly["총인건비"].sum() * 100) if df_monthly["총인건비"].sum() > 0 else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"월평균 총 인건비 ({len(df_monthly)}개월)", f"{avg_total:,}원")
        k2.metric(f"최고 지출 월 ({max_row['정산월']})", f"{int(max_row['총인건비']):,}원")
        k3.metric(f"최저 지출 월 ({min_row['정산월']})", f"{int(min_row['총인건비']):,}원")
        k4.metric("파트타임(변동급) 비중", f"{part_ratio:.1f}%")

        st.markdown('<div class="section-title">1. 월별 인건비 추이 (4대보험 vs 파트타임)</div>', unsafe_allow_html=True)
        with st.container(border=True):
            chart_df = df_monthly.set_index("정산월")[["4대보험", "파트타임"]]
            st.bar_chart(chart_df, height=320)

        df_monthly_disp = df_monthly.copy()
        df_monthly_disp["전월대비증감"] = df_monthly_disp["총인건비"].diff().fillna(0).astype(int)
        st.dataframe(
            df_monthly_disp,
            use_container_width=True,
            hide_index=True,
            column_config={
                "4대보험": st.column_config.NumberColumn("4대보험 실지급", format="%,d"),
                "파트타임": st.column_config.NumberColumn("파트타임 실지급", format="%,d"),
                "총인건비": st.column_config.NumberColumn("총 인건비", format="%,d"),
                "전월대비증감": st.column_config.NumberColumn("전월 대비 증감", format="%+,d"),
            },
        )

        st.markdown('<div class="section-title">2. 직원별 누적 근무시간 · 급여 요약</div>', unsafe_allow_html=True)

        f_col1, _ = st.columns([1, 3])
        with f_col1:
            years = sorted(list(set(["전체"] + [f"20{m[:2]}년" for m in df_staff["정산월"].unique()])))
            sel_year = st.selectbox("조회 연도", years, index=0)

        df_filtered = df_staff.copy()
        if sel_year != "전체":
            yy_prefix = sel_year[2:4] + "."
            df_filtered = df_filtered[df_filtered["정산월"].str.startswith(yy_prefix)]

        if not df_filtered.empty:
            summary_list = []
            for (gubun, emp_name), grp in df_filtered.groupby(["구분", "이름"]):
                months_cnt = grp["정산월"].nunique()
                total_mins = grp["근무분"].sum()
                latest_wage = grp.sort_values("정산월").iloc[-1]["시급"]
                total_gross = grp["총급여"].sum()
                total_net = grp["최종급여"].sum()
                summary_list.append({
                    "구분": gubun,
                    "이름": emp_name,
                    "근무개월수": f"{months_cnt}개월",
                    "최신시급": int(latest_wage),
                    "누적근무시간": minutes_to_hhmm(total_mins) if gubun == "파트타임" else "-",
                    "누적세전급여": int(total_gross),
                    "누적실수령액": int(total_net),
                    "누적원천세": int(total_gross - total_net),
                })

            df_emp_summary = pd.DataFrame(summary_list).sort_values(["구분", "누적실수령액"], ascending=[True, False])
            st.dataframe(
                df_emp_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "최신시급": st.column_config.NumberColumn("최신시급", format="%,d"),
                    "누적세전급여": st.column_config.NumberColumn("누적 세전급여", format="%,d"),
                    "누적실수령액": st.column_config.NumberColumn("누적 실수령액", format="%,d"),
                    "누적원천세": st.column_config.NumberColumn("누적 공제세액", format="%,d"),
                },
            )
