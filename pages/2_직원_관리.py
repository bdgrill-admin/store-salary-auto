import os
import re
import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

def get_secret(key: str, default: str = ""):
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


STORES = {
    "분당그릴": {
        "db_id": "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8",
        "manager_pin": get_secret("MANAGER_PIN_BUNDANG", "0524"),
    },
    # 향후 감동한점 오픈 시 주석 해제 후 시트 ID 입력
    # "감동한점": {
    #     "db_id": "여기에_감동한점_통합근태DB_ID",
    #     "manager_pin": get_secret("MANAGER_PIN_GAMDONG", "0524"),
    # },
}

CREDENTIALS_FILE = "credentials.json"
PART_COLS = ["입사일자", "이름", "주민번호", "은행명", "계좌번호", "시급", "상태", "메모", "이메일", "텔레그램ID"]
REG_COLS = ["이름", "주민번호", "은행명", "계좌번호", "계약급여", "최종급여", "텔레그램ID", "이메일"]

# 은행 대량이체 표준 은행명 리스트
BANK_OPTIONS = [
    "KB국민",
    "신한은행",
    "우리은행",
    "하나은행",
    "NH농협",
    "IBK기업은행",
    "카카오뱅크",
    "토스뱅크",
    "케이뱅크",
    "새마을금고",
    "신협",
    "우체국",
    "SC제일은행",
    "부산은행",
    "대구은행(iM뱅크)",
    "광주은행",
    "전북은행",
    "경남은행",
    "수협은행",
]

BANK_ALIAS_MAP = {
    "국민": "KB국민",
    "국민은행": "KB국민",
    "신한": "신한은행",
    "우리": "우리은행",
    "하나": "하나은행",
    "농협": "NH농협",
    "농협은행": "NH농협",
    "기업": "IBK기업은행",
    "기업은행": "IBK기업은행",
    "카카오": "카카오뱅크",
    "토스": "토스뱅크",
    "케이": "케이뱅크",
}

st.set_page_config(page_title="직원 · 시급/계좌 관리", page_icon="👥", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    }
    .block-container {
        padding-top: 3rem;
        padding-bottom: 3rem;
        max-width: 1360px;
    }
    .app-title {
        font-size: 1.55rem;
        font-weight: 700;
        color: #1E293B;
        margin: 0;
    }
    .section-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1E293B;
        margin: 1.1rem 0 0.5rem 0;
        padding-left: 0.6rem;
        border-left: 4px solid #334155;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
        min-height: 2.55rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def clean_int(val):
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0
    digits = re.sub(r"[^\d.-]", "", str(val))
    try:
        return int(round(float(digits)))
    except ValueError:
        return 0


def normalize_bank_name(bank_str: str) -> str:
    b = str(bank_str).strip()
    if not b:
        return ""
    return BANK_ALIAS_MAP.get(b, b)


def format_ssn(ssn_str):
    digits = re.sub(r"\D", "", str(ssn_str).strip())
    if len(digits) == 13:
        return f"{digits[:6]}-{digits[6:]}"
    return str(ssn_str).strip()


@st.cache_data(ttl=25, show_spinner="직원 명부(파트타임 · 정규직)를 불러오는 중...")
def load_staff_tabs(db_id: str):
    gc = get_gspread_client()
    db_ss = gc.open_by_key(db_id)
    titles = [s.title.strip() for s in db_ss.worksheets()]

    def read_tab(tab_name: str, expected_cols: list):
        if tab_name not in titles:
            return pd.DataFrame(columns=expected_cols)
        ws = db_ss.worksheet(tab_name)
        rows = ws.get_all_values()
        out = []
        if len(rows) >= 2:
            headers = [c.strip() for c in rows[0]]
            for r in rows[1:]:
                d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
                if d.get("이름"):
                    out.append(d)
        df = pd.DataFrame(out)
        for col in expected_cols:
            if col not in df.columns:
                df[col] = "재직" if col == "상태" else ""
        if "은행명" in df.columns:
            df["은행명"] = df["은행명"].apply(normalize_bank_name)
        return df[expected_cols].copy()

    df_part = read_tab("파트타임", PART_COLS)
    df_reg = read_tab("정규직", REG_COLS)
    return df_part, df_reg


def save_staff_tabs(db_id: str, df_part_edited: pd.DataFrame, df_reg_edited: pd.DataFrame):
    gc = get_gspread_client()
    db_ss = gc.open_by_key(db_id)

    # 1) '파트타임' 탭 저장
    p_ws = db_ss.worksheet("파트타임")
    for c in PART_COLS:
        if c not in df_part_edited.columns:
            df_part_edited[c] = ""
    clean_p = df_part_edited[PART_COLS].copy()
    clean_p["은행명"] = clean_p["은행명"].apply(normalize_bank_name)
    clean_p["시급"] = clean_p["시급"].apply(lambda x: str(clean_int(x)) if clean_int(x) > 0 else "")
    clean_p["주민번호"] = clean_p["주민번호"].apply(format_ssn)
    clean_p = clean_p.fillna("").astype(str)
    clean_p = clean_p[clean_p["이름"].str.strip() != ""]
    p_ws.clear()
    p_ws.update(range_name="A1", values=[PART_COLS] + clean_p.values.tolist())

    # 2) '정규직' 탭 저장
    r_ws = db_ss.worksheet("정규직")
    for c in REG_COLS:
        if c not in df_reg_edited.columns:
            df_reg_edited[c] = ""
    clean_r = df_reg_edited[REG_COLS].copy()
    clean_r["은행명"] = clean_r["은행명"].apply(normalize_bank_name)
    clean_r["계약급여"] = clean_r["계약급여"].apply(lambda x: str(clean_int(x)) if clean_int(x) > 0 else "")
    clean_r["최종급여"] = clean_r["최종급여"].apply(lambda x: str(clean_int(x)) if clean_int(x) > 0 else "")
    clean_r["주민번호"] = clean_r["주민번호"].apply(format_ssn)
    clean_r = clean_r.fillna("").astype(str)
    clean_r = clean_r[clean_r["이름"].str.strip() != ""]
    r_ws.clear()
    r_ws.update(range_name="A1", values=[REG_COLS] + clean_r.values.tolist())


h1, h2, h3 = st.columns([2.6, 0.9, 0.7], vertical_alignment="center")
with h1:
    st.markdown('<div class="app-title">👥 직원 · 시급/계좌 관리</div>', unsafe_allow_html=True)
with h2:
    selected_store = st.selectbox("매장 선택", list(STORES.keys()), index=0, label_visibility="collapsed")
with h3:
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

store_cfg = STORES[selected_store]

is_unlocked = st.session_state.get("authenticated", False) or st.session_state.get("staff_mgr_unlocked", False)

if not is_unlocked:
    st.write("")
    _, c_mid, _ = st.columns([1.2, 1.3, 1.2])
    with c_mid:
        with st.container(border=True):
            st.markdown("#### 🔐 매니저 / 관리자 전용")
            st.caption("직원 명부 및 시급·계좌 관리를 위해 비밀번호를 입력하세요.")
            pin = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력", label_visibility="collapsed")
            if st.button("확인", type="primary", use_container_width=True):
                if pin == store_cfg["manager_pin"]:
                    st.session_state["staff_mgr_unlocked"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()

st.caption("💡 여기서 신규 직원을 등록하거나 시급·계좌·상태(재직/퇴사)를 수정하면 **출퇴근기록부와 급여 정산기에 즉시 반영**됩니다.")

df_part, df_reg = load_staff_tabs(store_cfg["db_id"])

# =========================================================================
# 신규 파트타임 직원 간편 등록 (은행명 드롭다운 적용)
# =========================================================================
with st.expander("➕ 신규 파트타임 직원 등록하기", expanded=False):
    with st.form("new_part_staff_form", clear_on_submit=True):
        fc1, fc2, fc3, fc4 = st.columns([1.0, 1.1, 1.0, 1.2])
        new_join_date = fc1.date_input("입사일자", value=datetime.date.today())
        new_name = fc2.text_input("이름 (계좌 예금주명)*", placeholder="예: 홍길동")
        new_wage = fc3.number_input("시급 (원)", min_value=0, value=12000, step=100)
        new_ssn = fc4.text_input("주민등록번호", placeholder="예: 000101-3123456")

        fc5, fc6, fc7, fc8 = st.columns([1.0, 1.3, 1.2, 1.0])
        new_bank = fc5.selectbox("은행명", options=BANK_OPTIONS, index=0)
        new_acct = fc6.text_input("계좌번호", placeholder="예: 3333-01-1234567")
        new_email = fc7.text_input("이메일 (명세서 발송용)", placeholder="example@gmail.com")
        new_tg = fc8.text_input("텔레그램 ID (선택)", placeholder="숫자 ID")

        new_memo = st.text_input(
            "메모 / 실근무자 이름 (예금주와 실제 출근자가 다를 때만 실근무자 이름 입력)",
            placeholder="예: 강성원",
        )

        if st.form_submit_button("✅ 신규 파트타임 직원 등록", type="primary", use_container_width=True):
            clean_nm = new_name.strip()
            if not clean_nm:
                st.error("직원 이름을 입력해 주세요.")
            else:
                new_row = pd.DataFrame([{
                    "입사일자": new_join_date.strftime("%Y-%m-%d"),
                    "이름": clean_nm,
                    "주민번호": format_ssn(new_ssn),
                    "은행명": new_bank,
                    "계좌번호": new_acct.strip(),
                    "시급": str(int(new_wage)),
                    "상태": "재직",
                    "메모": new_memo.strip(),
                    "이메일": new_email.strip(),
                    "텔레그램ID": new_tg.strip(),
                }])
                updated_part = pd.concat([df_part, new_row], ignore_index=True)
                save_staff_tabs(store_cfg["db_id"], updated_part, df_reg)
                st.success(f"🎉 [{clean_nm}] 님이 신규 등록되었습니다!")
                st.cache_data.clear()
                st.rerun()

# =========================================================================
# 1. 파트타임 직원 명부 (시급 · 계좌 · 재직/퇴사 · 연락처)
# =========================================================================
st.markdown('<div class="section-title">1. 파트타임 직원 명부 (시급 · 계좌 · 재직/퇴사 관리)</div>', unsafe_allow_html=True)
df_part_disp = df_part.copy()
df_part_disp["시급"] = df_part_disp["시급"].apply(clean_int)

edited_part = st.data_editor(
    df_part_disp,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key=f"part_ed_{selected_store}",
    column_config={
        "입사일자": st.column_config.TextColumn("입사일자"),
        "이름": st.column_config.TextColumn("이름", required=True),
        "주민번호": st.column_config.TextColumn("주민번호"),
        "은행명": st.column_config.SelectboxColumn("은행명", options=BANK_OPTIONS),
        "계좌번호": st.column_config.TextColumn("계좌번호"),
        "시급": st.column_config.NumberColumn("시급 (원)", format="%,d"),
        "상태": st.column_config.SelectboxColumn("상태 (퇴사 시 출퇴근 제외)", options=["재직", "퇴사"], default="재직"),
        "메모": st.column_config.TextColumn("메모 (실근무자명/퇴사일)"),
        "이메일": st.column_config.TextColumn("이메일"),
        "텔레그램ID": st.column_config.TextColumn("텔레그램ID"),
    },
)

# =========================================================================
# 2. 정규직 직원 명부 (계약급여 · 실지급액 · 계좌 · 연락처)
# =========================================================================
st.markdown('<div class="section-title">2. 정규직 직원 명부 (계약급여 · 계좌 · 연락처)</div>', unsafe_allow_html=True)
df_reg_disp = df_reg.copy()
df_reg_disp["계약급여"] = df_reg_disp["계약급여"].apply(clean_int)
df_reg_disp["최종급여"] = df_reg_disp["최종급여"].apply(clean_int)

edited_reg = st.data_editor(
    df_reg_disp,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key=f"reg_ed_{selected_store}",
    column_config={
        "이름": st.column_config.TextColumn("이름", required=True),
        "은행명": st.column_config.SelectboxColumn("은행명", options=BANK_OPTIONS),
        "계약급여": st.column_config.NumberColumn("계약급여 (원)", format="%,d"),
        "최종급여": st.column_config.NumberColumn("최종급여 (원)", format="%,d"),
    },
)

if st.button("💾 수정된 직원 명부 · 시급/계좌 정보 저장하기", type="primary", use_container_width=True):
    with st.spinner("통합근태DB 시트에 저장 중..."):
        save_staff_tabs(store_cfg["db_id"], edited_part, edited_reg)
        st.success("✅ 파트타임 및 정규직 직원 명부가 모두 저장되었습니다!")
        st.cache_data.clear()
        st.rerun()
