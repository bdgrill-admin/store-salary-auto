"""
================================================================================
[파일명] views/staff.py
[역할] 관리자/매니저 전용 '직원 · 시급/계좌 · 보건증 만료 관리 및 전자 근로계약서 발급' 페이지
================================================================================
"""

import re
import json
import datetime
import requests
import pandas as pd
import streamlit as st
from store_registry import (
    load_all_stores,
    load_store_settings,
    get_gspread_client,
)

STORES = load_all_stores()

PART_COLS = ["입사일자", "이름", "주민번호", "은행명", "계좌번호", "시급", "상태", "메모", "이메일", "텔레그램ID", "보건증만료일"]
REG_COLS = ["입사일자", "이름", "주민번호", "은행명", "계좌번호", "계약급여", "제세금", "계산급여", "상태", "메모", "이메일", "텔레그램ID", "보건증만료일"]

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
    .step1-highlight {
        background-color: #FFFBEB;
        border: 2px solid #F59E0B;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 12px;
    }
    .step1-title {
        font-size: 1.08rem;
        font-weight: 800;
        color: #B45309;
        margin-bottom: 4px;
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


@st.cache_data(ttl=25, show_spinner="직원 명부를 불러오는 중...")
def load_staff_sheets(db_id: str):
    gc = get_gspread_client()
    db_ss = gc.open_by_key(db_id)
    titles = [s.title.strip() for s in db_ss.worksheets()]

    def read_tab(tab_name: str, expected_cols: list, is_reg: bool = False):
        if tab_name not in titles:
            return pd.DataFrame(columns=expected_cols)
        ws = db_ss.worksheet(tab_name)
        rows = ws.get_all_values()
        out = []
        if len(rows) >= 2:
            headers = [c.strip() for c in rows[0]]
            for r in rows[1:]:
                d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
                if not d.get("이름"):
                    continue
                if is_reg:
                    c_pay = clean_int(d.get("계약급여", 0))
                    old_net = clean_int(d.get("계산급여", 0)) or clean_int(d.get("최종급여", 0))
                    tax_v = clean_int(d.get("제세금", 0))
                    if tax_v == 0 and c_pay > 0 and 0 < old_net < c_pay:
                        tax_v = c_pay - old_net
                    calc_v = c_pay - tax_v if c_pay > 0 else old_net
                    d["계약급여"] = str(c_pay) if c_pay > 0 else ""
                    d["제세금"] = str(tax_v) if tax_v > 0 else "0"
                    d["계산급여"] = str(calc_v) if calc_v > 0 else ""
                out.append(d)
        df = pd.DataFrame(out)
        for col in expected_cols:
            if col not in df.columns:
                df[col] = "재직" if col == "상태" else ""
        if "상태" in df.columns:
            df["상태"] = df["상태"].apply(lambda x: x if str(x).strip() in ["재직", "퇴사"] else "재직")
        if "은행명" in df.columns:
            df["은행명"] = df["은행명"].apply(normalize_bank_name)
        return df[expected_cols].copy()

    df_part = read_tab("파트타임", PART_COLS, is_reg=False)
    df_reg = read_tab("정규직", REG_COLS, is_reg=True)
    return df_part, df_reg


def send_contract_link_via_webapp(to_email: str, emp_name: str, sign_url: str, app_cfg: dict):
    webapp_url = app_cfg.get("drive_webapp_url", "").strip()
    store_title = app_cfg.get("store_title", "분당그릴").strip() or "분당그릴"
    if not webapp_url or not to_email or "@" not in to_email:
        return False, "이메일 주소 또는 웹앱 URL 미설정"
    payload = {
        "action": "send_email",
        "toEmail": to_email.strip(),
        "subject": f"[{store_title}] {emp_name}님 전자 근로계약서 서명 요청 안내",
        "body": (
            f"안녕하세요, {emp_name}님. {store_title}입니다.\n\n"
            f"아래 전용 링크를 눌러 스마트폰 또는 PC에서 근로계약서 내용을 확인하시고 전자서명을 완료해 주세요.\n\n"
            f"▶ 서명 링크: {sign_url}\n\n"
            f"감사합니다.\n{store_title} 드림"
        ),
    }
    try:
        res = requests.post(
            webapp_url,
            data=json.dumps(payload),
            headers={"Content-Type": "text/plain; charset=utf-8"},
            allow_redirects=True,
            timeout=20,
        )
        rj = res.json()
        return (True, "이메일 발송 완료") if rj.get("ok") else (False, rj.get("error", "발송 실패"))
    except Exception as e:
        return False, str(e)


def save_staff_tabs(db_id: str, df_part_edited: pd.DataFrame, df_reg_edited: pd.DataFrame):
    gc = get_gspread_client()
    db_ss = gc.open_by_key(db_id)

    p_ws = db_ss.worksheet("파트타임")
    for c in PART_COLS:
        if c not in df_part_edited.columns:
            df_part_edited[c] = "재직" if c == "상태" else ""
    clean_p = df_part_edited[PART_COLS].copy()
    clean_p["은행명"] = clean_p["은행명"].apply(normalize_bank_name)
    clean_p["시급"] = clean_p["시급"].apply(lambda x: str(clean_int(x)) if clean_int(x) > 0 else "")
    clean_p["주민번호"] = clean_p["주민번호"].apply(format_ssn)
    clean_p["상태"] = clean_p["상태"].apply(lambda x: x if str(x).strip() in ["재직", "퇴사"] else "재직")
    clean_p = clean_p.fillna("").astype(str)
    clean_p = clean_p[clean_p["이름"].str.strip() != ""]
    p_ws.clear()
    p_ws.update(range_name="A1", values=[PART_COLS] + clean_p.values.tolist(), value_input_option="RAW")

    r_ws = db_ss.worksheet("정규직")
    for c in REG_COLS:
        if c not in df_reg_edited.columns:
            df_reg_edited[c] = "재직" if c == "상태" else ""
    clean_r = df_reg_edited[REG_COLS].copy()
    clean_r["은행명"] = clean_r["은행명"].apply(normalize_bank_name)

    for idx, row in clean_r.iterrows():
        c_val = clean_int(row.get("계약급여", 0))
        t_val = clean_int(row.get("제세금", 0))
        calc_val = max(0, c_val - t_val)
        clean_r.at[idx, "계약급여"] = str(c_val) if c_val > 0 else ""
        clean_r.at[idx, "제세금"] = str(t_val)
        clean_r.at[idx, "계산급여"] = str(calc_val) if calc_val > 0 else ""

    clean_r["주민번호"] = clean_r["주민번호"].apply(format_ssn)
    clean_r["상태"] = clean_r["상태"].apply(lambda x: x if str(x).strip() in ["재직", "퇴사"] else "재직")
    clean_r = clean_r.fillna("").astype(str)
    clean_r = clean_r[clean_r["이름"].str.strip() != ""]
    r_ws.clear()
    r_ws.update(range_name="A1", values=[REG_COLS] + clean_r.values.tolist(), value_input_option="RAW")


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
app_cfg = load_store_settings(store_cfg["db_id"], selected_store)
df_part, df_reg = load_staff_sheets(store_cfg["db_id"])
active_mgr_pin = app_cfg.get("manager_pin") or store_cfg["manager_pin"]

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
                if pin == active_mgr_pin:
                    st.session_state["staff_mgr_unlocked"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()

st.caption("💡 **Step 1.** 먼저 직원을 등록(파트타임/정규직)한 뒤 → **Step 2.** 하단 전자 근로계약서에서 해당 직원을 선택하면 기본정보가 자동으로 연동됩니다.")

today_dt = datetime.date.today()
alert_threshold_days = int(app_cfg.get("health_alert_days", "30") or 30)
health_alerts = []

for gubun_label, df_chk in [("파트타임", df_part), ("정규직", df_reg)]:
    if df_chk.empty:
        continue
    for _, r in df_chk.iterrows():
        nm = str(r.get("이름", "")).strip()
        st_val = str(r.get("상태", "재직")).strip()
        exp_str = str(r.get("보건증만료일", "")).strip()
        if not nm or st_val == "퇴사" or not exp_str:
            continue
        try:
            exp_dt = datetime.date.fromisoformat(exp_str[:10])
            d_left = (exp_dt - today_dt).days
            if d_left < 0:
                health_alerts.append(f"🚨 **[{gubun_label}] {nm}** 님: 보건증 유효기간이 **{abs(d_left)}일 경과**했습니다! (만료일: `{exp_str}`)")
            elif d_left <= alert_threshold_days:
                health_alerts.append(f"⚠️ **[{gubun_label}] {nm}** 님: 보건증 만료 **D-{d_left}** 입니다. 갱신을 안내해 주세요. (만료일: `{exp_str}`)")
        except Exception:
            pass

if health_alerts:
    with st.container(border=True):
        al_c1, al_c2 = st.columns([3.2, 1.0], vertical_alignment="center")
        with al_c1:
            st.error(f"🏥 **보건증 갱신/만료 확인이 필요한 재직 직원이 {len(health_alerts)}명 있습니다!**")
            for ha in health_alerts:
                st.markdown(f"- {ha}")
        with al_c2:
            if st.button("📲 텔레그램으로 갱신 명단 알림 전송", use_container_width=True):
                bot_token = app_cfg.get("telegram_bot_token", "").strip()
                chat_id = app_cfg.get("telegram_chat_id", "").strip()
                store_title = app_cfg.get("store_title", selected_store)
                if bot_token and chat_id:
                    clean_lines = [re.sub(r"[*`]", "", x) for x in health_alerts]
                    msg = f"🏥 [{store_title} 보건증 갱신 알림]\n\n" + "\n".join(clean_lines)
                    requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": msg},
                        timeout=5,
                    )
                    st.toast("텔레그램으로 보건증 갱신 알림을 전송했습니다!")
                else:
                    st.warning("환경설정에서 텔레그램 토큰과 채팅 ID를 확인해 주세요.")

with st.expander("➕ 신규 직원 등록하기 (파트타임 · 정규직)", expanded=False):
    emp_type_choice = st.radio("등록할 직원 구분", ["파트타임 (시급제)", "정규직 (월급제)"], horizontal=True)
    is_reg_new = emp_type_choice.startswith("정규직")

    with st.form("new_staff_unified_form", clear_on_submit=True):
        fc1, fc2, fc3, fc4 = st.columns([1.0, 1.1, 1.0, 1.2])
        new_join_date = fc1.date_input("입사일자", value=datetime.date.today())
        new_name = fc2.text_input("이름 (계좌 예금주명)*", placeholder="예: 홍길동")
        if is_reg_new:
            new_wage = fc3.number_input("계약 월급여 (세전, 원)", min_value=0, value=3500000, step=50000)
        else:
            new_wage = fc3.number_input("시급 (원)", min_value=0, value=12000, step=100)
        new_ssn = fc4.text_input("주민등록번호", placeholder="숫자 13자리 입력")

        fc5, fc6, fc7, fc8 = st.columns([1.0, 1.3, 1.2, 1.0])
        new_bank = fc5.selectbox("은행명", options=BANK_OPTIONS, index=0)
        new_acct = fc6.text_input("계좌번호", placeholder="예: 3333-01-1234567")
        new_email = fc7.text_input("이메일 (계약서·명세서 발송용)", placeholder="example@gmail.com")
        new_tg = fc8.text_input("텔레그램 ID (선택)", placeholder="숫자 ID")

        mc1, mc2, mc3 = st.columns([1.0, 1.1, 2.2])
        new_health_exp = mc1.text_input("보건증 만료일 (선택)", placeholder="예: 2027-11-18")
        if is_reg_new:
            new_tax = mc2.number_input("월 제세금 (4대보험·세금 공제액, 원)", min_value=0, value=242320, step=1000)
            new_memo = mc3.text_input("메모 / 직책 · 특이사항", placeholder="예: 주방 실장")
        else:
            new_tax = 0
            new_memo = mc3.text_input(
                "메모 / 실근무자 이름 (예금주와 실제 출근자가 다를 때만 실근무자 이름 입력)",
                placeholder="예: 강성원",
            )

        if st.form_submit_button("✅ 신규 직원 등록", type="primary", use_container_width=True):
            clean_nm = new_name.strip()
            if not clean_nm:
                st.error("직원 이름을 입력해 주세요.")
            else:
                if is_reg_new:
                    calc_pay = max(0, int(new_wage) - int(new_tax))
                    new_row = pd.DataFrame([{
                        "입사일자": new_join_date.strftime("%Y-%m-%d"),
                        "이름": clean_nm,
                        "주민번호": format_ssn(new_ssn),
                        "은행명": new_bank,
                        "계좌번호": new_acct.strip(),
                        "계약급여": str(int(new_wage)),
                        "제세금": str(int(new_tax)),
                        "계산급여": str(calc_pay),
                        "상태": "재직",
                        "메모": new_memo.strip(),
                        "이메일": new_email.strip(),
                        "텔레그램ID": new_tg.strip(),
                        "보건증만료일": new_health_exp.strip(),
                    }])
                    updated_reg = pd.concat([df_reg, new_row], ignore_index=True)
                    save_staff_tabs(store_cfg["db_id"], df_part, updated_reg)
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
                        "보건증만료일": new_health_exp.strip(),
                    }])
                    updated_part = pd.concat([df_part, new_row], ignore_index=True)
                    save_staff_tabs(store_cfg["db_id"], updated_part, df_reg)

                st.success(f"🎉 [{clean_nm}] 님이 신규 등록되었습니다! 아래 전자 근로계약서에서 직원을 선택해 계약서를 발급하세요.")
                st.cache_data.clear()
                st.rerun()

st.markdown('<div class="section-title">1. 파트타임 직원 명부 (시급 · 계좌 · 보건증 · 재직/퇴사 관리)</div>', unsafe_allow_html=True)
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
        "보건증만료일": st.column_config.TextColumn("보건증만료일 (YYYY-MM-DD)"),
    },
)

st.markdown('<div class="section-title">2. 정규직 직원 명부 (계약급여 - 제세금 = 계산급여 자동 산출)</div>', unsafe_allow_html=True)
st.caption("💡 **계약급여**와 매월 고정 공제되는 **제세금**(4대보험+소득세)을 입력하면 **계산급여**(고정 실수령액)가 자동 계산됩니다.")

df_reg_disp = df_reg.copy()
df_reg_disp["계약급여"] = df_reg_disp["계약급여"].apply(clean_int)
df_reg_disp["제세금"] = df_reg_disp["제세금"].apply(clean_int)
df_reg_disp["계산급여"] = (df_reg_disp["계약급여"] - df_reg_disp["제세금"]).clip(lower=0)

edited_reg = st.data_editor(
    df_reg_disp,
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True,
    key=f"reg_ed_{selected_store}",
    column_config={
        "입사일자": st.column_config.TextColumn("입사일자"),
        "이름": st.column_config.TextColumn("이름", required=True),
        "주민번호": st.column_config.TextColumn("주민번호"),
        "은행명": st.column_config.SelectboxColumn("은행명", options=BANK_OPTIONS),
        "계좌번호": st.column_config.TextColumn("계좌번호"),
        "계약급여": st.column_config.NumberColumn("계약급여 (원)", format="%,d"),
        "제세금": st.column_config.NumberColumn("제세금 (공제액)", format="%,d"),
        "계산급여": st.column_config.NumberColumn("계산급여 (계약-제세금)", format="%,d", disabled=True),
        "상태": st.column_config.SelectboxColumn("상태 (퇴사 시 정산 제외)", options=["재직", "퇴사"], default="재직"),
        "메모": st.column_config.TextColumn("메모 (직책/퇴사일)"),
        "이메일": st.column_config.TextColumn("이메일"),
        "텔레그램ID": st.column_config.TextColumn("텔레그램ID"),
        "보건증만료일": st.column_config.TextColumn("보건증만료일 (YYYY-MM-DD)"),
    },
)

if st.button("💾 수정된 직원 명부 · 시급/계좌 · 보건증 정보 저장하기", type="primary", use_container_width=True):
    with st.spinner("통합근태DB 시트에 저장 중..."):
        save_staff_tabs(store_cfg["db_id"], edited_part, edited_reg)
        st.success("✅ 파트타임 및 정규직 직원 명부가 모두 저장되었습니다!")
        st.cache_data.clear()
        st.rerun()

# ==============================================================================
# 📝 전자 근로계약서 발급 및 서명 현황 관리
# ==============================================================================
import datetime as _dt
from contract_utils import create_new_contract, load_all_contracts, delete_contract_by_id

st.divider()
st.subheader("📝 전자 근로계약서 발급 및 서명 현황")
st.caption("먼저 계약서를 작성할 직원을 선택하면, 해당 직원의 기본정보와 환경설정 기본 근무조건이 자동으로 연동되어 아래 입력창이 열립니다.")

APP_BASE_URL = "https://store-salary-auto-5xqyisbltbombukh3zltva.streamlit.app/"

PLACEHOLDER_OPT = "🔽 여기를 눌러 계약서를 작성할 직원을 먼저 선택하세요..."
DIRECT_INPUT_OPT = "➕ 직접 입력 (명부에 없는 신규 입사자)"

staff_lookup = {}
staff_options = [PLACEHOLDER_OPT]

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
    st_val = str(r.get("상태", "재직")).strip()
    if nm and st_val != "퇴사":
        label = f"[정규직] {nm} (월급 {clean_int(r.get('계약급여', 3000000)):,}원)"
        staff_options.append(label)
        staff_lookup[label] = {
            "구분": "정규직",
            "직원명": nm,
            "근로개시일": str(r.get("입사일자", "")).strip(),
            "임금구분": "월급",
            "금액": clean_int(r.get("계약급여", 3000000)) or 3000000,
            "주민번호": str(r.get("주민번호", "")).strip(),
            "은행명": normalize_bank_name(r.get("은행명", "")),
            "계좌번호": str(r.get("계좌번호", "")).strip(),
            "이메일": str(r.get("이메일", "")).strip(),
        }

staff_options.append(DIRECT_INPUT_OPT)

with st.expander("➕ 새 근로계약서 링크 생성하기 (직원 선택 필수)", expanded=True):
    st.markdown(
        """
        <div class="step1-highlight">
            <div class="step1-title">👤 1단계: 계약서를 작성할 직원을 먼저 선택해 주세요 (필수)</div>
            <div style="font-size:0.88rem; color:#78350F;">위 직원 명부에 등록된 재직자를 선택하면 아래에 근로조건 입력창과 기본정보가 자동으로 펼쳐집니다.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    selected_staff_label = st.selectbox(
        "계약 대상 직원 선택",
        options=staff_options,
        index=0,
        key=f"c_staff_selector_{selected_store}",
        label_visibility="collapsed",
    )

    if selected_staff_label == PLACEHOLDER_OPT:
        st.warning("☝️ 위 드롭다운 박스를 클릭해 **계약서를 발급할 직원**을 선택하면 아래에 상세 입력란이 나타납니다.")
    else:
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

        st.divider()
        st.markdown("##### 📝 2단계: 연동된 정보 확인 및 근로조건 입력")

        if prefill:
            st.success(
                f"✅ **[{prefill.get('구분')}] {default_name}** 님의 명부 정보 자동 연동 완료!\n\n"
                f"• **입금계좌**: `{prefill.get('은행명') or '미등록'} {prefill.get('계좌번호') or ''}`  |  "
                f"• **이메일**: `{prefill.get('이메일') or '미등록'}` *(직원 서명 화면에 자동으로 미리 채워집니다)*"
            )
        else:
            st.info("ℹ️ 미등록 신규 입사자 직접 입력 모드입니다. 가급적 상단 명부에 먼저 등록하신 뒤 선택하시는 것을 권장합니다.")

        k_sfx = f"{selected_store}_{selected_staff_label}"

        c_col1, c_col2, c_col3 = st.columns(3)
        with c_col1:
            c_type = st.selectbox(
                "계약 유형",
                ["기간의 정함이 없는 경우", "기간의 정함이 있는 경우"],
                key=f"new_c_type_{k_sfx}",
            )
            c_emp_name = st.text_input(
                "직원 성명",
                value=default_name,
                disabled=bool(default_name),
                placeholder="예: 홍길동",
                key=f"new_c_name_{k_sfx}",
            )
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
            c_w_start = st.text_input(
                "소정근로 시작시간",
                value=app_cfg.get("default_work_start", "17:00"),
                key=f"new_c_w_start_{k_sfx}",
            )
            c_w_end = st.text_input(
                "소정근로 종료시간",
                value=app_cfg.get("default_work_end", "22:00"),
                key=f"new_c_w_end_{k_sfx}",
            )
            c_break = st.number_input(
                "휴게시간 (분)",
                min_value=0,
                max_value=180,
                value=int(app_cfg.get("default_break_min", "30") or 30),
                step=10,
                key=f"new_c_break_{k_sfx}",
            )
            c_days = st.number_input("주 근무일수 (일)", min_value=1, max_value=7, value=5, key=f"new_c_days_{k_sfx}")
            c_rest = st.selectbox("주휴요일", ["월", "화", "수", "목", "금", "토", "일"], index=0, key=f"new_c_rest_{k_sfx}")

        c_job = st.text_input(
            "업무의 내용",
            value=app_cfg.get("default_job_desc", "홀 서빙 및 주방 보조 등 매장 운영 전반"),
            key=f"new_c_job_{k_sfx}",
        )
        default_ins = ["고용보험", "산재보험"] if c_pay_type == "시급" else ["고용보험", "산재보험", "국민연금", "건강보험"]
        c_ins = st.multiselect(
            "사회보험 적용여부",
            ["고용보험", "산재보험", "국민연금", "건강보험"],
            default=default_ins,
            key=f"new_c_ins_{k_sfx}",
        )

        c_include_nda = st.checkbox(
            "🔒 비밀유지 및 경업금지 서약서 함께 받기 (레시피·숙성법·원가·거래처 보호 및 퇴직 후 2년 경업금지)",
            value=(prefill.get("구분") == "정규직"),
            key=f"new_c_nda_{k_sfx}",
        )

        if st.button("🔗 전자 근로계약서 링크 발급", type="primary", use_container_width=True):
            final_emp_name = default_name if default_name else c_emp_name.strip()
            if not final_emp_name:
                st.error("직원 성명을 입력해 주세요.")
            else:
                payload = {
                    "계약유형": c_type,
                    "직원명": final_emp_name,
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
                    "주민번호": prefill.get("주민번호", ""),
                    "은행명": prefill.get("은행명", ""),
                    "계좌번호": prefill.get("계좌번호", ""),
                    "이메일": prefill.get("이메일", ""),
                    "비밀유지서약": "Y" if c_include_nda else "N",
                }
                new_cid = create_new_contract(st.secrets, payload)
                sign_url = f"{APP_BASE_URL}?contract_id={new_cid}"
                nda_msg = " (비밀유지 서약서 포함)" if c_include_nda else ""
                st.success(f"✅ **{final_emp_name}** 님의 전자 근로계약서{nda_msg} 링크가 발급되었습니다! 아래 주소를 복사해 직원에게 전달해 주세요.")
                st.code(sign_url, language="text")

st.markdown("#### 📋 발급 및 서명 완료 목록")
try:
    all_contracts = load_all_contracts(st.secrets)
    if not all_contracts:
        st.info("아직 발급된 전자 근로계약서가 없습니다.")
    else:
        for item in reversed(all_contracts[-20:]):
            cid_val = item.get("계약ID", "")
            emp_nm = item.get("직원명", "")
            is_done = item.get("상태") == "서명완료"
            status_badge = "✅ 서명완료" if is_done else "⏳ 서명대기"
            nda_badge = " · 🔒 비밀유지서약포함" if str(item.get("비밀유지서약", "")).upper() == "Y" else ""
            link_url = f"{APP_BASE_URL}?contract_id={cid_val}"

            with st.container(border=True):
                r1, r2, r3 = st.columns([2.8, 2.2, 2.2], vertical_alignment="center")
                with r1:
                    st.markdown(f"**{emp_nm}** · {status_badge}{nda_badge} ({item.get('계약유형')})")
                    st.caption(f"입사일: {item.get('근로개시일')} | {item.get('임금구분')} {item.get('금액')}원 | 생성: {item.get('생성일시')}")
                with r2:
                    if is_done:
                        st.caption(f"서명일시: {item.get('서명일시')}")
                        st.caption(f"연락처: {item.get('연락처')} / 보건증제출: {item.get('보건증제출일')}")
                    else:
                        st.code(link_url, language="text")
                with r3:
                    if is_done and item.get("드라이브PDF링크"):
                        st.link_button("📄 드라이브 PDF 열기", item.get("드라이브PDF링크"), use_container_width=True)
                    elif not is_done:
                        b_col1, b_col2 = st.columns(2)
                        with b_col1:
                            if st.button("📨 링크 발송", key=f"resend_{cid_val}", use_container_width=True):
                                target_mail = item.get("이메일", "").strip()
                                if target_mail:
                                    ok, msg = send_contract_link_via_webapp(target_mail, emp_nm, link_url, app_cfg)
                                    if ok:
                                        st.toast(f"{emp_nm} 님 이메일({target_mail})로 서명 링크를 발송했습니다!")
                                    else:
                                        st.error(f"발송 실패: {msg}")
                                else:
                                    st.warning("명부에 이메일이 없습니다. 링크를 직접 복사해 카톡/문자로 전달해 주세요.")
                        with b_col2:
                            if st.button("🗑️ 대기 삭제", key=f"del_c_{cid_val}", use_container_width=True):
                                if delete_contract_by_id(st.secrets, cid_val):
                                    st.toast(f"[{emp_nm}] 님의 서명대기 계약서를 삭제했습니다.")
                                    st.rerun()
                                else:
                                    st.error("삭제 대상을 찾지 못했습니다.")
except Exception as e:
    st.warning(f"근로계약서 목록을 불러오는 중 오류가 발생했습니다: {e}")
