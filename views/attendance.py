"""
================================================================================
[파일명] views/attendance.py
[역할] 매장 직원 및 매니저 공용 '일일 출퇴근기록부 및 월별 근무시간 조회' 페이지
================================================================================
"""

import re
import datetime
import pandas as pd
import streamlit as st
from store_registry import (
    load_all_stores,
    load_store_settings,
    get_gspread_client,
    dispatch_telegram_alert,
)
from ui_styles import apply_base_theme, render_section_banner

STORES = load_all_stores()
KST = datetime.timezone(datetime.timedelta(hours=9))
SHIFT_OPTIONS = ["평일", "주말(점심)", "주말(저녁)", "기타"]
EMP_PLACEHOLDER = "이름 선택"
REG_CHANGE_TYPES = ["➕ 추가출근", "➖ 기타휴무", "🔄 대체휴무"]
REG_CHANGE_UNITS = ["1일", "시간단위(사유란 기재)"]


def kst_now() -> datetime.datetime:
    return datetime.datetime.now(KST)


def kst_today() -> datetime.date:
    return kst_now().date()


def apply_clean_style():
    apply_base_theme(max_width=1380)
    st.markdown(
        """
        <style>
        input[type="password"] {
            font-size: 1.35rem !important;
            letter-spacing: 0.2em !important;
            font-weight: 800 !important;
            line-height: 1.2 !important;
        }
        input[type="password"]::placeholder {
            font-size: 0.88rem !important;
            letter-spacing: normal !important;
            font-weight: 500 !important;
        }
        /* 상단 퀵 팝업 버튼 상태별 강조 색상 */
        .st-key-qbtn_pay_alert button {
            background-color: #059669 !important;
            color: #FFFFFF !important;
            border: 2px solid #047857 !important;
            box-shadow: 0 2px 10px rgba(5, 150, 105, 0.32) !important;
        }
        .st-key-qbtn_pay_alert button:hover {
            background-color: #047857 !important;
            color: #FFFFFF !important;
        }
        .st-key-qbtn_health_alert button {
            background-color: #DC2626 !important;
            color: #FFFFFF !important;
            border: 2px solid #B91C1C !important;
            box-shadow: 0 2px 10px rgba(220, 38, 38, 0.30) !important;
        }
        .st-key-qbtn_health_alert button:hover {
            background-color: #B91C1C !important;
            color: #FFFFFF !important;
        }
        .st-key-qbtn_mgr_alert button {
            background-color: #D97706 !important;
            color: #FFFFFF !important;
            border: 2px solid #B45309 !important;
            box-shadow: 0 2px 10px rgba(217, 119, 6, 0.30) !important;
        }
        .st-key-qbtn_mgr_alert button:hover {
            background-color: #B45309 !important;
            color: #FFFFFF !important;
        }
        .st-key-qbtn_pay_idle button,
        .st-key-qbtn_health_idle button,
        .st-key-qbtn_mgr_idle button {
            background-color: #F8FAFC !important;
            color: #475569 !important;
            border: 1.5px solid #CBD5E1 !important;
        }
        .st-key-qbtn_pay_idle button:hover,
        .st-key-qbtn_health_idle button:hover,
        .st-key-qbtn_mgr_idle button:hover {
            background-color: #F1F5F9 !important;
            color: #0F172A !important;
            border-color: #94A3B8 !important;
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
    """정규직 특근·휴무 등록/수정/삭제 시 설정된 수신 대상(대표/매니저/모두)에게 텔레그램 알림을 발송합니다."""
    dispatch_telegram_alert(app_cfg, "tg_target_reg_change", text, default_target="대표")


@st.cache_data(ttl=20, show_spinner="근태 데이터를 불러오는 중...")
def load_db_sheets(db_id: str):
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    titles = [s.title.strip() for s in ss.worksheets()]

    target_tabs = [t for t in ["파트타임", "정규직", "통합근태DB", "입금확인로그", "주간스케줄"] if t in titles]
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
    df_pay = parse_rows(values_map.get("입금확인로그", []), with_row_num=True)
    df_sched = parse_rows(values_map.get("주간스케줄", []))

    return df_emp, df_reg, df_att, df_pay, df_sched


def mark_payments_confirmed(db_id: str, sheet_rows: list):
    """입금확인로그 탭의 선택된 행들의 확인여부를 '확인완료'로 일괄 변경합니다."""
    if not sheet_rows:
        return
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    ws = ss.worksheet("입금확인로그")
    headers = [c.strip() for c in ws.row_values(1)]
    status_idx = headers.index("확인여부") if "확인여부" in headers else 5
    col_letter = chr(ord("A") + status_idx)
    batch_payload = [
        {"range": f"{col_letter}{int(r_num)}", "values": [["확인완료"]]}
        for r_num in sheet_rows
    ]
    ws.batch_update(batch_payload, value_input_option="RAW")


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
    send_telegram_notice(app_cfg, store_key, msg)


def delete_regular_change(db_id: str, app_cfg: dict, store_key: str, sheet_row: int, summary_str: str):
    ws = _get_or_create_reg_change_ws(db_id)
    ws.delete_rows(sheet_row)

    store_title = app_cfg.get("store_title", store_key).strip() or store_key
    msg = f"🗑️ [{store_title} 정규직 근태변동 삭제]\n• 삭제된 내역: {summary_str}"
    send_telegram_notice(app_cfg, store_key, msg)


@st.cache_resource
def _daily_health_telegram_tracker():
    return {}


def auto_send_daily_health_telegram(store_key: str, app_cfg: dict, alert_lines: list):
    if not alert_lines:
        return
    tracker = _daily_health_telegram_tracker()
    today_s = kst_today().strftime("%Y-%m-%d")
    if tracker.get(store_key) == today_s:
        return

    store_title = app_cfg.get("store_title", store_key).strip() or store_key
    clean_lines = [re.sub(r"[*`]", "", x) for x in alert_lines]
    msg = f"🏥 [{store_title} 일일 보건증 갱신 알림 ({today_s})]\n\n" + "\n".join(clean_lines)
    dispatch_telegram_alert(app_cfg, "tg_target_health", msg, default_target="모두")
    tracker[store_key] = today_s


h_col1, h_date, h_day, h_col2, h_col3 = st.columns([1.35, 1.15, 0.55, 1.0, 0.75], vertical_alignment="center")
with h_col1:
    st.markdown('<div class="app-title" style="white-space:nowrap;">▪&nbsp;&nbsp;출퇴근기록부</div>', unsafe_allow_html=True)
with h_col2:
    selected_store = st.selectbox("매장 선택", list(STORES.keys()), index=0, label_visibility="collapsed")
with h_col3:
    if st.button("새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

date_widget_key = f"att_sel_date_{selected_store}"
with h_date:
    sel_date = st.date_input("조회 및 입력 날짜", value=kst_today(), key=date_widget_key, label_visibility="collapsed")
    date_str = sel_date.strftime("%Y-%m-%d")
with h_day:
    weekdays_kr = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    w_kr = weekdays_kr[sel_date.weekday()]
    w_color = "#DC2626" if sel_date.weekday() >= 5 else "#1E293B"
    st.markdown(
        f'<div style="font-size:1.12rem; font-weight:800; color:{w_color}; white-space:nowrap;">{w_kr}</div>',
        unsafe_allow_html=True,
    )

store_cfg = STORES[selected_store]
app_cfg = load_store_settings(store_cfg["db_id"], selected_store)

try:
    df_emp, df_reg, df_att, df_pay, df_sched = load_db_sheets(store_cfg["db_id"])
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

active_mgr_pin = app_cfg.get("manager_pin") or store_cfg["manager_pin"]
payroll_start_day = int(app_cfg.get("payroll_start_day", "5") or 5)
time_step_sec = int(app_cfg.get("att_time_step_min", "10") or 10) * 60
health_alert_days = int(app_cfg.get("health_alert_days", "30") or 30)

today_dt = kst_today()
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

# 실시간 계좌입금 · 지역화폐 결제 집계 (날짜+시간 최신순 정렬)
show_pay_board = app_cfg.get("show_payment_board", "TRUE").upper() == "TRUE"
today_prefix = today_dt.strftime("%Y-%m-%d")
today_pay_df = pd.DataFrame()
if show_pay_board and df_pay is not None and not df_pay.empty and "수신일시" in df_pay.columns:
    _pay_tmp = df_pay.copy()
    _pay_tmp["_dt_sort"] = pd.to_datetime(_pay_tmp["수신일시"].astype(str).str.strip(), errors="coerce")
    _is_today = (_pay_tmp["_dt_sort"].dt.date == today_dt) | (
        _pay_tmp["_dt_sort"].isna() & _pay_tmp["수신일시"].astype(str).str.startswith(today_prefix)
    )
    _sort_cols = ["_dt_sort", "_sheet_row"] if "_sheet_row" in _pay_tmp.columns else ["_dt_sort"]
    today_pay_df = (
        _pay_tmp[_is_today]
        .sort_values(_sort_cols, ascending=[False] * len(_sort_cols), na_position="last")
        .head(30)
        .reset_index(drop=True)
    )

pending_pay_rows = []
if not today_pay_df.empty and "확인여부" in today_pay_df.columns:
    pending_pay_rows = today_pay_df[today_pay_df["확인여부"].astype(str).str.strip() != "확인완료"]["_sheet_row"].tolist()
elif not today_pay_df.empty and "_sheet_row" in today_pay_df.columns:
    pending_pay_rows = today_pay_df["_sheet_row"].tolist()
pending_pay_cnt = len(pending_pay_rows)

# 매니저 미승인 파트타임 근태 집계
pending_att_df = (
    df_att[df_att["매니저확인"].astype(str).str.upper() != "TRUE"].copy()
    if (df_att is not None and not df_att.empty and "매니저확인" in df_att.columns)
    else pd.DataFrame()
)
pending_att_cnt = len(pending_att_df)


# ==============================================================================
# 팝업 다이얼로그 정의 (계좌입금·지역화폐 / 보건증 / 매니저 전용)
# ==============================================================================
@st.dialog("실시간 계좌입금 · 지역화폐 결제 확인", width="large")
def open_payment_dialog():
    biz_only = app_cfg.get("payment_biz_hours_only", "TRUE").upper() == "TRUE"
    if biz_only:
        if today_dt.weekday() >= 5:
            wk_s = app_cfg.get("payment_wknd_biz_start", "12:00")
            wk_e = app_cfg.get("payment_wknd_biz_end", "22:00")
            brk_s = app_cfg.get("payment_wknd_break_start", "15:00").strip()
            brk_e = app_cfg.get("payment_wknd_break_end", "17:00").strip()
            brk_txt = f", 브레이크 {brk_s}~{brk_e} 제외" if (brk_s and brk_e) else ""
            biz_info_txt = f"주말 영업시간({wk_s}~{wk_e}{brk_txt}) 내 "
        else:
            wd_s = app_cfg.get("payment_biz_start", "16:00")
            wd_e = app_cfg.get("payment_biz_end", "22:00")
            biz_info_txt = f"평일 영업시간({wd_s}~{wd_e}) 내 "
    else:
        biz_info_txt = ""

    st.caption(f"{biz_info_txt}우리은행 계좌입금 및 지역화폐 결제 알림만 자동 기록됩니다.")
    pb_c1, pb_c2 = st.columns(2)
    with pb_c1:
        if st.button("내역 새로고침", key=f"dlg_refresh_pay_{selected_store}", use_container_width=True):
            load_db_sheets.clear(store_cfg["db_id"])
            st.rerun()
    with pb_c2:
        if pending_pay_cnt > 0:
            if st.button(f"미확인 {pending_pay_cnt}건 확인완료", key=f"dlg_confirm_pay_{selected_store}", type="primary", use_container_width=True):
                with st.spinner("확인 처리 중..."):
                    mark_payments_confirmed(store_cfg["db_id"], pending_pay_rows)
                    load_db_sheets.clear(store_cfg["db_id"])
                    st.session_state["edited_banner"] = f"계좌입금·지역화폐 미확인 {pending_pay_cnt}건을 확인완료 처리했습니다."
                    st.rerun()

    if today_pay_df.empty:
        st.info("오늘 수신된 계좌입금 또는 지역화폐 결제 내역이 아직 없습니다.")
    else:
        def _fmt_pay_gubun(g):
            gs = str(g).strip()
            if not gs:
                return "계좌입금"
            if "chak" in gs.lower() or "상품권" in gs:
                return "지역화폐"
            return gs

        def _fmt_pay_amt(v):
            digits = re.sub(r"[^\d-]", "", str(v))
            try:
                return f"{int(digits):,}원" if digits else str(v)
            except ValueError:
                return str(v)

        def _fmt_pay_dt(row_idx):
            dt_val = today_pay_df.at[row_idx, "_dt_sort"] if "_dt_sort" in today_pay_df.columns else pd.NaT
            if pd.notna(dt_val):
                return dt_val.strftime("%Y-%m-%d %H:%M:%S")
            return str(today_pay_df.at[row_idx, "수신일시"]).strip()

        pay_disp = pd.DataFrame({
            "일시": [_fmt_pay_dt(i) for i in range(len(today_pay_df))],
            "구분": today_pay_df.get("구분", pd.Series([""] * len(today_pay_df))).apply(_fmt_pay_gubun),
            "입금자 / 상세": today_pay_df.get("입금자_상세", pd.Series([""] * len(today_pay_df))),
            "금액": today_pay_df.get("금액", pd.Series([""] * len(today_pay_df))).apply(_fmt_pay_amt),
            "상태": today_pay_df.get("확인여부", pd.Series(["대기"] * len(today_pay_df))).apply(
                lambda x: "✓ 확인완료" if str(x).strip() == "확인완료" else "● 미확인"
            ),
        })
        st.dataframe(pay_disp, use_container_width=True, hide_index=True, row_height=30)


@st.dialog("보건증 갱신 · 만료 알림", width="large")
def open_health_dialog():
    if health_alerts:
        st.warning(f"보건증 갱신 또는 만료 확인이 필요한 재직 직원이 **{len(health_alerts)}명** 있습니다.")
        for ha in health_alerts:
            st.markdown(f"- {ha}")
        st.caption("직원이 새 보건증을 제출하면 '직원관리' 메뉴에서 보건증 만료일을 갱신해 주세요.")
    else:
        st.success("현재 재직 중인 모든 직원의 보건증이 유효합니다.")


@st.dialog("매니저 전용 확인", width="large")
def open_manager_dialog(cur_sel_date: datetime.date, cur_date_str: str):
    mgr_unlock_key = f"att_mgr_dialog_unlocked_{selected_store}"
    is_mgr_open = st.session_state.get("authenticated", False) or st.session_state.get(mgr_unlock_key, False)

    if not is_mgr_open:
        st.caption("파트타임 근태 일괄 승인·해제 및 정규직 특근/휴무 등록을 위해 매니저 PIN을 입력하세요.")
        with st.form(key=f"dlg_mgr_pin_form_{selected_store}", border=False):
            p_inp, p_btn = st.columns([2.1, 0.9], vertical_alignment="center")
            with p_inp:
                pin_input = st.text_input(
                    "매니저확인 비밀번호",
                    type="password",
                    placeholder="매니저 PIN 입력",
                    key=f"dlg_mgr_pin_inp_{selected_store}",
                    label_visibility="collapsed",
                )
            with p_btn:
                submitted_pin = st.form_submit_button("확인", type="primary", use_container_width=True)

        if submitted_pin:
            if pin_input == active_mgr_pin:
                st.session_state[mgr_unlock_key] = True
                is_mgr_open = True
            else:
                st.error("비밀번호가 일치하지 않습니다.")

    if not is_mgr_open:
        return

    top_m1, top_m2 = st.columns([3.0, 1.0], vertical_alignment="center")
    with top_m1:
        st.caption(f"[{selected_store}] 매니저 인증됨 · 기준 날짜: {cur_date_str}")
    with top_m2:
        if st.button("잠금", key=f"dlg_mgr_lock_{selected_store}", use_container_width=True):
            st.session_state[mgr_unlock_key] = False
            st.rerun()

    t_app, t_unapp, t_reg = st.tabs([
        f"미확인 승인 ({pending_att_cnt})",
        "승인 해제",
        "정규직 특근/휴무",
    ])

    with t_app:
        if pending_att_df.empty:
            st.success("🎉 모든 근태 기록이 확인 완료되었습니다.")
        else:
            with st.form(key=f"dlg_mgr_approve_form_{selected_store}", border=False):
                select_all = st.checkbox(
                    f"전체 선택 (총 {len(pending_att_df)}건)",
                    value=True,
                    key=f"dlg_chk_all_{selected_store}",
                )
                st.divider()
                row_checks = []
                for _, r in pending_att_df.iterrows():
                    chk_label = f"[{r['날짜'][5:]}] **{r['이름']}** ({r.get('근무타임', '')}) `{r['시작시간']}~{r['종료시간']}` ({r['총시간(h:m)']})"
                    checked = st.checkbox(
                        chk_label,
                        value=True,
                        key=f"dlg_chk_app_{selected_store}_{r['_sheet_row']}",
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
                        now_s = kst_now().strftime("%m/%d %H:%M:%S")
                        now_f = kst_now().strftime("%Y-%m-%d %H:%M:%S")
                        batch_payload = [
                            {
                                "range": f"H{r_num}:J{r_num}",
                                "values": [["TRUE", f"{old_n}\n[{now_s}] 매니저 확인 완료".strip(), now_f]],
                            }
                            for r_num, old_n in approve_targets
                        ]
                        ws.batch_update(batch_payload, value_input_option="RAW")
                        st.session_state["edited_banner"] = f"✅ 파트타임 근태 {len(approve_targets)}건이 일괄 확인 완료되었습니다."
                        load_db_sheets.clear(store_cfg["db_id"])
                        st.rerun()

    with t_unapp:
        if not df_att.empty:
            approved_day = df_att[
                (df_att["날짜"] == cur_date_str)
                & (df_att["매니저확인"].astype(str).str.upper() == "TRUE")
            ]
            if approved_day.empty:
                st.caption(f"{cur_date_str}에 승인 완료된 기록이 없습니다.")
            else:
                with st.form(key=f"dlg_mgr_unapprove_form_{selected_store}", border=False):
                    unapp_checks = []
                    for _, r in approved_day.iterrows():
                        lbl = f"**{r['이름']}** ({r.get('근무타임', '')}) `{r['시작시간']}~{r['종료시간']}`"
                        chk = st.checkbox(
                            lbl,
                            value=False,
                            key=f"dlg_chk_unapp_{selected_store}_{r['_sheet_row']}",
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
                            now_s = kst_now().strftime("%m/%d %H:%M:%S")
                            now_f = kst_now().strftime("%Y-%m-%d %H:%M:%S")
                            batch_payload = [
                                {
                                    "range": f"H{r_num}:J{r_num}",
                                    "values": [["FALSE", f"{old_n}\n[{now_s}] 매니저 확인 해제".strip(), now_f]],
                                }
                                for r_num, old_n in unapp_targets
                            ]
                            ws.batch_update(batch_payload, value_input_option="RAW")
                            st.session_state["edited_banner"] = f"🔓 {len(unapp_targets)}건 승인이 해제되었습니다."
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
            with st.form(key=f"dlg_reg_change_form_{selected_store}", border=False, clear_on_submit=True):
                rc1, rc2 = st.columns(2)
                with rc1:
                    reg_date = st.date_input("발생 날짜", value=cur_sel_date)
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
                    now_f = kst_now().strftime("%Y-%m-%d %H:%M:%S")
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
                    st.session_state["edited_banner"] = f"✅ [{reg_emp}] {reg_date.strftime('%m/%d')} {reg_type} 기록 완료!"
                    st.rerun()

            df_rc = load_regular_changes(store_cfg["db_id"])
            if not df_rc.empty and "발생일" in df_rc.columns:
                cur_s, cur_e = get_payroll_period(kst_today(), start_day=payroll_start_day)
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
                            key=f"dlg_sel_edit_rc_{selected_store}",
                        )
                        target_rc = rc_records[sel_rc_idx]
                        target_rc_row = int(target_rc["_sheet_row"])

                        try:
                            def_rc_dt = datetime.date.fromisoformat(str(target_rc["발생일"])[:10])
                        except Exception:
                            def_rc_dt = cur_sel_date

                        def_emp_idx = reg_names.index(target_rc["이름"]) if target_rc["이름"] in reg_names else 0
                        def_type_idx = REG_CHANGE_TYPES.index(target_rc["구분"]) if target_rc["구분"] in REG_CHANGE_TYPES else 0
                        def_unit_idx = REG_CHANGE_UNITS.index(target_rc["일수_시간"]) if target_rc["일수_시간"] in REG_CHANGE_UNITS else 0

                        ec1, ec2 = st.columns(2)
                        with ec1:
                            edit_rc_date = st.date_input("발생 날짜 수정", value=def_rc_dt, key=f"dlg_ed_rc_dt_{selected_store}_{target_rc_row}")
                        with ec2:
                            edit_rc_emp = st.selectbox("정규직 수정", options=reg_names, index=def_emp_idx, key=f"dlg_ed_rc_emp_{selected_store}_{target_rc_row}")

                        ec3, ec4 = st.columns(2)
                        with ec3:
                            edit_rc_type = st.selectbox("변동 구분 수정", options=REG_CHANGE_TYPES, index=def_type_idx, key=f"dlg_ed_rc_tp_{selected_store}_{target_rc_row}")
                        with ec4:
                            edit_rc_unit = st.selectbox("단위 수정", options=REG_CHANGE_UNITS, index=def_unit_idx, key=f"dlg_ed_rc_un_{selected_store}_{target_rc_row}")

                        edit_rc_memo = st.text_input(
                            "사유 및 정산 메모 수정",
                            value=str(target_rc.get("상세메모", "")),
                            key=f"dlg_ed_rc_mm_{selected_store}_{target_rc_row}",
                        )

                        b_save_rc, b_del_rc = st.columns(2)
                        with b_save_rc:
                            if st.button("💾 수정 반영", type="primary", use_container_width=True, key=f"dlg_btn_save_rc_{selected_store}_{target_rc_row}"):
                                with st.spinner("수정 내용 반영 중..."):
                                    now_f = kst_now().strftime("%Y-%m-%d %H:%M:%S")
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
                                    st.session_state["edited_banner"] = "✅ 정규직 근태변동 수정 내용이 반영되었습니다."
                                    st.rerun()
                        with b_del_rc:
                            if st.button("🗑️ 내역 삭제", use_container_width=True, key=f"dlg_btn_del_rc_{selected_store}_{target_rc_row}"):
                                with st.spinner("내역 삭제 중..."):
                                    delete_regular_change(
                                        store_cfg["db_id"],
                                        app_cfg,
                                        selected_store,
                                        target_rc_row,
                                        rc_labels[sel_rc_idx],
                                    )
                                    load_regular_changes.clear(store_cfg["db_id"])
                                    st.session_state["edited_banner"] = "🗑️ 선택한 정규직 근태변동 내역이 삭제되었습니다."
                                    st.rerun()


# ==============================================================================
# 상단 상태 반응형 퀵 팝업 버튼 바 (데이터가 생기면 색상·문구 자동 강조)
# ==============================================================================
if show_pay_board:
    qb1, qb2, qb3 = st.columns(3)
    with qb1:
        if pending_pay_cnt > 0:
            if st.button(f"● 계좌입금·지역화폐 미확인 {pending_pay_cnt}건", key="qbtn_pay_alert", use_container_width=True):
                open_payment_dialog()
        else:
            pay_lbl = f"계좌입금·지역화폐 확인 (오늘 {len(today_pay_df)}건)" if not today_pay_df.empty else "계좌입금·지역화폐 확인 (0건)"
            if st.button(pay_lbl, key="qbtn_pay_idle", use_container_width=True):
                open_payment_dialog()
    with qb2:
        if health_alerts:
            if st.button(f"▲ 보건증 갱신 {len(health_alerts)}명 확인", key="qbtn_health_alert", use_container_width=True):
                open_health_dialog()
        else:
            if st.button("보건증 정상 (0명)", key="qbtn_health_idle", use_container_width=True):
                open_health_dialog()
    with qb3:
        if pending_att_cnt > 0:
            if st.button(f"● 매니저 승인 대기 {pending_att_cnt}건", key="qbtn_mgr_alert", use_container_width=True):
                open_manager_dialog(sel_date, date_str)
        else:
            if st.button("매니저 확인 (승인완료)", key="qbtn_mgr_idle", use_container_width=True):
                open_manager_dialog(sel_date, date_str)
else:
    qb2, qb3 = st.columns(2)
    with qb2:
        if health_alerts:
            if st.button(f"▲ 보건증 갱신 {len(health_alerts)}명 확인", key="qbtn_health_alert", use_container_width=True):
                open_health_dialog()
        else:
            if st.button("보건증 정상 (0명)", key="qbtn_health_idle", use_container_width=True):
                open_health_dialog()
    with qb3:
        if pending_att_cnt > 0:
            if st.button(f"● 매니저 승인 대기 {pending_att_cnt}건", key="qbtn_mgr_alert", use_container_width=True):
                open_manager_dialog(sel_date, date_str)
        else:
            if st.button("매니저 확인 (승인완료)", key="qbtn_mgr_idle", use_container_width=True):
                open_manager_dialog(sel_date, date_str)

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

# 확정된 주간 스케줄 기준 선택 날짜 출근 예정자 표시 (등록된 날에만 컴팩트 1줄 표시)
if df_sched is not None and not df_sched.empty and "주차" in df_sched.columns and "구분" in df_sched.columns:
    day_cols_kr = ["월", "화", "수", "목", "금", "토", "일"]
    sel_mon_str = (sel_date - datetime.timedelta(days=sel_date.weekday())).strftime("%Y-%m-%d")
    sel_day_col = day_cols_kr[sel_date.weekday()]
    if sel_day_col in df_sched.columns:
        day_sched_df = df_sched[
            (df_sched["주차"].astype(str).str.strip() == sel_mon_str)
            & (df_sched["구분"].astype(str).str.strip() == "확정")
        ]
        scheduled_items = []
        for _, sr in day_sched_df.iterrows():
            s_nm = str(sr.get("이름", "")).strip()
            s_tm = str(sr.get(sel_day_col, "")).strip()
            if s_nm and s_tm and s_tm not in ("-", "휴무", "없음", "❌휴무요청"):
                scheduled_items.append((s_tm, s_nm))
        if scheduled_items:
            scheduled_items.sort(key=lambda x: (x[0], x[1]))
            pills = " ".join(
                f'<span style="display:inline-block; background:#EEF2FF; border:1px solid #C7D2FE; color:#3730A3; '
                f'font-size:0.82rem; font-weight:700; padding:2px 9px; border-radius:999px; margin:2px 4px 2px 0;">'
                f'{nm} {tm}</span>'
                for tm, nm in scheduled_items
            )
            st.markdown(
                f'<div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:10px; '
                f'padding:0.45rem 0.85rem; margin:0.25rem 0 0.2rem 0; line-height:1.7;">'
                f'<span style="font-size:0.84rem; font-weight:800; color:#312E81; margin-right:6px;">'
                f'▪ {sel_date.strftime("%m/%d")}({sel_day_col}) 출근 예정 ({len(scheduled_items)}명):</span> {pills}</div>',
                unsafe_allow_html=True,
            )

if "edited_banner" in st.session_state and st.session_state["edited_banner"]:
    st.success(st.session_state["edited_banner"])
    st.session_state["edited_banner"] = ""

# ==============================================================================
# [메인 1] 일 근무현황 (화면 전체 폭)
# ==============================================================================
selected_grid_record = None
last_edited_row = st.session_state.get("last_edited_sheet_row", None)

render_section_banner("1. 일 근무현황", badge="직원 공용", subtitle="수정할 줄 왼쪽 체크박스를 누르면 아래에서 수정할 수 있습니다", accent="blue")
if not df_att.empty and "날짜" in df_att.columns:
    day_df = df_att[df_att["날짜"] == date_str].copy().reset_index(drop=True)
    if not day_df.empty:
        day_df["확인상태"] = day_df["매니저확인"].apply(
            lambda x: "✓ 확인완료" if str(x).strip().upper() == "TRUE" else "· 대기중"
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

        grid_height = max(210, min(len(day_df) * 30 + 40, 360))
        event = st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            row_height=29,
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

    render_section_banner(
        "2. 출퇴근 시간 입력 / 수정",
        badge=("수정 모드" if mode == "기존 수정" else "신규 입력"),
        subtitle="신규 입력: 본인 이름 선택 후 저장 | 수정: 표에서 해당 줄 체크",
        accent=("amber" if mode == "기존 수정" else "blue"),
    )

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

        c_name, c1 = st.columns(2)
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

        c2, c3 = st.columns(2)
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
            st.warning("먼저 좌측의 **본인 이름 선택**에서 이름을 고르면 시간 입력칸이 활성화됩니다.")
        elif diff_mins > 0:
            st.success(f"계산된 근무시간: **{hm_str}** ({mins_to_korean(diff_mins)})")
        else:
            st.warning("시작시간과 종료시간을 입력해 주세요.")

        st.markdown(
            """
            <div style="background-color:#FEF3C7; border:1px solid #F59E0B; border-radius:7px; padding:0.48rem 0.75rem; margin:0.35rem 0 0.55rem 0; color:#92400E; font-weight:700; font-size:0.88rem;">
                ※ 근무시간 수정 시 위의 표에서 해당 내역을 먼저 체크한 후 수정하세요.
            </div>
            """,
            unsafe_allow_html=True,
        )

        if mode == "기존 수정":
            edit_reason = st.text_input(
                "수정 사유 (필수 입력)",
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
        btn_label = "출퇴근 시간 저장하기" if mode == "신규 등록" else "수정 내역 반영하기"

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
        render_section_banner("3. 개인별 월별 근무시간 조회", badge="월별 누적", accent="indigo")
        with st.container(border=True):
            st.info("좌측 **2. 출퇴근 시간 입력/수정**에서 **본인 이름**을 선택하면, 여기에 본인의 이번 달 누적 출근일수와 근무시간이 표시됩니다.")
    else:
        render_section_banner(f"3. {real_emp_name} 님 월별 근무시간", badge="월별 누적", accent="indigo")

        month_options = get_recent_payroll_months(kst_today(), start_day=payroll_start_day, count=6)
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

            with st.expander(f"세부 근무 내역 ({len(m_df)}건)", expanded=False):
                if not m_df.empty:
                    m_disp = m_df.sort_values("날짜", ascending=False).copy()
                    m_disp["날짜"] = m_disp["날짜"].apply(format_date_with_weekday)
                    m_disp["근무시간"] = m_disp["시작시간"] + "~" + m_disp["종료시간"]
                    m_disp["상태"] = m_disp["매니저확인"].apply(
                        lambda x: "✓ 확인" if str(x).strip().upper() == "TRUE" else "· 대기"
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
