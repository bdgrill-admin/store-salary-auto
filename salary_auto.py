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
# 0. 매장별 설정 및 환경 변수
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
        "db_id": "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8",      # 통합근태DB & 직원목록 시트 ID
        "info_id": "1oLO0aH2UQhiwOfaSPGnxFLmQ8wDqEal3wm7NGSkyUpU",    # 직원인적사항 시트 ID
        "hist_id": get_secret("HIST_SHEET_BUNDANG", ""),              # 분당그릴_급여히스토리 시트 ID
        "sales_id": get_secret("SALES_SHEET_BUNDANG", ""),            # 분당그릴_매출관리 시트 ID
        "tax_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
    },
    # 향후 감동한점 오픈 시 주석(#)을 풀고 시트 ID만 채우면 즉시 활성화됩니다.
    # "감동한점": {
    #     "db_id": "여기에_감동한점_통합근태DB_ID",
    #     "info_id": "여기에_감동한점_직원인적사항_ID",
    #     "hist_id": get_secret("HIST_SHEET_GAMDONG", ""),
    #     "sales_id": get_secret("SALES_SHEET_GAMDONG", ""),
    #     "tax_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
    # },
}

CREDENTIALS_FILE = "credentials.json"

SENDER_EMAIL = get_secret("SENDER_EMAIL", "bdgrill0524@gmail.com")
SENDER_APP_PASSWORD = get_secret("SENDER_APP_PASSWORD", "")
TELEGRAM_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = get_secret("TELEGRAM_CHAT_ID", "")
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "0524")

st.set_page_config(page_title="매장 통합 급여 정산 & 경영 분석", page_icon="🥩", layout="wide")


# =========================================================================
# 커스텀 스타일
# =========================================================================
def apply_clean_style():
    st.markdown(
        """
        <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

        html, body, [class*="css"] {
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
        }

        .block-container {
            padding-top: 2.8rem;
            padding-bottom: 3rem;
            max-width: 1360px;
        }

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

        .section-title {
            font-size: 1.12rem;
            font-weight: 700;
            color: #1E293B;
            margin: 1.3rem 0 0.65rem 0;
            padding-left: 0.6rem;
            border-left: 4px solid #334155;
        }

        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 0.85rem 1rem;
        }
        div[data-testid="stMetric"] label {
            font-size: 0.82rem;
            font-weight: 600;
            color: #475569;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.32rem;
            font-weight: 700;
            color: #0F172A;
        }

        button[data-baseweb="tab"] {
            font-size: 0.98rem;
            font-weight: 600;
            padding: 0.6rem 1.2rem;
        }

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
# 1. 보안 로그인 잠금
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
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(creds)
    except Exception:
        pass

    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def get_settlement_period(base_date: datetime.date):
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


def normalize_ym_label(val: str) -> str:
    s = str(val).strip()
    m = re.match(r"^(?:20)?(\d{2})[-./년\s]+(\d{1,2})월?$", s)
    if m:
        return f"{m.group(1)}.{int(m.group(2)):02d}"
    return s


def parse_sheet_date(val):
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%y-%m-%d", "%Y. %m. %d", "%y.%m.%d"):
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
# 3. 새 통합근태DB + 직원인적사항 연동 데이터 로드 및 근태 집계
# =========================================================================
@st.cache_data(ttl=30, show_spinner="통합근태DB 및 직원 데이터를 불러오는 중...")
def fetch_and_calculate_salary(db_id: str, info_id: str, start_date: datetime.date, end_date: datetime.date):
    gc = get_gspread_client()
    db_ss = gc.open_by_key(db_id)
    info_ss = gc.open_by_key(info_id)

    warnings = []
    attendance_map = {}

    att_ws = db_ss.worksheet("통합근태DB")
    att_rows = att_ws.get_all_values()

    if len(att_rows) >= 2:
        headers = [c.strip() for c in att_rows[0]]
        col_idx = {h: i for i, h in enumerate(headers) if h}

        d_i = col_idx.get("날짜", 0)
        n_i = col_idx.get("이름", 1)
        s_i = col_idx.get("시작시간", 3)
        e_i = col_idx.get("종료시간", 4)
        hm_i = col_idx.get("총시간(h:m)", 5)
        app_i = col_idx.get("매니저확인", 7)

        emp_mins = {}
        emp_dates = {}

        for row_num, r in enumerate(att_rows[1:], start=2):
            if len(r) <= max(d_i, n_i, hm_i):
                continue
            raw_d = str(r[d_i]).strip()
            emp_name = str(r[n_i]).strip()
            if not raw_d or not emp_name:
                continue

            d_obj = parse_sheet_date(raw_d)
            if not d_obj:
                warnings.append(f"⚠️ [{emp_name}] {raw_d} (DB {row_num}행): 날짜 형식 오류")
                continue

            if start_date <= d_obj <= end_date:
                hm_val = str(r[hm_i]).strip()
                mins = parse_hhmm_to_minutes(hm_val)
                if mins <= 0:
                    warnings.append(f"⚠️ [{emp_name}] {d_obj.strftime('%m-%d')} (DB {row_num}행): 근무시간 누락/오류 ({hm_val})")
                    continue

                is_checked = str(r[app_i]).strip().upper() == "TRUE" if len(r) > app_i else False
                if not is_checked:
                    s_t = r[s_i].strip() if len(r) > s_i else ""
                    e_t = r[e_i].strip() if len(r) > e_i else ""
                    warnings.append(
                        f"🚨 [{emp_name}] {d_obj.strftime('%m-%d')} ({s_t}~{e_t}, {hm_val}): **매니저 미확인 상태 (급여 집계 제외됨)**"
                    )
                    continue

                emp_mins[emp_name] = emp_mins.get(emp_name, 0) + mins
                emp_dates.setdefault(emp_name, []).append(d_obj.strftime("%m-%d"))

        for emp_name, t_min in emp_mins.items():
            unique_dates = sorted(list(set(emp_dates.get(emp_name, []))))
            attendance_map[emp_name] = {
                "total_min": t_min,
                "total_hhmm": minutes_to_hhmm(t_min),
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

    emp_master_map = {}
    try:
        emp_ws = db_ss.worksheet("직원목록")
        for r in get_records_auto_header(emp_ws):
            nm = str(r.get("이름", "")).strip()
            if nm:
                emp_master_map[nm] = r
    except Exception:
        pass

    part_records = []
    sheet_titles = [s.title.strip() for s in info_ss.worksheets()]
    if "파트타임" in sheet_titles:
        part_ws = info_ss.worksheet("파트타임")
        part_records = get_records_auto_header(part_ws)

    part_list = []
    processed_lookup_names = set()

    for rec in part_records:
        report_name = str(rec.get("이름", "")).strip()
        if not report_name:
            continue

        remark = str(rec.get("비고", "")).strip()
        lookup_name = report_name
        match = re.search(r"\(실근무\)\s*([가-힣a-zA-Z0-9_]+)", remark)
        if match:
            lookup_name = match.group(1).strip()
        elif report_name in emp_master_map:
            m_memo = str(emp_master_map[report_name].get("메모", "")).strip()
            if m_memo and "퇴사" not in m_memo and len(m_memo) <= 5:
                lookup_name = m_memo

        processed_lookup_names.add(lookup_name)
        att = attendance_map.get(lookup_name, {"total_min": 0, "total_hhmm": "00:00", "work_dates": ""})
        if att["total_min"] == 0:
            continue

        m_rec = emp_master_map.get(report_name, {})
        master_wage = clean_int(m_rec.get("시급", 0))
        info_wage = clean_int(rec.get("시급", 0))
        wage = master_wage if master_wage > 0 else info_wage

        # 직원목록 탭의 최신 은행명·계좌번호·이메일·텔레그램ID 우선 반영 (비어있으면 직원인적사항 참조)
        bank_name = str(m_rec.get("은행명", "")).strip() or str(rec.get("은행명", "")).strip()
        acct_num = str(m_rec.get("계좌번호", "")).strip() or str(rec.get("계좌번호", "")).strip()
        tg_id = str(m_rec.get("텔레그램ID", "")).strip() or str(rec.get("텔레그램ID", "")).strip()
        email_addr = str(m_rec.get("이메일", "")).strip() or str(rec.get("이메일", "")).strip()

        gross_pay = int(round(wage * (att["total_min"] / 60.0)))
        rate_float = 0.033 if gross_pay >= 1_000_000 else 0.009
        rate_str = f"{rate_float * 100:g}%"
        net_pay = int(round(gross_pay * (1.0 - rate_float)))

        part_list.append({
            "이름": report_name,
            "주민번호": format_ssn(rec.get("주민번호", "")),
            "은행명": bank_name,
            "계좌번호": acct_num,
            "시급": wage,
            "총시간": att["total_hhmm"],
            "총급여": gross_pay,
            "공제율": rate_str,
            "그외비용": 0,
            "그외비용사유": "",
            "최종급여": net_pay,
            "비고": remark,
            "근무일자": att["work_dates"],
            "텔레그램ID": tg_id,
            "이메일": email_addr,
        })

    for emp_n, att in attendance_map.items():
        if emp_n not in processed_lookup_names and att["total_min"] > 0:
            m_info = emp_master_map.get(emp_n, {})
            wage = clean_int(m_info.get("시급", 0))
            gross_pay = int(round(wage * (att["total_min"] / 60.0)))
            rate_float = 0.033 if gross_pay >= 1_000_000 else 0.009
            net_pay = int(round(gross_pay * (1.0 - rate_float)))
            warnings.append(f"⚠️ [{emp_n}] 사이드바 '직원 관리' 페이지에서 시급/주민번호를 등록해 주세요.")
            part_list.append({
                "이름": emp_n,
                "주민번호": "",
                "은행명": str(m_info.get("은행명", "")).strip(),
                "계좌번호": str(m_info.get("계좌번호", "")).strip(),
                "시급": wage,
                "총시간": att["total_hhmm"],
                "총급여": gross_pay,
                "공제율": f"{rate_float * 100:g}%",
                "그외비용": 0,
                "그외비용사유": "",
                "최종급여": net_pay,
                "비고": "인적사항 미등록",
                "근무일자": att["work_dates"],
                "텔레그램ID": str(m_info.get("텔레그램ID", "")).strip(),
                "이메일": str(m_info.get("이메일", "")).strip(),
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
# 4. 구글 시트 기반 급여 히스토리 + 매출 연동 분석
# =========================================================================
def _parse_grid_values(all_rows: list):
    ins_sum, part_sum = 0, 0
    total_part_mins = 0
    staff_items = []
    mode = None
    col_map = {}

    for r in all_rows:
        vals = [str(v).strip() if v is not None else "" for v in r]
        if "이름" in vals and "계약급여" in vals:
            mode = "정규직"
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

            if mode == "정규직":
                ins_sum += net_val
                gross_val = clean_int(vals[col_map["계약급여"]]) if ("계약급여" in col_map and col_map["계약급여"] < len(vals)) else net_val
                wage_val, mins_val = 0, 0
            else:
                part_sum += net_val
                gross_val = clean_int(vals[col_map["총급여"]]) if ("총급여" in col_map and col_map["총급여"] < len(vals)) else net_val
                wage_val = clean_int(vals[col_map["시급"]]) if ("시급" in col_map and col_map["시급"] < len(vals)) else 0
                mins_val = parse_hhmm_to_minutes(vals[col_map["총시간"]]) if ("총시간" in col_map and col_map["총시간"] < len(vals)) else 0
                total_part_mins += mins_val

            staff_items.append({
                "구분": mode,
                "이름": name_val,
                "시급": wage_val,
                "근무분": mins_val,
                "총급여": gross_val,
                "최종급여": net_val,
            })

    return {
        "regular": ins_sum,
        "part": part_sum,
        "total": ins_sum + part_sum,
        "part_mins": total_part_mins,
        "staff": staff_items,
    }


def save_history_to_gsheet(hist_id: str, df_ins: pd.DataFrame, df_part: pd.DataFrame, end_date: datetime.date):
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


@st.cache_data(ttl=60, show_spinner="매출 관리 시트에서 월별 매출을 불러오는 중...")
def load_gsheet_sales(sales_id: str) -> pd.DataFrame:
    if not sales_id:
        return pd.DataFrame(columns=["정산월", "총매출"])
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(sales_id)
        titles = [ws.title.strip() for ws in ss.worksheets()]
        ws = ss.worksheet("월별매출") if "월별매출" in titles else ss.worksheets()[0]
        rows = ws.get_all_values()
        if len(rows) < 2:
            return pd.DataFrame(columns=["정산월", "총매출"])

        headers = [c.strip() for c in rows[0]]
        ym_idx = headers.index("정산월") if "정산월" in headers else 0
        sales_idx = headers.index("총매출") if "총매출" in headers else 1

        records = []
        for r in rows[1:]:
            if len(r) <= max(ym_idx, sales_idx):
                continue
            ym = normalize_ym_label(r[ym_idx])
            val = clean_int(r[sales_idx])
            if re.match(r"^\d{2}\.\d{2}$", ym) and val > 0:
                records.append({"정산월": ym, "총매출": val})

        df_sales = pd.DataFrame(records)
        if not df_sales.empty:
            df_sales = df_sales.drop_duplicates(subset=["정산월"], keep="last").sort_values("정산월").reset_index(drop=True)
        return df_sales
    except Exception:
        return pd.DataFrame(columns=["정산월", "총매출"])


@st.cache_data(ttl=60, show_spinner="구글 히스토리 시트에서 누적 추이를 분석하는 중...")
def load_gsheet_history(hist_id: str, sales_id: str = ""):
    if not hist_id:
        return pd.DataFrame(), pd.DataFrame()
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(hist_id)
    except Exception:
        return pd.DataFrame(), pd.DataFrame()

    monthly_map = {}
    staff_rows = []
    sheet_titles = [ws.title.strip() for ws in ss.worksheets()]

    if "과거요약" in sheet_titles:
        ws_past = ss.worksheet("과거요약")
        p_rows = ws_past.get_all_values()
        for r in p_rows[1:]:
            if len(r) < 2:
                continue
            ym = normalize_ym_label(r[0])
            tot_val = clean_int(r[1])
            if re.match(r"^\d{2}\.\d{2}$", ym) and tot_val > 0:
                monthly_map[ym] = {
                    "정산월": ym,
                    "정규직": 0,
                    "파트타임": 0,
                    "총인건비": tot_val,
                    "파트근무분": 0,
                }

    for ws in ss.worksheets():
        sname = normalize_ym_label(ws.title.strip())
        if not re.match(r"^\d{2}\.\d{2}$", sname):
            continue
        parsed = _parse_grid_values(ws.get_all_values())
        if parsed["total"] > 0:
            monthly_map[sname] = {
                "정산월": sname,
                "정규직": parsed["regular"],
                "파트타임": parsed["part"],
                "총인건비": parsed["total"],
                "파트근무분": parsed["part_mins"],
            }
            for item in parsed["staff"]:
                staff_rows.append({"정산월": sname, **item})

    df_m = pd.DataFrame(list(monthly_map.values()))
    if not df_m.empty:
        df_m = df_m.sort_values("정산월").reset_index(drop=True)

        df_sales = load_gsheet_sales(sales_id)
        if not df_sales.empty:
            df_m = pd.merge(df_m, df_sales, on="정산월", how="left")
            df_m["총매출"] = df_m["총매출"].fillna(0).astype(int)
        else:
            df_m["총매출"] = 0

        df_m["인건비율(%)"] = df_m.apply(
            lambda r: round((r["총인건비"] / r["총매출"] * 100), 1) if r["총매출"] > 0 else 0.0, axis=1
        )
        df_m["고정급비율(%)"] = df_m.apply(
            lambda r: round((r["정규직"] / r["총매출"] * 100), 1) if (r["총매출"] > 0 and r["정규직"] > 0) else 0.0, axis=1
        )
        df_m["변동급비율(%)"] = df_m.apply(
            lambda r: round((r["파트타임"] / r["총매출"] * 100), 1) if (r["총매출"] > 0 and r["파트타임"] > 0) else 0.0, axis=1
        )
        df_m["시간당매출(SPLH)"] = df_m.apply(
            lambda r: int(round(r["총매출"] / (r["파트근무분"] / 60.0))) if (r["총매출"] > 0 and r["파트근무분"] > 0) else 0,
            axis=1,
        )

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
# 6. Streamlit 메인 대시보드 UI
# =========================================================================
head_c1, head_c2 = st.columns([3.2, 1], vertical_alignment="center")
with head_c1:
    st.markdown(
        """
        <div class="app-header">
            <div class="app-title">🥩 매장 통합 급여 정산 & 경영 분석</div>
            <div class="app-subtitle">통합근태DB 실시간 연동 · 매출 대비 인건비율 · 전년 동월 비교 · 급여명세서 일괄 발송</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with head_c2:
    selected_store = st.selectbox("정산 매장", list(STORES.keys()), index=0)

store_cfg = STORES[selected_store]

tab_calc, tab_trend = st.tabs([
    f"💰 {selected_store} 월별 급여 정산",
    f"📈 {selected_store} 매출 · 인건비 경영 분석",
])

# =========================================================================
# [TAB 1] 월별 급여 정산 (새 통합근태DB 직결)
# =========================================================================
with tab_calc:
    with st.container(border=True):
        ctrl_1, ctrl_2, ctrl_3 = st.columns([1.3, 2.2, 1.1], vertical_alignment="bottom")
        with ctrl_1:
            base_date = st.date_input("정산 기준일 (매월 5일 기준)", value=datetime.date.today())
        start_dt, end_dt = get_settlement_period(base_date)
        with ctrl_2:
            st.markdown(
                f"""
                <div style="background:#F1F5F9; border-radius:8px; padding:0.58rem 0.9rem; font-size:0.93rem; color:#1E293B;">
                    📅 <b>집계 기간:</b> {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')} &nbsp;(매니저 확인 완료 건만 자동 집계)
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
            store_cfg["db_id"], store_cfg["info_id"], start_dt, end_dt
        )

        if warnings:
            st.error(f"🚨 확인이 필요한 근태/인적사항 알림이 **{len(warnings)}건** 있습니다. 정산 확정 전 확인해 주세요.")
            with st.expander(f"상세 내역 보기 ({len(warnings)}건)", expanded=True):
                for w in warnings:
                    st.markdown(f"- {w}")

        st.markdown('<div class="section-title">1. 정규직 직원 급여 내역</div>', unsafe_allow_html=True)
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

        sum_reg = df_ins_edited["최종급여"].apply(clean_int).sum() if not df_ins_edited.empty else 0
        sum_part = df_part_edited["최종급여"].apply(clean_int).sum() if not df_part_edited.empty else 0
        total_payout = sum_reg + sum_part

        df_hist_m, _ = load_gsheet_history(store_cfg["hist_id"], store_cfg["sales_id"])
        df_sales_all = load_gsheet_sales(store_cfg["sales_id"])

        curr_ym = end_dt.strftime("%y.%m")
        prev_ym = (end_dt.replace(day=1) - datetime.timedelta(days=1)).strftime("%y.%m")
        yoy_ym = f"{int(end_dt.strftime('%y')) - 1:02d}.{end_dt.month:02d}"

        prev_row = df_hist_m[df_hist_m["정산월"] == prev_ym] if not df_hist_m.empty else pd.DataFrame()
        yoy_row = df_hist_m[df_hist_m["정산월"] == yoy_ym] if not df_hist_m.empty else pd.DataFrame()

        prev_dt = end_dt.replace(day=1) - datetime.timedelta(days=1)
        prev_yoy_ym = f"{int(prev_dt.strftime('%y')) - 1:02d}.{prev_dt.month:02d}"

        cur_sales_row = df_sales_all[df_sales_all["정산월"] == prev_ym] if not df_sales_all.empty else pd.DataFrame()
        yoy_sales_row = df_sales_all[df_sales_all["정산월"] == prev_yoy_ym] if not df_sales_all.empty else pd.DataFrame()
        cur_sales_val = int(cur_sales_row.iloc[0]["총매출"]) if not cur_sales_row.empty else 0
        yoy_sales_val = int(yoy_sales_row.iloc[0]["총매출"]) if not yoy_sales_row.empty else 0

        st.write("")
        m1, m2, m3, m4, m5 = st.columns(5)

        if not prev_row.empty:
            p_reg = int(prev_row.iloc[0]["정규직"])
            p_part = int(prev_row.iloc[0]["파트타임"])
            p_tot = int(prev_row.iloc[0]["총인건비"])
            if p_reg > 0:
                m1.metric("정규직 실지급 소계(A)", f"{sum_reg:,}원", delta=f"{sum_reg - p_reg:+,}원 (전월 대비)", delta_color="inverse")
            else:
                m1.metric("정규직 실지급 소계(A)", f"{sum_reg:,}원")
            if p_part > 0:
                m2.metric("파트타임 실지급 소계(B)", f"{sum_part:,}원", delta=f"{sum_part - p_part:+,}원 (전월 대비)", delta_color="inverse")
            else:
                m2.metric("파트타임 실지급 소계(B)", f"{sum_part:,}원")
            m3.metric("총 이체 합계(A+B)", f"{total_payout:,}원", delta=f"{total_payout - p_tot:+,}원 (전월 대비)", delta_color="inverse")
        else:
            m1.metric("정규직 실지급 소계(A)", f"{sum_reg:,}원")
            m2.metric("파트타임 실지급 소계(B)", f"{sum_part:,}원")
            m3.metric("총 이체 합계(A+B)", f"{total_payout:,}원")

        if cur_sales_val > 0 and yoy_sales_val > 0:
            diff_sales = cur_sales_val - yoy_sales_val
            pct_sales = diff_sales / yoy_sales_val * 100
            m4.metric(
                f"전년 대비 매출 ({prev_ym})",
                f"{diff_sales:+,}원 ({pct_sales:+.1f}%)",
                delta=f"당월귀속 {cur_sales_val:,}원 / 작년 {yoy_sales_val:,}원",
                delta_color="off",
            )
        elif cur_sales_val > 0:
            m4.metric(
                f"귀속월 매출 ({prev_ym})",
                f"{cur_sales_val:,}원",
                delta=f"작년 {prev_yoy_ym} 매출 데이터 없음",
                delta_color="off",
            )
        elif yoy_sales_val > 0:
            m4.metric(
                f"작년 {prev_yoy_ym} 매출",
                f"{yoy_sales_val:,}원",
                delta=f"올해 {prev_ym} 매출 미입력",
                delta_color="off",
            )
        else:
            m4.metric("전년 대비 매출", "매출 미입력", delta=f"{prev_ym} 매출 시트 확인", delta_color="off")

        if not yoy_row.empty:
            y_tot = int(yoy_row.iloc[0]["총인건비"])
            diff_yoy = total_payout - y_tot
            pct_yoy = (diff_yoy / y_tot * 100) if y_tot > 0 else 0.0
            m5.metric(
                f"전년 대비 인건비 ({curr_ym})",
                f"{diff_yoy:+,}원 ({pct_yoy:+.1f}%)",
                delta=f"작년 {yoy_ym}: {y_tot:,}원",
                delta_color="off",
            )
        else:
            m5.metric("전년 대비 인건비", "데이터 없음", delta=f"작년 {yoy_ym} 기록 없음", delta_color="off")

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
                    st.caption(f"⚠️ 미확인/확인필요 알림 {len(warnings)}건 있음")

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

# =========================================================================
# [TAB 2] 매출 · 인건비 경영 분석
# =========================================================================
with tab_trend:
    df_monthly, df_staff = load_gsheet_history(store_cfg["hist_id"], store_cfg["sales_id"])

    if df_monthly.empty:
        st.info(
            "ℹ️ 구글 히스토리 시트에 `과거요약` 탭 또는 `YY.MM` 탭(`25.12`, `26.01` 등)이 있으면 자동으로 경영 분석 리포트가 표시됩니다."
        )
    else:
        has_sales = (df_monthly["총매출"] > 0).any()
        valid_sales_df = df_monthly[df_monthly["총매출"] > 0]

        avg_total = int(df_monthly["총인건비"].mean())
        detailed_df = df_monthly[(df_monthly["정규직"] > 0) | (df_monthly["파트타임"] > 0)]
        part_ratio = (
            (detailed_df["파트타임"].sum() / detailed_df["총인건비"].sum() * 100)
            if (not detailed_df.empty and detailed_df["총인건비"].sum() > 0)
            else 0.0
        )

        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"월평균 총 인건비 ({len(df_monthly)}개월)", f"{avg_total:,}원")

        if has_sales:
            avg_sales = int(valid_sales_df["총매출"].mean())
            avg_labor_ratio = valid_sales_df["총인건비"].sum() / valid_sales_df["총매출"].sum() * 100
            valid_splh = valid_sales_df[valid_sales_df["시간당매출(SPLH)"] > 0]
            avg_splh = int(valid_splh["시간당매출(SPLH)"].mean()) if not valid_splh.empty else 0

            k2.metric(f"월평균 매출 ({len(valid_sales_df)}개월 기준)", f"{avg_sales:,}원")
            k3.metric(
                "평균 매출 대비 인건비율",
                f"{avg_labor_ratio:.1f}%",
                delta=f"상세집계 변동급 비중 {part_ratio:.1f}%" if part_ratio > 0 else "과거요약 포함",
                delta_color="off",
            )
            k4.metric("파트타임 시간당 매출(SPLH)", f"{avg_splh:,}원/h" if avg_splh > 0 else "상세집계 후 표시")
        else:
            max_row = df_monthly.loc[df_monthly["총인건비"].idxmax()]
            min_row = df_monthly.loc[df_monthly["총인건비"].idxmin()]
            k2.metric(f"최고 지출 월 ({max_row['정산월']})", f"{int(max_row['총인건비']):,}원")
            k3.metric(f"최저 지출 월 ({min_row['정산월']})", f"{int(min_row['총인건비']):,}원")
            k4.metric("파트타임(변동급) 비중", f"{part_ratio:.1f}%" if part_ratio > 0 else "-")

        st.markdown('<div class="section-title">1. 월별 매출 · 인건비 및 인건비율 추이</div>', unsafe_allow_html=True)
        if has_sales:
            ch1, ch2 = st.columns(2)
            with ch1:
                with st.container(border=True):
                    st.caption("📊 월별 총매출 vs 총인건비 추이")
                    st.bar_chart(valid_sales_df.set_index("정산월")[["총매출", "총인건비"]], height=300)
            with ch2:
                with st.container(border=True):
                    st.caption("📉 매출 대비 인건비율 추이 (%)")
                    st.line_chart(valid_sales_df.set_index("정산월")[["인건비율(%)"]], height=300)
        else:
            with st.container(border=True):
                st.bar_chart(df_monthly.set_index("정산월")[["총인건비"]], height=320)

        df_monthly_calc = df_monthly.copy()
        df_monthly_calc["월번호"] = df_monthly_calc["정산월"].str.split(".").str[1]

        yoy_records = []
        for idx, r in df_monthly_calc.iterrows():
            prev_year_ym = f"{int(r['정산월'][:2]) - 1:02d}.{r['월번호']}"
            match_prev_yr = df_monthly_calc[df_monthly_calc["정산월"] == prev_year_ym]
            if not match_prev_yr.empty:
                pr = match_prev_yr.iloc[0]
                diff_labor = int(r["총인건비"] - pr["총인건비"])
                pct_labor = (diff_labor / pr["총인건비"] * 100) if pr["총인건비"] > 0 else 0.0
                diff_sales = int(r["총매출"] - pr["총매출"]) if (r["총매출"] > 0 and pr["총매출"] > 0) else 0
                pct_sales = (diff_sales / pr["총매출"] * 100) if (r["총매출"] > 0 and pr["총매출"] > 0) else 0.0
                diff_ratio = round(r["인건비율(%)"] - pr["인건비율(%)"], 1) if (r["총매출"] > 0 and pr["총매출"] > 0) else 0.0
                yoy_records.append({
                    "비교월": f"{prev_year_ym} → {r['정산월']}",
                    "작년매출": int(pr["총매출"]),
                    "올해매출": int(r["총매출"]),
                    "매출증감률(%)": round(pct_sales, 1),
                    "작년인건비": int(pr["총인건비"]),
                    "올해인건비": int(r["총인건비"]),
                    "인건비증감액": diff_labor,
                    "인건비증감률(%)": round(pct_labor, 1),
                    "인건비율변화(%p)": diff_ratio,
                })

        if yoy_records:
            st.markdown('<div class="section-title">2. 전년 동월 대비(YoY) 매출 · 인건비 증감 현황</div>', unsafe_allow_html=True)
            df_yoy = pd.DataFrame(yoy_records)
            st.dataframe(
                df_yoy,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "작년매출": st.column_config.NumberColumn("작년 매출", format="%,d"),
                    "올해매출": st.column_config.NumberColumn("올해 매출", format="%,d"),
                    "매출증감률(%)": st.column_config.NumberColumn("매출 증감률", format="%+.1f%%"),
                    "작년인건비": st.column_config.NumberColumn("작년 인건비", format="%,d"),
                    "올해인건비": st.column_config.NumberColumn("올해 인건비", format="%,d"),
                    "인건비증감액": st.column_config.NumberColumn("인건비 증감액", format="%+,d"),
                    "인건비증감률(%)": st.column_config.NumberColumn("인건비 증감률", format="%+.1f%%"),
                    "인건비율변화(%p)": st.column_config.NumberColumn("인건비율 변화", format="%+.1f%%p"),
                },
            )

        sec_num = "3" if yoy_records else "2"
        st.markdown(f'<div class="section-title">{sec_num}. 월별 매출 · 인건비 상세 내역</div>', unsafe_allow_html=True)
        df_monthly_disp = df_monthly.copy()
        df_monthly_disp["전월대비인건비증감"] = df_monthly_disp["총인건비"].diff().fillna(0).astype(int)

        if has_sales:
            disp_cols = [
                "정산월", "총매출", "정규직", "파트타임", "총인건비",
                "전월대비인건비증감", "인건비율(%)", "시간당매출(SPLH)"
            ]
        else:
            disp_cols = ["정산월", "정규직", "파트타임", "총인건비", "전월대비인건비증감"]

        st.dataframe(
            df_monthly_disp[disp_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "총매출": st.column_config.NumberColumn("총 매출", format="%,d"),
                "정규직": st.column_config.NumberColumn("정규직(상세)", format="%,d"),
                "파트타임": st.column_config.NumberColumn("파트타임(상세)", format="%,d"),
                "총인건비": st.column_config.NumberColumn("총 인건비", format="%,d"),
                "전월대비인건비증감": st.column_config.NumberColumn("전월 대비 증감", format="%+,d"),
                "인건비율(%)": st.column_config.NumberColumn("인건비율", format="%.1f%%"),
                "시간당매출(SPLH)": st.column_config.NumberColumn("시간당 매출", format="%,d원"),
            },
        )

        if not df_staff.empty:
            sec_staff_num = "4" if yoy_records else "3"
            st.markdown(f'<div class="section-title">{sec_staff_num}. 직원별 누적 근무시간 · 급여 요약 (상세 내역 기준)</div>', unsafe_allow_html=True)

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
