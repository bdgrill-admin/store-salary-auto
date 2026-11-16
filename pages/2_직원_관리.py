import os
import re
import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# =========================================================================
# 0. 매장 및 인증 설정
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
        "db_id": "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8",
        "info_id": "1oLO0aH2UQhiwOfaSPGnxFLmQ8wDqEal3wm7NGSkyUpU",
        "manager_pin": get_secret("MANAGER_PIN_BUNDANG", "0524"),
    },
    # 향후 감동한점 오픈 시 주석 해제 후 시트 ID 입력
    # "감동한점": {
    #     "db_id": "여기에_감동한점_통합근태DB_ID",
    #     "info_id": "여기에_감동한점_직원인적사항_ID",
    #     "manager_pin": get_secret("MANAGER_PIN_GAMDONG", "0524"),
    # },
}

CREDENTIALS_FILE = "credentials.json"
MASTER_COLS = ["입사일자", "이름", "은행명", "계좌번호", "상태", "메모", "이메일", "텔레그램ID"]

st.set_page_config(page_title="직원 · 시급/계좌 관리", page_icon="👥", layout="wide")


# =========================================================================
# 1. 스타일
# =========================================================================
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


# =========================================================================
# 2. 유틸리티 & 구글 시트 연동
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


def clean_int(val):
    if pd.isna(val) or val is None or str(val).strip() == "":
        return 0
    digits = re.sub(r"[^\d.-]", "", str(val))
    try:
        return int(round(float(digits)))
    except ValueError:
        return 0


def format_ssn(ssn_str):
    digits = re.sub(r"\D", "", str(ssn_str).strip())
    if len(digits) == 13:
        return f"{digits[:6]}-{digits[6:]}"
    return str(ssn_str).strip()


@st.cache_data(ttl=25, show_spinner="직원 명부 및 계좌 정보를 불러오는 중...")
def load_staff_data(db_id: str, info_id: str):
    gc = get_gspread_client()
    db_ss = gc.open_by_key(db_id)
    info_ss = gc.open_by_key(info_id)

    # 1) 통합근태DB -> 직원목록 (입사일자, 이름, 은행명, 계좌번호, 상태, 메모, 이메일, 텔레그램ID)
    emp_ws = db_ss.worksheet("직원목록")
    emp_rows = emp_ws.get_all_values()
    master_list = []
    if len(emp_rows) >= 2:
        headers = [c.strip() for c in emp_rows[0]]
        for r in emp_rows[1:]:
            d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
            if d.get("이름"):
                master_list.append(d)
    df_master = pd.DataFrame(master_list)
    for col in MASTER_COLS:
        if col not in df_master.columns:
            df_master[col] = "재직" if col == "상태" else ""
    df_master = df_master[MASTER_COLS].copy()

    # 2) 직원인적사항 -> 파트타임
    titles = [s.title.strip() for s in info_ss.worksheets()]
    part_list = []
    if "파트타임" in titles:
        p_ws = info_ss.worksheet("파트타임")
        p_rows = p_ws.get_all_values()
        h_idx = 0
        for i, r in enumerate(p_rows[:5]):
            if "이름" in [c.strip() for c in r]:
                h_idx = i
                break
        if len(p_rows) > h_idx + 1:
            headers = [c.strip() for c in p_rows[h_idx]]
            for r in p_rows[h_idx + 1:]:
                d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
                if d.get("이름"):
                    part_list.append(d)
    df_part_info = pd.DataFrame(part_list)
    for col in ["이름", "주민번호", "은행명", "계좌번호", "시급", "비고", "텔레그램ID", "이메일"]:
        if col not in df_part_info.columns:
            df_part_info[col] = ""

    return df_master, df_part_info


def save_staff_data(db_id: str, info_id: str, df_master_edited: pd.DataFrame, df_part_edited: pd.DataFrame):
    gc = get_gspread_client()
    db_ss = gc.open_by_key(db_id)
    info_ss = gc.open_by_key(info_id)

    # 1) 직원목록 저장 (실제 8개 컬럼 유지)
    emp_ws = db_ss.worksheet("직원목록")
    for c in MASTER_COLS:
        if c not in df_master_edited.columns:
            df_master_edited[c] = ""
    clean_m = df_master_edited[MASTER_COLS].fillna("").astype(str)
    clean_m = clean_m[clean_m["이름"].str.strip() != ""]
    emp_ws.clear()
    emp_ws.update(range_name="A1", values=[MASTER_COLS] + clean_m.values.tolist())

    # 2) 직원인적사항(파트타임) 저장
    part_ws = info_ss.worksheet("파트타임")
    existing_rows = part_ws.get_all_values()
    h_idx = 0
    for i, r in enumerate(existing_rows[:5]):
        if "이름" in [c.strip() for c in r]:
            h_idx = i
            break
    orig_headers = [c.strip() for c in existing_rows[h_idx] if c.strip()] if len(existing_rows) > h_idx else [
        "이름", "주민번호", "은행명", "계좌번호", "시급", "비고", "텔레그램ID", "이메일"
    ]
    for c in orig_headers:
        if c not in df_part_edited.columns:
            df_part_edited[c] = ""
    clean_p = df_part_edited[orig_headers].fillna("").astype(str)
    clean_p = clean_p[clean_p["이름"].str.strip() != ""]

    prefix_rows = existing_rows[:h_idx] if h_idx > 0 else []
    part_ws.clear()
    part_ws.update(range_name="A1", values=prefix_rows + [orig_headers] + clean_p.values.tolist())


# =========================================================================
# 3. 상단 헤더 & 매니저/관리자 잠금 확인
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

st.caption("💡 신규 직원 등록, 시급 변경, 재직/퇴사 상태 변경 시 **출퇴근기록부(`직원목록`)와 급여 정산 시트(`직원인적사항`)에 동시에 반영**됩니다.")

df_master, df_part_info = load_staff_data(store_cfg["db_id"], store_cfg["info_id"])

# =========================================================================
# 4. 신규 직원 간편 등록
# =========================================================================
with st.expander("➕ 신규 직원 등록하기", expanded=False):
    with st.form("new_staff_form", clear_on_submit=True):
        fc1, fc2, fc3, fc4 = st.columns([1.0, 1.1, 1.0, 1.2])
        new_join_date = fc1.date_input("입사일자", value=datetime.date.today())
        new_name = fc2.text_input("이름 (계좌 예금주명)*", placeholder="예: 홍길동")
        new_wage = fc3.number_input("시급 (원)", min_value=0, value=10320, step=100)
        new_ssn = fc4.text_input("주민등록번호", placeholder="예: 000101-3123456")

        fc5, fc6, fc7, fc8 = st.columns([1.0, 1.3, 1.2, 1.0])
        new_bank = fc5.text_input("은행명", placeholder="예: 카카오뱅크")
        new_acct = fc6.text_input("계좌번호", placeholder="예: 3333-01-1234567")
        new_email = fc7.text_input("이메일 (명세서 발송용)", placeholder="example@gmail.com")
        new_tg = fc8.text_input("텔레그램 ID (선택)", placeholder="숫자 ID")

        new_memo = st.text_input(
            "메모 / 실근무자 이름 (예금주와 실제 출근자가 다를 때만 실근무자 이름 입력)",
            placeholder="예: 강성원",
        )

        if st.form_submit_button("✅ 신규 직원 등록 및 양쪽 시트 반영", type="primary", use_container_width=True):
            clean_nm = new_name.strip()
            if not clean_nm:
                st.error("직원 이름을 입력해 주세요.")
            else:
                new_m_row = pd.DataFrame([{
                    "입사일자": new_join_date.strftime("%Y-%m-%d"),
                    "이름": clean_nm,
                    "은행명": new_bank.strip(),
                    "계좌번호": new_acct.strip(),
                    "상태": "재직",
                    "메모": new_memo.strip(),
                    "이메일": new_email.strip(),
                    "텔레그램ID": new_tg.strip(),
                }])
                updated_m = pd.concat([df_master, new_m_row], ignore_index=True)

                remark_str = f"(실근무) {new_memo.strip()}" if new_memo.strip() else ""
                new_p_row = pd.DataFrame([{
                    "이름": clean_nm,
                    "주민번호": format_ssn(new_ssn),
                    "은행명": new_bank.strip(),
                    "계좌번호": new_acct.strip(),
                    "시급": str(int(new_wage)),
                    "비고": remark_str,
                    "텔레그램ID": new_tg.strip(),
                    "이메일": new_email.strip(),
                }])
                updated_p = pd.concat([df_part_info, new_p_row], ignore_index=True)

                save_staff_data(store_cfg["db_id"], store_cfg["info_id"], updated_m, updated_p)
                st.success(f"🎉 [{clean_nm}] 님이 신규 등록되었습니다!")
                st.cache_data.clear()
                st.rerun()

# =========================================================================
# 5. 직원 명부(재직/퇴사 · 계좌 · 연락처) & 시급/주민번호 일괄 편집
# =========================================================================
st.markdown('<div class="section-title">1. 출퇴근기록부 직원 명부 (입사일자 · 재직/퇴사 · 계좌 · 연락처)</div>', unsafe_allow_html=True)

edited_master = st.data_editor(
    df_master,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key=f"master_ed_{selected_store}",
    column_config={
        "입사일자": st.column_config.TextColumn("입사일자"),
        "이름": st.column_config.TextColumn("이름", required=True),
        "은행명": st.column_config.TextColumn("은행명"),
        "계좌번호": st.column_config.TextColumn("계좌번호"),
        "상태": st.column_config.SelectboxColumn("상태 (퇴사 변경 시 출퇴근 제외)", options=["재직", "퇴사"], default="재직"),
        "메모": st.column_config.TextColumn("메모 (실근무자명/퇴사일)"),
        "이메일": st.column_config.TextColumn("이메일"),
        "텔레그램ID": st.column_config.TextColumn("텔레그램ID"),
    },
)

st.markdown('<div class="section-title">2. 급여 정산 · 세무신고용 시급 및 주민번호 관리</div>', unsafe_allow_html=True)
df_part_disp = df_part_info.copy()
df_part_disp["시급"] = df_part_disp["시급"].apply(clean_int)

edited_part = st.data_editor(
    df_part_disp,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key=f"part_ed_{selected_store}",
    column_config={
        "시급": st.column_config.NumberColumn("시급 (원)", format="%,d"),
    },
)

if st.button("💾 수정된 직원 명부 · 시급/계좌 정보 일괄 저장하기", type="primary", use_container_width=True):
    with st.spinner("양쪽 구글 시트에 동시 저장 중..."):
        # 위 '직원목록'에서 수정한 계좌·이메일·텔레그램ID를 아래 '직원인적사항' 표에도 자동 동기화
        if not edited_master.empty and not edited_part.empty:
            master_lookup = {
                str(r["이름"]).strip(): r
                for _, r in edited_master.iterrows()
                if str(r.get("이름", "")).strip()
            }
            for idx, r in edited_part.iterrows():
                nm = str(r.get("이름", "")).strip()
                if nm in master_lookup:
                    m_row = master_lookup[nm]
                    for sync_col in ["은행명", "계좌번호", "이메일", "텔레그램ID"]:
                        val = str(m_row.get(sync_col, "")).strip()
                        if val:
                            edited_part.at[idx, sync_col] = val

        save_staff_data(store_cfg["db_id"], store_cfg["info_id"], edited_master, edited_part)
        st.success("✅ 직원 명부와 시급/계좌 정보가 양쪽 시트에 모두 저장되었습니다!")
        st.cache_data.clear()
        st.rerun()
