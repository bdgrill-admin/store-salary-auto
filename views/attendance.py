"""
================================================================================
[파일명] views/attendance.py
[역할] 매장 직원 및 매니저 공용 '일일 출퇴근기록부 및 월별 근무시간 조회' 페이지
================================================================================
"""

import re
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
SHIFT_OPTIONS = ["평일", "주말(점심)", "주말(저녁)", "기타"]
EMP_PLACEHOLDER = "🔽 이름 선택"
REG_CHANGE_TYPES = ["➕ 추가출근", "➖ 기타휴무", "🔄 대체휴무"]
REG_CHANGE_UNITS = ["1일", "시간단위(사유란 기재)"]


def apply_clean_style():
    st.markdown(
        """
        <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

        html, body, [class*="css"] {
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
        }
        .block-container {
            padding-top: 3.2rem;
            padding-bottom: 2.5rem;
            max-width: 1380px;
        }
        .app-title {
            font-size: 1.55rem;
            font-weight: 700;
            color: #1E293B;
            margin: 0;
            line-height: 1.2;
            letter-spacing: -0.02em;
            white-space: nowrap;
        }
        .app-subtitle {
            font-size: 0.92rem;
            font-weight: 600;
            color: #475569;
            margin-top: 0.5rem;
            margin-bottom: 0.3rem;
        }
        .section-title {
            font-size: 1.02rem;
            font-weight: 700;
            color: #1E293B;
            margin: 0.6rem 0 0.45rem 0;
            padding-left: 0.55rem;
            border-left: 4px solid #334155;
        }
        .mgr-section-title {
            font-size: 1.02rem;
            font-weight: 700;
            color: #92400E;
            margin: 0.6rem 0 0.45rem 0;
            padding-left: 0.55rem;
            border-left: 4px solid #D97706;
        }
        div[data-testid="stVerticalBlock"]:has(> div.element-container > div.stMarkdown > div.mgr-box-marker) {
            background-color: #FFFBEB;
            border: 1.5px solid #F59E0B;
            border-radius: 10px;
            padding: 0.85rem 1rem;
        }
        input[type="password"] {
            font-size: 1.45rem !important;
            letter-spacing: 0.22em !important;
            font-weight: 800 !important;
            line-height: 1.2 !important;
        }
        input[type="password"]::placeholder {
            font-size: 0.88rem !important;
            letter-spacing: normal !important;
            font-weight: 400 !important;
        }
        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 0.75rem 1rem;
        }
        .stButton > button, .stFormSubmitButton > button {
            border-radius: 8px;
            font-weight: 600;
            min-height: 2.45rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_clean_style()


def get_payroll_period(ref_date: datetime.date, start_day: int = 5):
    if ref_date.day >= start_day:
        m_start = ref_date.replace(day=start_day)
        if ref_date.month == 12:
            next_m = ref_date.replace(year=ref_date.year + 1, month=1, day=start_day)
        else:
            next_m = ref_date.replace(month=ref_date.month + 1, day=start_day)
        m_end = next_m - datetime.timedelta(days=1)
    else:
        if ref_date.month == 1:
            m_start = ref_date.replace(year=ref_date.year - 1, month=12, day=start_day)
        else:
            m_start = ref_date.replace(month=ref_date.month - 1, day=start_day)
        m_end = ref_date.replace(day=start_day) - datetime.timedelta(days=1)
    return m_start, m_end


def get_recent_payroll_months(base_date: datetime.date, start_day: int = 5, count: int = 6):
    options = {}
    cur_start, cur_end = get_payroll_period(base_date, start_day)
    for i in range(count):
        tag = "이번 정산월" if i == 0 else f"{i}개월 전"
        label = f"{cur_start.strftime('%Y년 %m월분')} ({cur_start.strftime('%m/%d')}~{cur_end.strftime('%m/%d')}) · {tag}"
        options[label] = (cur_start, cur_end)
        prev_ref = cur_start - datetime.timedelta(days=1)
        cur_start, cur_end = get_payroll_period(prev_ref, start_day)
    return options


def mins_to_hm(total_mins: int) -> str:
    return f"{total_mins // 60:02d}:{total_mins % 60:02d}"


def mins_to_korean(total_mins: int) -> str:
    return f"{total_mins // 60}시간 {total_mins % 60}분"


def format_date_with_weekday(d_str: str) -> str:
    weekdays_short = ["월", "화", "수", "목", "금", "토", "일"]
    try:
        dt = datetime.datetime.strptime(str(d_str).strip(), "%Y-%m-%d").date()
        return f"{dt.strftime('%m-%d')} ({weekdays_short[dt.weekday()]})"
    except Exception:
        return str(d_str)[5:] if len(str(d_str)) >= 10 else str(d_str)


def send_telegram_notice(app_cfg: dict, store_key: str, text: str):
    bot_token = app_cfg.get("telegram_bot_token", "").strip()
    chat_id = app_cfg.get("telegram_chat_id", "").strip()
    if bot_token and chat_id:
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=4,
            )
        except Exception:
            pass


@st.cache_data(ttl=20, show_spinner="근태 데이터를 불러오는 중...")
def load_db_sheets(db_id: str):
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    titles = [s.title.strip() for s in ss.worksheets()]

    target_tabs = [t for t in ["파트타임", "정규직", "통합근태DB"] if t in titles]
    values_map = {}
    if target_tabs:
        res = ss.values_batch_get([f"'{t}'!A:Z" for t in target_tabs])
        for tab_name, vr in zip(target_tabs, res.get("valueRanges", [])):
            values_map[tab_name] = vr.get("values", [])

    def parse_rows(rows: list, with_row_num: bool = False):
        out = []
        if len(rows) >= 2:
            headers = [c.strip() for c in rows[0]]
            for idx, r in enumerate(rows[1:], start=2):
                row_d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
                if any(row_d.values()):
                    if with_row_num:
                        row_d["_sheet_row"] = idx
                    out.append(row_d)
        return pd.DataFrame(out)

    df_emp = parse_rows(values_map.get("파트타임", []))
    df_reg = parse_rows(values_map.get("정규직", []))
    df_att = parse_rows(values_map.get("통합근태DB", []), with_row_num=True)
    if not df_att.empty:
        df_att = df_att[(df_att["날짜"] != "") & (df_att["이름"] != "")].copy()

    return df_emp, df_reg, df_att


@st.cache_data(ttl=20, show_spinner=False)
def load_regular_changes(db_id: str) -> pd.DataFrame:
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    titles = [s.title.strip() for s in ss.worksheets()]
    tab_name = "정규직근태변동" if "정규직근태변동" in titles else ("정직원근태변동" if "정직원근태변동" in titles else "")
    if not tab_name:
        return pd.DataFrame()
    ws = ss.worksheet(tab_name)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return pd.DataFrame()
    headers = [c.strip() for c in rows[0]]
    out = []
    for idx, r in enumerate(rows[1:], start=2):
        row_d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
        if any(row_d.values()):
            row_d["_sheet_row"] = idx
            out.append(row_d)
    return pd.DataFrame(out)


def _get_or_create_reg_change_ws(db_id: str):
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    titles = [s.title.strip() for s in ss.worksheets()]
    if "정규직근태변동" in titles:
        return ss.worksheet("정규직근태변동")
    if "정직원근태변동" in titles:
        ws = ss.worksheet("정직원근태변동")
        ws.update_title("정규직근태변동")
        return ws
    ws = ss.add_worksheet(title="정규직근태변동", rows=500, cols=8)
    ws.append_row(
        ["발생일", "이름", "구분", "일수_시간", "상세메모", "정산반영여부", "등록일시"],
        value_input_option="RAW",
    )
    return ws


def append_regular_change(db_id: str, app_cfg: dict, store_key: str, row_values: list):
    ws = _get_or_create_reg_change_ws(db_id)
    ws.append_row(row_values, value_input_option="USER_ENTERED")

    store_title = app_cfg.get("store_title", store_key).strip() or store_key
    msg = (
        f"📌 [{store_title} 정규직 근태변동 등록]\n"
        f"• 발생일: {row_values[0]}\n"
        f"• 이름: {row_values[1]}\n"
        f"• 구분: {row_values[2]} ({row_values[3]})\n"
        f"• 사유: {row_values[4] or '없음'}"
    )
    if app_cfg.get("tg_alert_reg_change", "TRUE").upper() == "TRUE":
        send_telegram_notice(app_cfg, store_key, msg)


def update_regular_change(db_id: str, app_cfg: dict, store_key: str, sheet_row: int, row_values: list):
    ws = _get_or_create_reg_change_ws(db_id)
    ws.update(range_name=f"A{sheet_row}:G{sheet_row}", values=[row_values], value_input_option="USER_ENTERED")

    store_title = app_cfg.get("store_title", store_key).strip() or store_key
    msg = (
        f"✏️ [{store_title} 정규직 근태변동 수정]\n"
        f"• 발생일: {row_values[0]}\n"
        f"• 이름: {row_values[1]}\n"
        f"• 변경내용: {row_values[2]} ({row_values[3]})\n"
        f"• 사유: {row_values[4] or '없음'}"
    )
    if app_cfg.get("tg_alert_reg_change", "TRUE").upper() == "TRUE":
        send_telegram_notice(app_cfg, store_key, msg)


def delete_regular_change(db_id: str, app_cfg: dict, store_key: str, sheet_row: int, summary_str: str):
    ws = _get_or_create_reg_change_ws(db_id)
    ws.delete_rows(sheet_row)

    store_title = app_cfg.get("store_title", store_key).strip() or store_key
    msg = f"🗑️ [{store_title} 정규직 근태변동 삭제]\n• 삭제된 내역: {summary_str}"
    if app_cfg.get("tg_alert_reg_change", "TRUE").upper() == "TRUE":
        send_telegram_notice(app_cfg, store_key, msg)


@st.cache_resource
def _daily_health_telegram_tracker():
    return {}


def auto_send_daily_health_telegram(store_key: str, app_cfg: dict, alert_lines: list):
    if not alert_lines or app_cfg.get("tg_alert_health", "TRUE").upper() != "TRUE":
        return
    tracker = _daily_health_telegram_tracker()
    today_s = datetime.date.today().strftime("%Y-%m-%d")
    if tracker.get(store_key) == today_s:
        return

    bot_token = app_cfg.get("telegram_bot_token", "").strip()
    chat_id = app_cfg.get("telegram_chat_id", "").strip()
    store_title = app_cfg.get("store_title", store_key).strip() or store_key
    if bot_token and chat_id:
        clean_lines = [re.sub(r"[*`]", "", x) for x in alert_lines]
        msg = f"🏥 [{store_title} 일일 보건증 갱신 알림 ({today_s})]\n\n" + "\n".join(clean_lines)
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": msg},
                timeout=5,
            )
            if resp.status_code == 200:
                tracker[store_key] = today_s
        except Exception:
            pass


h_col1, h_col2, _, h_col4 = st.columns([0.95, 0.55, 2.7, 0.85], vertical_alignment="center")
with h_col1:
    st.markdown('<div class="app-title">⏱️ 출퇴근기록부</div>', unsafe_allow_html=True)
with h_col2:
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with h_col4:
    selected_store = st.selectbox("매장 선택", list(STORES.keys()), index=0, label_visibility="collapsed")

store_cfg = STORES[selected_store]
app_cfg = load_store_settings(store_cfg["db_id"], selected_store)

try:
    df_emp, df_reg, df_att = load_db_sheets(store_cfg["db_id"])
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

active_mgr_pin = app_cfg.get("manager_pin") or store_cfg["manager_pin"]
payroll_start_day = int(app_cfg.get("payroll_start_day", "5") or 5)
time_step_sec = int(app_cfg.get("att_time_step_min", "10") or 10) * 60
health_alert_days = int(app_cfg.get("health_alert_days", "30") or 30)

today_dt = datetime.date.today()
health_alerts = []
emp_health_warning_map = {}

for gubun_label, df_chk in [("파트타임", df_emp), ("정규직", df_reg)]:
    if df_chk is None or df_chk.empty or "보건증만료일" not in df_chk.columns:
        continue
    for _, r in df_chk.iterrows():
        reg_nm = str(r.get("이름", "")).strip()
        memo_nm = str(r.get("메모", "")).strip()
        st_val = str(r.get("상태", "재직")).strip()
        exp_str = str(r.get("보건증만료일", "")).strip()
        if not reg_nm or st_val == "퇴사" or not exp_str:
            continue
        disp_nm = memo_nm if (gubun_label == "파트타임" and memo_nm and "퇴사" not in memo_nm and len(memo_nm) <= 5) else reg_nm
        try:
            exp_dt = datetime.date.fromisoformat(exp_str[:10])
            d_left = (exp_dt - today_dt).days
            if d_left < 0:
                msg = f"🚨 **[{gubun_label}] {disp_nm}** 님: 보건증 유효기간 **{abs(d_left)}일 경과** (만료일: `{exp_str}`)"
                health_alerts.append(msg)
                emp_health_warning_map[disp_nm] = f"🚨 **{disp_nm}** 님, 보건증 유효기간({exp_str})이 지났습니다! 즉시 재발급 후 매니저에게 제출해 주세요."
            elif d_left <= health_alert_days:
                msg = f"⚠️ **[{gubun_label}] {disp_nm}** 님: 보건증 만료 **D-{d_left}** (만료일: `{exp_str}`)"
                health_alerts.append(msg)
                emp_health_warning_map[disp_nm] = f"⚠️ **{disp_nm}** 님, 보건증 만료일이 **{d_left}일** 남았습니다({exp_str}). 미리 보건소에서 갱신해 주세요!"
        except Exception:
            pass

if health_alerts:
    auto_send_daily_health_telegram(selected_store, app_cfg, health_alerts)
    with st.expander(f"🏥 [필독] 보건증 갱신/만료 대상 직원이 {len(health_alerts)}명 있습니다 (클릭하여 명단 확인)", expanded=True):
        for ha in health_alerts:
            st.markdown(f"- {ha}")

st.markdown('<div class="app-subtitle">📅 조회 및 입력 날짜</div>', unsafe_allow_html=True)

active_emp_names = []
if not df_emp.empty:
    active_df = df_emp[df_emp["상태"] != "퇴사"] if "상태" in df_emp.columns else df_emp
    for _, r in active_df.iterrows():
        reg_name = str(r.get("이름", "")).strip()
        memo_name = str(r.get("메모", "")).strip()
        if not reg_name:
            continue
        if memo_name and "퇴사" not in memo_name and len(memo_name) <= 5:
            real_n = memo_name
        else:
            real_n = reg_name
        if real_n not in active_emp_names:
            active_emp_names.append(real_n)

if not df_att.empty:
    df_att["날짜_dt"] = pd.to_datetime(df_att["날짜"], errors="coerce").dt.date
    df_att["총시간(소수)"] = pd.to_numeric(df_att["총시간(소수)"], errors="coerce").fillna(0.0)

d_c1, d_c2, d_c3 = st.columns([0.85, 0.55, 3.7], vertical_alignment="center")
with d_c1:
    sel_date = st.date_input("조회 및 입력 날짜", value=datetime.date.today(), label_visibility="collapsed")
    date_str = sel_date.strftime("%Y-%m-%d")
with d_c2:
    weekdays_kr = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    w_kr = weekdays_kr[sel_date.weekday()]
    w_color = "#DC2626" if sel_date.weekday() >= 5 else "#1E293B"
    st.markdown(
        f'<div style="font-size:1.25rem; font-weight:800; color:{w_color}; padding-left:0.15rem; white-space:nowrap;">{w_kr}</div>',
        unsafe_allow_html=True,
    )
with d_c3:
    st.markdown(
        '<div style="font-size:0.88rem; color:#475569;">💡 <b>신규 입력</b>: 아래에서 본인 이름 선택 후 시간 저장 &nbsp;|&nbsp; <b>기존 수정</b>: 아래 표에서 해당 줄 체크 후 수정</div>',
        unsafe_allow_html=True,
    )

if "edited_banner" in st.session_state and st.session_state["edited_banner"]:
    st.success(st.session_state["edited_banner"])
    st.session_state["edited_banner"] = ""

top_left, top_right = st.columns([1.68, 1.07])

selected_grid_record = None
last_edited_row = st.session_state.get("last_edited_sheet_row", None)

with top_left:
    st.markdown('<div class="section-title">1. 일 근무현황</div>', unsafe_allow_html=True)
    if not df_att.empty and "날짜" in df_att.columns:
        day_df = df_att[df_att["날짜"] == date_str].copy().reset_index(drop=True)
        if not day_df.empty:
            day_df["확인상태"] = day_df["매니저확인"].apply(
                lambda x: "✅ 확인완료" if str(x).strip().upper() == "TRUE" else "⏳ 대기중"
            )
            show_cols = ["이름", "근무타임", "시작시간", "종료시간", "총시간(h:m)", "확인상태", "비고"]
            valid_cols = [c for c in show_cols if c in day_df.columns]

            prev_sel_rows = []
            grid_state_key = f"att_grid_{selected_store}_{date_str}"
            if grid_state_key in st.session_state:
                prev_sel_rows = st.session_state[grid_state_key].get("selection", {}).get("rows", [])

            def highlight_row(row):
                idx = row.name
                sheet_r = day_df.loc[idx, "_sheet_row"]
                if idx in prev_sel_rows:
                    return ["background-color: #DBEAFE; color: #1E3A8A; font-weight: 600;"] * len(row)
                if last_edited_row is not None and sheet_r == last_edited_row:
                    return ["background-color: #DCFCE7; color: #14532D; font-weight: 600;"] * len(row)
                return [""] * len(row)

            styled_df = day_df[valid_cols].style.apply(highlight_row, axis=1)

            grid_height = max(212, min(len(day_df) * 29 + 38, 340))
            event = st.dataframe(
                styled_df,
                use_container_width=True,
                hide_index=True,
                row_height=28,
                height=grid_height,
                on_select="rerun",
                selection_mode="single-row",
                key=grid_state_key,
            )

            sel_rows = event.selection.rows if event and event.selection else []
            if sel_rows:
                selected_grid_record = day_df.iloc[sel_rows[0]].to_dict()
        else:
            st.info("해당 날짜에 등록된 근무 기록이 없습니다.")
    else:
        st.info("등록된 근무 기록이 없습니다.")

with top_right:
    st.markdown('<div class="mgr-section-title">🔐 매니저 전용 확인</div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="mgr-box-marker" style="display:none;"></div>', unsafe_allow_html=True)
        with st.form(key=f"mgr_pin_form_{selected_store}", border=False):
            p_lbl, p_inp, p_btn = st.columns([0.85, 1.35, 0.65], vertical_alignment="center")
            with p_lbl:
                st.markdown(
                    '<div style="font-size:0.88rem; font-weight:700; color:#78350F; line-height:1.25;">매니저확인<br>비밀번호</div>',
                    unsafe_allow_html=True,
                )
            with p_inp:
                pin_input = st.text_input(
                    "매니저확인 비밀번호",
                    type="password",
                    placeholder="비밀번호 입력",
                    key=f"mgr_pin_top_{selected_store}",
                    label_visibility="collapsed",
                )
            with p_btn:
                st.form_submit_button("확인", use_container_width=True)

        if pin_input == active_mgr_pin:
            t_app, t_unapp, t_reg = st.tabs(["⏳ 미확인 승인", "🔓 승인 해제", "📝 정규직 특근/휴무"])

            with t_app:
                pending_df = (
                    df_att[df_att["매니저확인"].astype(str).str.upper() != "TRUE"].copy()
                    if not df_att.empty
                    else pd.DataFrame()
                )
                if pending_df.empty:
                    st.success("🎉 모든 근태 기록이 확인 완료되었습니다.")
                else:
                    with st.form(key=f"mgr_approve_form_{selected_store}", border=False):
                        select_all = st.checkbox(
                            f"전체 선택 (총 {len(pending_df)}건)",
                            value=True,
                            key=f"chk_all_{selected_store}",
                        )
                        st.divider()
                        row_checks = []
                        for _, r in pending_df.iterrows():
                            chk_label = f"[{r['날짜'][5:]}] **{r['이름']}** ({r.get('근무타임', '')}) `{r['시작시간']}~{r['종료시간']}` ({r['총시간(h:m)']})"
                            checked = st.checkbox(
                                chk_label,
                                value=True,
                                key=f"chk_app_{selected_store}_{r['_sheet_row']}",
                            )
                            row_checks.append((checked, int(r["_sheet_row"]), str(r.get("비고", ""))))

                        submitted_approve = st.form_submit_button(
                            "✅ 선택한 내역 일괄 확인 완료",
                            type="primary",
                            use_container_width=True,
                        )

                    if submitted_approve:
                        approve_targets = [
                            (r_num, old_n)
                            for checked, r_num, old_n in row_checks
                            if (select_all or checked)
                        ]
                        if not approve_targets:
                            st.warning("승인할 항목을 1개 이상 선택해 주세요.")
                        else:
                            with st.spinner("일괄 승인 처리 중..."):
                                gc = get_gspread_client()
                                ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")
                                now_s = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                                now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                batch_payload = [
                                    {
                                        "range": f"H{r_num}:J{r_num}",
                                        "values": [["TRUE", f"{old_n}\n[{now_s}] 매니저 확인 완료".strip(), now_f]],
                                    }
                                    for r_num, old_n in approve_targets
                                ]
                                ws.batch_update(batch_payload, value_input_option="RAW")
                                st.success(f"✅ {len(approve_targets)}건 확인 완료!")
                                load_db_sheets.clear(store_cfg["db_id"])
                                st.rerun()

            with t_unapp:
                if not df_att.empty:
                    approved_day = df_att[
                        (df_att["날짜"] == date_str)
                        & (df_att["매니저확인"].astype(str).str.upper() == "TRUE")
                    ]
                    if approved_day.empty:
                        st.caption(f"{date_str}에 승인 완료된 기록이 없습니다.")
                    else:
                        with st.form(key=f"mgr_unapprove_form_{selected_store}", border=False):
                            unapp_checks = []
                            for _, r in approved_day.iterrows():
                                lbl = f"**{r['이름']}** ({r.get('근무타임', '')}) `{r['시작시간']}~{r['종료시간']}`"
                                chk = st.checkbox(
                                    lbl,
                                    value=False,
                                    key=f"chk_unapp_{selected_store}_{r['_sheet_row']}",
                                )
                                unapp_checks.append((chk, int(r["_sheet_row"]), str(r.get("비고", ""))))

                            submitted_unapp = st.form_submit_button(
                                "🔓 선택한 내역 승인 해제",
                                use_container_width=True,
                            )

                        if submitted_unapp:
                            unapp_targets = [(r_num, old_n) for chk, r_num, old_n in unapp_checks if chk]
                            if not unapp_targets:
                                st.warning("승인 해제할 항목을 선택해 주세요.")
                            else:
                                with st.spinner("승인 해제 처리 중..."):
                                    gc = get_gspread_client()
                                    ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")
                                    now_s = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                                    now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    batch_payload = [
                                        {
                                            "range": f"H{r_num}:J{r_num}",
                                            "values": [["FALSE", f"{old_n}\n[{now_s}] 매니저 확인 해제".strip(), now_f]],
                                        }
                                        for r_num, old_n in unapp_targets
                                    ]
                                    ws.batch_update(batch_payload, value_input_option="RAW")
                                    st.warning(f"🔓 {len(unapp_targets)}건 승인이 해제되었습니다.")
                                    load_db_sheets.clear(store_cfg["db_id"])
                                    st.rerun()

            with t_reg:
                reg_names = []
                if df_reg is not None and not df_reg.empty and "이름" in df_reg.columns:
                    active_reg = df_reg[df_reg["상태"] != "퇴사"] if "상태" in df_reg.columns else df_reg
                    reg_names = [str(n).strip() for n in active_reg["이름"].tolist() if str(n).strip()]

                if not reg_names:
                    st.warning("'정규직' 시트에 등록된 재직 직원이 없습니다.")
                else:
                    with st.form(key=f"reg_change_form_{selected_store}", border=False, clear_on_submit=True):
                        rc1, rc2 = st.columns(2)
                        with rc1:
                            reg_date = st.date_input("발생 날짜", value=sel_date)
                        with rc2:
                            reg_emp = st.selectbox("정규직 선택", options=reg_names)

                        rc3, rc4 = st.columns(2)
                        with rc3:
                            reg_type = st.selectbox("변동 구분", options=REG_CHANGE_TYPES)
                        with rc4:
                            reg_unit = st.selectbox("단위", options=REG_CHANGE_UNITS)

                        reg_memo = st.text_input(
                            "사유 및 정산 메모",
                            placeholder="예: 추가출근:사유 / 개인사정결근:사유 / OO시간추가근무:사유",
                        )
                        submitted_reg = st.form_submit_button(
                            "📌 정규직 특근/휴무 기록 저장",
                            type="primary",
                            use_container_width=True,
                        )

                    if submitted_reg:
                        with st.spinner("기록 저장 및 알림 발송 중..."):
                            now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            row_vals = [
                                reg_date.strftime("%Y-%m-%d"),
                                reg_emp,
                                reg_type,
                                reg_unit,
                                reg_memo.strip(),
                                "대기",
                                now_f,
                            ]
                            append_regular_change(store_cfg["db_id"], app_cfg, selected_store, row_vals)
                            load_regular_changes.clear(store_cfg["db_id"])
                            st.success(f"✅ [{reg_emp}] {reg_date.strftime('%m/%d')} {reg_type} 기록 완료!")
                            st.rerun()

                    df_rc = load_regular_changes(store_cfg["db_id"])
                    if not df_rc.empty and "발생일" in df_rc.columns:
                        cur_s, cur_e = get_payroll_period(datetime.date.today(), start_day=payroll_start_day)
                        df_rc["발생일_dt"] = pd.to_datetime(df_rc["발생일"], errors="coerce").dt.date
                        cur_rc = df_rc[(df_rc["발생일_dt"] >= cur_s) & (df_rc["발생일_dt"] <= cur_e)].sort_values(
                            "발생일", ascending=False
                        )
                        st.caption(f"📋 이번 정산월({cur_s.strftime('%m/%d')}~{cur_e.strftime('%m/%d')}) 등록 내역: {len(cur_rc)}건")
                        if not cur_rc.empty:
                            disp_rc = cur_rc[["발생일", "이름", "구분", "일수_시간", "상세메모"]].copy()
                            disp_rc["발생일"] = disp_rc["발생일"].str[5:]
                            st.dataframe(disp_rc, use_container_width=True, hide_index=True, row_height=26)

                            with st.expander("✏️ 등록 내역 수정 / 삭제", expanded=False):
                                rc_records = cur_rc.to_dict("records")
                                rc_labels = [
                                    f"[{r['발생일'][5:]}] {r['이름']} | {r['구분']} ({r['일수_시간']}) - {r.get('상세메모', '')}"
                                    for r in rc_records
                                ]
                                sel_rc_idx = st.selectbox(
                                    "수정 또는 삭제할 내역 선택",
                                    options=range(len(rc_labels)),
                                    format_func=lambda i: rc_labels[i],
                                    key=f"sel_edit_rc_{selected_store}",
                                )
                                target_rc = rc_records[sel_rc_idx]
                                target_rc_row = int(target_rc["_sheet_row"])

                                try:
                                    def_rc_dt = datetime.date.fromisoformat(str(target_rc["발생일"])[:10])
                                except Exception:
                                    def_rc_dt = sel_date

                                def_emp_idx = reg_names.index(target_rc["이름"]) if target_rc["이름"] in reg_names else 0
                                def_type_idx = REG_CHANGE_TYPES.index(target_rc["구분"]) if target_rc["구분"] in REG_CHANGE_TYPES else 0
                                def_unit_idx = REG_CHANGE_UNITS.index(target_rc["일수_시간"]) if target_rc["일수_시간"] in REG_CHANGE_UNITS else 0

                                ec1, ec2 = st.columns(2)
                                with ec1:
                                    edit_rc_date = st.date_input("발생 날짜 수정", value=def_rc_dt, key=f"ed_rc_dt_{selected_store}_{target_rc_row}")
                                with ec2:
                                    edit_rc_emp = st.selectbox("정규직 수정", options=reg_names, index=def_emp_idx, key=f"ed_rc_emp_{selected_store}_{target_rc_row}")

                                ec3, ec4 = st.columns(2)
                                with ec3:
                                    edit_rc_type = st.selectbox("변동 구분 수정", options=REG_CHANGE_TYPES, index=def_type_idx, key=f"ed_rc_tp_{selected_store}_{target_rc_row}")
                                with ec4:
                                    edit_rc_unit = st.selectbox("단위 수정", options=REG_CHANGE_UNITS, index=def_unit_idx, key=f"ed_rc_un_{selected_store}_{target_rc_row}")

                                edit_rc_memo = st.text_input(
                                    "사유 및 정산 메모 수정",
                                    value=str(target_rc.get("상세메모", "")),
                                    key=f"ed_rc_mm_{selected_store}_{target_rc_row}",
                                )

                                b_save_rc, b_del_rc = st.columns(2)
                                with b_save_rc:
                                    if st.button("💾 수정 반영", type="primary", use_container_width=True, key=f"btn_save_rc_{selected_store}_{target_rc_row}"):
                                        with st.spinner("수정 내용 반영 중..."):
                                            now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            upd_vals = [
                                                edit_rc_date.strftime("%Y-%m-%d"),
                                                edit_rc_emp,
                                                edit_rc_type,
                                                edit_rc_unit,
                                                edit_rc_memo.strip(),
                                                str(target_rc.get("정산반영여부", "대기")),
                                                now_f,
                                            ]
                                            update_regular_change(store_cfg["db_id"], app_cfg, selected_store, target_rc_row, upd_vals)
                                            load_regular_changes.clear(store_cfg["db_id"])
                                            st.success("수정 내용이 반영되었습니다.")
                                            st.rerun()
                                with b_del_rc:
                                    if st.button("🗑️ 내역 삭제", use_container_width=True, key=f"btn_del_rc_{selected_store}_{target_rc_row}"):
                                        with st.spinner("내역 삭제 중..."):
                                            delete_regular_change(
                                                store_cfg["db_id"],
                                                app_cfg,
                                                selected_store,
                                                target_rc_row,
                                                rc_labels[sel_rc_idx],
                                            )
                                            load_regular_changes.clear(store_cfg["db_id"])
                                            st.warning("선택한 내역이 삭제되었습니다.")
                                            st.rerun()

        elif pin_input:
            st.error("비밀번호가 일치하지 않습니다.")
        else:
            st.caption("매니저 확인 전까지는 위의 표에서 행을 체크해 수정할 수 있습니다.")

if "form_reset_ver" not in st.session_state:
    st.session_state["form_reset_ver"] = 0

if st.session_state.get("reset_emp_selector", False):
    st.session_state["att_emp_selector"] = EMP_PLACEHOLDER
    st.session_state["form_reset_ver"] += 1
    st.session_state["reset_emp_selector"] = False

left_col, right_col = st.columns([1.5, 1.0])

with left_col:
    if selected_grid_record is not None:
        mode = "기존 수정"
        target_sheet_row = int(selected_grid_record["_sheet_row"])
        old_record = selected_grid_record
        real_emp_name = str(old_record.get("이름", "")).strip()
        is_emp_selected = True
    else:
        mode = "신규 등록"
        target_sheet_row = None
        old_record = {}
        real_emp_name = ""
        is_emp_selected = False

    st.markdown('<div class="section-title">2. 출퇴근 시간 입력/수정</div>', unsafe_allow_html=True)

    with st.container(border=True):
        if not active_emp_names:
            st.warning("'파트타임' 탭에 재직 중인 직원이 없습니다.")
            st.stop()

        if mode == "기존 수정":
            st.info(
                f"🔵 표에서 선택된 **[{real_emp_name}] {old_record.get('근무타임', '')} ({old_record.get('시작시간')}~{old_record.get('종료시간')})** 기록을 수정 중입니다. (신규 입력으로 돌아가려면 위 표의 체크를 해제하세요)"
            )

        is_locked = (mode == "기존 수정") and (str(old_record.get("매니저확인", "")).strip().upper() == "TRUE")
        if is_locked:
            st.error("🚫 매니저 확인이 완료된 기록은 수정할 수 없습니다. 수정이 필요하면 매니저에게 확인 해제를 요청하세요.")

        default_shift_idx = 0
        if mode == "기존 수정":
            old_t = str(old_record.get("근무타임", "")).strip()
            if old_t in SHIFT_OPTIONS:
                default_shift_idx = SHIFT_OPTIONS.index(old_t)
        else:
            default_shift_idx = 1 if sel_date.weekday() >= 5 else 0

        if mode == "기존 수정":
            try:
                def_s = datetime.datetime.strptime(str(old_record.get("시작시간", "00:00")), "%H:%M").time()
                def_e = datetime.datetime.strptime(str(old_record.get("종료시간", "00:00")), "%H:%M").time()
            except Exception:
                def_s, def_e = datetime.time(0, 0), datetime.time(0, 0)
        else:
            def_s, def_e = datetime.time(0, 0), datetime.time(0, 0)

        c_name, c1, c2, c3 = st.columns([1.15, 1.0, 0.92, 0.92])
        with c_name:
            if mode == "기존 수정":
                st.text_input("본인 이름", value=real_emp_name, disabled=True)
            else:
                emp_select_options = [EMP_PLACEHOLDER] + active_emp_names
                chosen_emp = st.selectbox(
                    "본인 이름 선택",
                    options=emp_select_options,
                    index=0,
                    key="att_emp_selector",
                )
                if chosen_emp != EMP_PLACEHOLDER:
                    real_emp_name = chosen_emp
                    is_emp_selected = True
                else:
                    real_emp_name = ""
                    is_emp_selected = False

        if is_emp_selected and real_emp_name in emp_health_warning_map:
            st.error(emp_health_warning_map[real_emp_name])

        inputs_disabled = is_locked or (not is_emp_selected)
        w_key_sfx = f"{selected_store}_{mode}_{target_sheet_row}_{st.session_state['form_reset_ver']}"

        with c1:
            shift_type = st.selectbox(
                "근무 타임",
                options=SHIFT_OPTIONS,
                index=default_shift_idx,
                disabled=inputs_disabled,
                key=f"shift_{w_key_sfx}",
            )
        with c2:
            start_t = st.time_input(
                "시작시간",
                value=def_s,
                step=time_step_sec,
                disabled=inputs_disabled,
                key=f"start_{w_key_sfx}",
            )
        with c3:
            end_t = st.time_input(
                "종료시간",
                value=def_e,
                step=time_step_sec,
                disabled=inputs_disabled,
                key=f"end_{w_key_sfx}",
            )

        dt_s = datetime.datetime.combine(sel_date, start_t)
        dt_e = datetime.datetime.combine(sel_date, end_t)
        if dt_e < dt_s:
            dt_e += datetime.timedelta(days=1)
        diff_mins = int((dt_e - dt_s).total_seconds() // 60)
        hm_str = mins_to_hm(diff_mins)
        dec_hours = round(diff_mins / 60.0, 2)

        if not is_emp_selected:
            st.warning("☝️ 먼저 좌측의 **본인 이름 선택**을 눌러 이름을 고르면 시간 입력칸이 활성화됩니다.")
        elif diff_mins > 0:
            st.success(f"⏱️ 계산된 근무시간: **{hm_str}** ({mins_to_korean(diff_mins)})")
        else:
            st.warning("시작시간과 종료시간을 입력해 주세요.")

        st.markdown(
            """
            <div style="background-color:#FEF3C7; border:1px solid #F59E0B; border-radius:7px; padding:0.48rem 0.75rem; margin:0.35rem 0 0.55rem 0; color:#92400E; font-weight:700; font-size:0.88rem;">
                ⚠️ 근무시간 수정 시 위의 표에서 해당 내역을 먼저 체크한 후 수정하세요.
            </div>
            """,
            unsafe_allow_html=True,
        )

        if mode == "기존 수정":
            edit_reason = st.text_input(
                "🚨 수정 사유 (필수 입력)",
                placeholder="예: 퇴근 시간 입력 오타 정정",
                disabled=inputs_disabled,
                key=f"reason_{w_key_sfx}",
            )
            memo_val = str(old_record.get("비고", ""))
        else:
            edit_reason = ""
            memo_val = st.text_input(
                "비고 / 특이사항 (선택)",
                placeholder="예: 홀 마감 지원, 대타 등",
                disabled=inputs_disabled,
                key=f"memo_{w_key_sfx}",
            )

        can_submit = (
            is_emp_selected
            and (not is_locked)
            and (diff_mins > 0)
            and (mode == "신규 등록" or len(edit_reason.strip()) > 0)
        )
        btn_label = "💾 출퇴근 시간 저장하기" if mode == "신규 등록" else "🔄 수정 내역 반영하기"

        if st.button(btn_label, type="primary", use_container_width=True, disabled=not can_submit):
            with st.spinner("출퇴근 기록을 저장하는 중..."):
                now_full = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                now_short = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                gc = get_gspread_client()
                ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")

                s_str = start_t.strftime("%H:%M")
                e_str = end_t.strftime("%H:%M")

                if mode == "기존 수정":
                    logs = []
                    if str(old_record.get("시작시간", "")) != s_str:
                        logs.append(f"[{now_short}] 시작시간 변경: {old_record.get('시작시간')} → {s_str}")
                    if str(old_record.get("종료시간", "")) != e_str:
                        logs.append(f"[{now_short}] 종료시간 변경: {old_record.get('종료시간')} → {e_str}")
                    logs.append(f"[{now_short}] 수정사유: {edit_reason.strip()}")

                    prev_note = memo_val.strip()
                    new_note = f"{prev_note}\n" + "\n".join(logs) if prev_note else "\n".join(logs)

                    row_values = [date_str, real_emp_name, shift_type, s_str, e_str, hm_str, dec_hours, "FALSE", new_note, now_full]
                    ws.update(range_name=f"A{target_sheet_row}:J{target_sheet_row}", values=[row_values], value_input_option="USER_ENTERED")

                    st.session_state["last_edited_sheet_row"] = target_sheet_row
                    st.session_state["edited_banner"] = f"✅ [{real_emp_name}] 님의 근무 기록({s_str}~{e_str}) 수정이 완료되었습니다."
                else:
                    row_values = [date_str, real_emp_name, shift_type, s_str, e_str, hm_str, dec_hours, "FALSE", memo_val.strip(), now_full]
                    ws.append_row(row_values, value_input_option="USER_ENTERED")
                    st.session_state["last_edited_sheet_row"] = None
                    st.session_state["edited_banner"] = f"✅ [{real_emp_name}] 님의 근무 기록({s_str}~{e_str})이 저장되었습니다."

                st.session_state["reset_emp_selector"] = True
                load_db_sheets.clear(store_cfg["db_id"])
                st.rerun()

with right_col:
    if not is_emp_selected:
        st.markdown('<div class="section-title">3. 개인별 월별 근무시간 조회</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.info("👈 좌측 **'2. 출퇴근 시간 입력/수정'**에서 **본인 이름**을 선택하면, 여기에 본인의 이번 달 누적 출근일수와 근무시간이 표시됩니다.")
    else:
        st.markdown(f'<div class="section-title">3. {real_emp_name} 님 월별 근무시간 조회</div>', unsafe_allow_html=True)

        month_options = get_recent_payroll_months(datetime.date.today(), start_day=payroll_start_day, count=6)
        sel_month_label = st.selectbox("조회할 정산월 선택", options=list(month_options.keys()), index=0)
        m_start, m_end = month_options[sel_month_label]

        if not df_att.empty and "이름" in df_att.columns:
            emp_all = df_att[df_att["이름"] == real_emp_name]
            m_df = emp_all[(emp_all["날짜_dt"] >= m_start) & (emp_all["날짜_dt"] <= m_end)]
            m_mins = int(round(m_df["총시간(소수)"].sum() * 60))
            work_days = m_df["날짜"].nunique() if not m_df.empty else 0

            st.metric(
                label="누적 출근일 · 근무시간",
                value=f"{work_days}일 · {mins_to_korean(m_mins)}",
            )

            with st.expander(f"📋 세부 근무 내역({len(m_df)}건)", expanded=False):
                if not m_df.empty:
                    m_disp = m_df.sort_values("날짜", ascending=False).copy()
                    m_disp["날짜"] = m_disp["날짜"].apply(format_date_with_weekday)
                    m_disp["근무시간"] = m_disp["시작시간"] + "~" + m_disp["종료시간"]
                    m_disp["상태"] = m_disp["매니저확인"].apply(
                        lambda x: "✅ 확인" if str(x).strip().upper() == "TRUE" else "⏳ 대기"
                    )
                    m_disp = m_disp.rename(columns={"근무타임": "구분", "총시간(h:m)": "총시간"})
                    st.dataframe(
                        m_disp[["날짜", "구분", "근무시간", "총시간", "상태"]],
                        use_container_width=True,
                        hide_index=True,
                        row_height=28,
                    )
                else:
                    st.caption("선택한 정산월에 등록된 근무 기록이 없습니다.")
        else:
            st.caption("누적 근무 내역이 없습니다.")
