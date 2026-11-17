"""
================================================================================
[파일명] views/staff.py
[역할] 관리자/매니저 전용 '직원 · 시급/계좌 관리 및 전자 근로계약서 발급' 페이지
[주요 기능]
  1. 매니저 PIN 번호 잠금 해제
  2. 신규 파트타임 직원 간편 등록 폼
  3. 파트타임 / 정규직 직원 명부 표(data_editor) 조회, 수정 및 시트 저장
  4. [핵심 개편] 등록된 직원을 드롭다운에서 선택하면 기본정보(입사일, 시급/월급, 계좌, 이메일)를
     자동으로 불러와 전자 근로계약서 서명 링크를 생성하는 기능
  5. 발급된 계약서 진행 상태(서명대기/서명완료) 및 구글 드라이브 PDF 열기 버튼 목록
================================================================================
"""

import os
import re
import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()


# ------------------------------------------------------------------------------
# 환경변수 및 Streamlit Secrets 조회 함수
# ------------------------------------------------------------------------------
def get_secret(key: str, default: str = ""):
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


# ------------------------------------------------------------------------------
# 매장별 통합근태DB 시트 ID 및 매니저 PIN 설정
# ------------------------------------------------------------------------------
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

# 파트타임 탭(10열)과 정규직 탭(8열)의 컬럼 순서 정의
PART_COLS = ["입사일자", "이름", "주민번호", "은행명", "계좌번호", "시급", "상태", "메모", "이메일", "텔레그램ID"]
REG_COLS = ["이름", "주민번호", "은행명", "계좌번호", "계약급여", "최종급여", "텔레그램ID", "이메일"]

# 은행 대량이체 표준 은행명 리스트 및 약칭 변환 매핑
BANK_OPTIONS = [
    "KB국민", "신한은행", "우리은행", "하나은행", "NH농협", "IBK기업은행",
    "카카오뱅크", "토스뱅크", "케이뱅크", "새마을금고", "신협", "우체국",
    "SC제일은행", "부산은행", "대구은행(iM뱅크)", "광주은행", "전북은행", "경남은행", "수협은행",
]

BANK_ALIAS_MAP = {
    "국민": "KB국민", "국민은행": "KB국민", "신한": "신한은행", "우리": "우리은행",
    "하나": "하나은행", "농협": "NH농협", "농협은행": "NH농협", "기업": "IBK기업은행",
    "기업은행": "IBK기업은행", "카카오": "카카오뱅크", "토스": "토스뱅크", "케이": "케이뱅크",
}

# 화면 스타일(Pretendard 폰트 및 여백) 설정
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


# ------------------------------------------------------------------------------
# 구글 시트 연결 및 데이터 정제 보조 함수들
# ------------------------------------------------------------------------------
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
    """콤마 등이 섞인 금액 문자열을 정수(int)로 안전하게 변환"""
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0
    digits = re.sub(r"[^\d.-]", "", str(val))
    try:
        return int(round(float(digits)))
    except ValueError:
        return 0


def normalize_bank_name(bank_str: str) -> str:
    """'국민', '국민은행' 등을 대량이체 표준 명칭('KB국민')으로 통일"""
    b = str(bank_str).strip()
    if not b:
        return ""
    return BANK_ALIAS_MAP.get(b, b)


def format_ssn(ssn_str):
    """주민번호 13자리 숫자를 앞6자리-뒤7자리 하이픈 형식으로 자동 포맷팅"""
    digits = re.sub(r"\D", "", str(ssn_str).strip())
    if len(digits) == 13:
        return f"{digits[:6]}-{digits[6:]}"
    return str(ssn_str).strip()


# ------------------------------------------------------------------------------
# '파트타임' 및 '정규직' 탭 데이터 로드 및 저장 함수
# ------------------------------------------------------------------------------
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


# =========================================================================
# 상단 헤더 및 비밀번호 잠금 확인
# =========================================================================
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

st.caption("💡 **Step 1.** 먼저 직원을 등록(파트타임/정규직)한 뒤 → **Step 2.** 하단 전자 근로계약서에서 해당 직원을 선택하면 기본정보가 자동으로 연동됩니다.")

df_part, df_reg = load_staff_tabs(store_cfg["db_id"])

# =========================================================================
# 신규 파트타임 직원 간편 등록 폼
# =========================================================================
with st.expander("➕ 신규 파트타임 직원 등록하기", expanded=False):
    with st.form("new_part_staff_form", clear_on_submit=True):
        fc1, fc2, fc3, fc4 = st.columns([1.0, 1.1, 1.0, 1.2])
        new_join_date = fc1.date_input("입사일자", value=datetime.date.today())
        new_name = fc2.text_input("이름 (계좌 예금주명)*", placeholder="예: 홍길동")
        new_wage = fc3.number_input("시급 (원)", min_value=0, value=12000, step=100)
        new_ssn = fc4.text_input("주민등록번호", placeholder="숫자 13자리 입력")

        fc5, fc6, fc7, fc8 = st.columns([1.0, 1.3, 1.2, 1.0])
        new_bank = fc5.selectbox("은행명", options=BANK_OPTIONS, index=0)
        new_acct = fc6.text_input("계좌번호", placeholder="예: 3333-01-1234567")
        new_email = fc7.text_input("이메일 (계약서·명세서 발송용)", placeholder="example@gmail.com")
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
                st.success(f"🎉 [{clean_nm}] 님이 신규 등록되었습니다! 아래 전자 근로계약서에서 직원을 선택해 계약서를 발급하세요.")
                st.cache_data.clear()
                st.rerun()

# =========================================================================
# 1. 파트타임 직원 명부 편집 표
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
# 2. 정규직 직원 명부 편집 표
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

# ==============================================================================
# 📝 전자 근로계약서 발급 및 서명 현황 관리 (직원 선택 -> 기본정보 자동 연동)
# ==============================================================================
import datetime as _dt
from contract_utils import create_new_contract, load_all_contracts

st.divider()
st.subheader("📝 전자 근로계약서 발급 및 서명 현황")
st.caption("위 직원 명부에 등록된 직원을 선택하면 기본정보(시급/월급, 입사일, 계좌, 이메일 등)가 자동으로 불러와집니다. 추가 근로조건만 확인 후 링크를 발급하세요.")

APP_BASE_URL = "https://store-salary-auto-5xqyisbltbombukh3zltva.streamlit.app/"

# 파트타임 및 정규직 명부에서 재직 중인 직원들을 드롭다운 선택지(staff_options)로 생성
staff_lookup = {}
staff_options = ["➕ 직접 입력 (미등록 신규 직원)"]

for _, r in df_part.iterrows():
    nm = str(r.get("이름", "")).strip()
    st_val = str(r.get("상태", "재직")).strip()
    if nm and st_val != "퇴사":
        label = f"[파트타임] {nm} (시급 {clean_int(r.get('시급', 12000)):,}원)"
        staff_options.append(label)
        staff_lookup[label] = {
            "구분": "파트타임",
            "직원명": nm,
            "근로개시일": str(r.get("입사일자", "")).strip(),
            "임금구분": "시급",
            "금액": clean_int(r.get("시급", 12000)) or 12000,
            "주민번호": str(r.get("주민번호", "")).strip(),
            "은행명": normalize_bank_name(r.get("은행명", "")),
            "계좌번호": str(r.get("계좌번호", "")).strip(),
            "이메일": str(r.get("이메일", "")).strip(),
        }

for _, r in df_reg.iterrows():
    nm = str(r.get("이름", "")).strip()
    if nm:
        label = f"[정규직] {nm} (월급 {clean_int(r.get('계약급여', 3000000)):,}원)"
        staff_options.append(label)
        staff_lookup[label] = {
            "구분": "정규직",
            "직원명": nm,
            "근로개시일": "",
            "임금구분": "월급",
            "금액": clean_int(r.get("계약급여", 3000000)) or 3000000,
            "주민번호": str(r.get("주민번호", "")).strip(),
            "은행명": normalize_bank_name(r.get("은행명", "")),
            "계좌번호": str(r.get("계좌번호", "")).strip(),
            "이메일": str(r.get("이메일", "")).strip(),
        }

with st.expander("➕ 새 근로계약서 링크 생성하기 (직원 선택 → 자동 불러오기)", expanded=True):
    # 1단계: 드롭다운에서 직원 선택
    selected_staff_label = st.selectbox(
        "👤 1단계: 계약서를 작성할 직원 선택 (위 직원 명부 연동)",
        options=staff_options,
        index=0,
        key="c_staff_selector",
    )

    # 선택한 직원의 기본정보 추출
    prefill = staff_lookup.get(selected_staff_label, {})
    default_name = prefill.get("직원명", "")
    default_pay_type = prefill.get("임금구분", "시급")
    default_pay_amt = prefill.get("금액", 12000 if default_pay_type == "시급" else 3000000)

    default_start_date = _dt.date.today()
    raw_sdate = prefill.get("근로개시일", "")
    if raw_sdate:
        try:
            default_start_date = _dt.date.fromisoformat(raw_sdate[:10])
        except Exception:
            pass

    if prefill:
        st.info(
            f"✅ **{default_name}** 님의 명부 정보 자동 연동됨 — "
            f"**은행/계좌**: {prefill.get('은행명') or '미등록'} {prefill.get('계좌번호') or ''} | "
            f"**이메일**: {prefill.get('이메일') or '미등록'} *(직원 서명 화면에 자동으로 미리 채워집니다)*"
        )

    # 직원을 바꿀 때마다 아래 입력칸들이 해당 직원의 값으로 즉시 바뀌도록 동적 key 부여
    k_sfx = selected_staff_label

    # 2단계: 근로조건 확인 및 추가 입력
    c_col1, c_col2, c_col3 = st.columns(3)
    with c_col1:
        c_type = st.selectbox(
            "계약 유형",
            ["기간의 정함이 없는 경우", "기간의 정함이 있는 경우"],
            key=f"new_c_type_{k_sfx}",
        )
        c_emp_name = st.text_input("직원 성명", value=default_name, placeholder="예: 홍길동", key=f"new_c_name_{k_sfx}")
        c_start_date = st.date_input("근로개시일", value=default_start_date, key=f"new_c_start_{k_sfx}")
        c_end_date = None
        if c_type == "기간의 정함이 있는 경우":
            c_end_date = st.date_input(
                "근로종료일",
                value=default_start_date + _dt.timedelta(days=365),
                key=f"new_c_end_{k_sfx}",
            )

    with c_col2:
        pay_type_idx = 0 if default_pay_type == "시급" else 1
        c_pay_type = st.selectbox("임금 구분", ["시급", "월급"], index=pay_type_idx, key=f"new_c_pay_type_{k_sfx}")
        c_pay_amt = st.number_input(
            "임금 금액 (원)",
            min_value=0,
            value=int(default_pay_amt) if c_pay_type == default_pay_type else (12000 if c_pay_type == "시급" else 3000000),
            step=100 if c_pay_type == "시급" else 50000,
            key=f"new_c_pay_amt_{k_sfx}",
        )
        c_bonus = st.text_input("상여금", value="없음", key=f"new_c_bonus_{k_sfx}")
        c_other_pay = st.text_input("기타급여(제수당 등)", value="없음", key=f"new_c_other_{k_sfx}")

    with c_col3:
        c_w_start = st.text_input("소정근로 시작시간", value="17:00", key=f"new_c_w_start_{k_sfx}")
        c_w_end = st.text_input("소정근로 종료시간", value="22:00", key=f"new_c_w_end_{k_sfx}")
        c_break = st.number_input("휴게시간 (분)", min_value=0, max_value=180, value=30, step=10, key=f"new_c_break_{k_sfx}")
        c_days = st.number_input("주 근무일수 (일)", min_value=1, max_value=7, value=5, key=f"new_c_days_{k_sfx}")
        c_rest = st.selectbox("주휴요일", ["월", "화", "수", "목", "금", "토", "일"], index=0, key=f"new_c_rest_{k_sfx}")

    c_job = st.text_input(
        "업무의 내용",
        value="홀 서빙 및 주방 보조 등 매장 운영 전반",
        key=f"new_c_job_{k_sfx}",
    )
    default_ins = ["고용보험", "산재보험"] if c_pay_type == "시급" else ["고용보험", "산재보험", "국민연금", "건강보험"]
    c_ins = st.multiselect(
        "사회보험 적용여부",
        ["고용보험", "산재보험", "국민연금", "건강보험"],
        default=default_ins,
        key=f"new_c_ins_{k_sfx}",
    )

    # 3단계: 전용 서명 링크 발급 버튼
    if st.button("🔗 전자 근로계약서 링크 발급", type="primary", use_container_width=True):
        if not c_emp_name.strip():
            st.error("직원 성명을 입력해 주세요.")
        else:
            payload = {
                "계약유형": c_type,
                "직원명": c_emp_name.strip(),
                "근로개시일": c_start_date.strftime("%Y-%m-%d"),
                "근로종료일": c_end_date.strftime("%Y-%m-%d") if c_end_date else "",
                "업무내용": c_job.strip(),
                "근무시작": c_w_start.strip(),
                "근무종료": c_w_end.strip(),
                "휴게시간(분)": c_break,
                "주근무일수": c_days,
                "주휴요일": c_rest,
                "임금구분": c_pay_type,
                "금액": c_pay_amt,
                "상여금": c_bonus.strip(),
                "기타급여": c_other_pay.strip(),
                "사회보험": ", ".join(c_ins) if c_ins else "해당없음",
                # 선택한 직원의 기존 기본정보도 함께 저장하여 서명 화면에서 자동 프리필
                "주민번호": prefill.get("주민번호", ""),
                "은행명": prefill.get("은행명", ""),
                "계좌번호": prefill.get("계좌번호", ""),
                "이메일": prefill.get("이메일", ""),
            }
            new_cid = create_new_contract(st.secrets, payload)
            sign_url = f"{APP_BASE_URL}?contract_id={new_cid}"
            st.success(f"✅ **{c_emp_name.strip()}** 님의 전자 근로계약서 링크가 발급되었습니다! 아래 주소를 복사해 직원에게 전달해 주세요.")
            st.code(sign_url, language="text")

# ------------------------------------------------------------------------------
# 최근 발급된 계약서 현황 리스트 및 구글 드라이브 PDF 바로가기
# ------------------------------------------------------------------------------
st.markdown("#### 📋 발급 및 서명 완료 목록")
try:
    all_contracts = load_all_contracts(st.secrets)
    if not all_contracts:
        st.info("아직 발급된 전자 근로계약서가 없습니다.")
    else:
        for item in reversed(all_contracts[-20:]):
            status_badge = "✅ 서명완료" if item.get("상태") == "서명완료" else "⏳ 서명대기"
            link_url = f"{APP_BASE_URL}?contract_id={item.get('계약ID')}"
            with st.container(border=True):
                r1, r2, r3 = st.columns([3, 2, 2])
                with r1:
                    st.markdown(f"**{item.get('직원명')}** · {status_badge} ({item.get('계약유형')})")
                    st.caption(f"입사일: {item.get('근로개시일')} | {item.get('임금구분')} {item.get('금액')}원 | 생성: {item.get('생성일시')}")
                with r2:
                    if item.get("상태") == "서명완료":
                        st.caption(f"서명일시: {item.get('서명일시')}")
                        st.caption(f"연락처: {item.get('연락처')} / 이메일: {item.get('이메일')}")
                    else:
                        st.caption("직원 서명 대기 중입니다.")
                with r3:
                    if item.get("상태") == "서명완료" and item.get("드라이브PDF링크"):
                        st.link_button("📄 드라이브 PDF 열기", item.get("드라이브PDF링크"), use_container_width=True)
                    else:
                        st.code(link_url, language="text")
except Exception as e:
    st.warning(f"근로계약서 목록을 불러오는 중 오류가 발생했습니다: {e}")
