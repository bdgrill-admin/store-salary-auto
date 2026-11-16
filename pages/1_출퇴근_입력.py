import os
import datetime
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# =========================================================================
# 0. 매장 및 시스템 설정
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
        "manager_pin": get_secret("MANAGER_PIN_BUNDANG", "0524"),
    },
    # 향후 감동한점 오픈 시 주석 해제 후 ID 입력
    # "감동한점": {
    #     "db_id": "여기에_감동한점_통합근태DB_ID",
    #     "manager_pin": get_secret("MANAGER_PIN_GAMDONG", "0524"),
    # },
}

CREDENTIALS_FILE = "credentials.json"
PAYROLL_START_DAY = 5  # 급여 정산 시작일 (매월 5일 ~ 익월 4일)
SHIFT_OPTIONS = ["평일", "주말(점심)", "주말(저녁)", "기타"]

st.set_page_config(page_title="분당그릴 출퇴근기록부", page_icon="⏱️", layout="wide")


# =========================================================================
# 1. 커스텀 스타일
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
        /* 매니저 확인 섹션 전용 배경/테두리 강조 */
        div[data-testid="stVerticalBlock"]:has(> div.element-container > div.stMarkdown > div.mgr-box-marker) {
            background-color: #FFFBEB;
            border: 1.5px solid #F59E0B;
            border-radius: 10px;
            padding: 0.85rem 1rem;
        }
        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 0.75rem 1rem;
        }
        .stButton > button {
            border-radius: 8px;
            font-weight: 600;
            min-height: 2.45rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_clean_style()


# =========================================================================
# 2. 구글 시트 연결 및 날짜/시간 계산 유틸리티
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


def get_recent_payroll_months(base_date: datetime.date, count: int = 6):
    options = {}
    cur_start, cur_end = get_payroll_period(base_date, PAYROLL_START_DAY)
    for i in range(count):
        tag = "이번 정산월" if i == 0 else f"{i}개월 전"
        label = f"{cur_start.strftime('%Y년 %m월분')} ({cur_start.strftime('%m/%d')}~{cur_end.strftime('%m/%d')}) · {tag}"
        options[label] = (cur_start, cur_end)
        prev_ref = cur_start - datetime.timedelta(days=1)
        cur_start, cur_end = get_payroll_period(prev_ref, PAYROLL_START_DAY)
    return options


def mins_to_hm(total_mins: int) -> str:
    return f"{total_mins // 60:02d}:{total_mins % 60:02d}"


def mins_to_korean(total_mins: int) -> str:
    return f"{total_mins // 60}시간 {total_mins % 60}분"


@st.cache_data(ttl=20, show_spinner="근태 데이터를 불러오는 중...")
def load_db_sheets(db_id: str):
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)

    def read_sheet(tab_name: str, with_row_num: bool = False):
        ws = ss.worksheet(tab_name)
        rows = ws.get_all_values()
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

    df_emp = read_sheet("직원목록")
    df_att = read_sheet("통합근태DB", with_row_num=True)
    if not df_att.empty:
        df_att = df_att[(df_att["날짜"] != "") & (df_att["이름"] != "")].copy()

    return df_emp, df_att


# =========================================================================
# 3. 상단 헤더 (제목 바로 옆 새로고침 밀착 정렬 | 우측 끝 매장선택)
# =========================================================================
h_col1, h_col2, _, h_col4 = st.columns([0.95, 0.55, 2.7, 0.85], vertical_alignment="center")
with h_col1:
    st.markdown('<div class="app-title">⏱️ 출퇴근기록부</div>', unsafe_allow_html=True)
with h_col2:
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
with h_col4:
    selected_store = st.selectbox("매장 선택", list(STORES.keys()), index=0, label_visibility="collapsed")

st.markdown('<div class="app-subtitle">📅 조회 및 입력 날짜</div>', unsafe_allow_html=True)

store_cfg = STORES[selected_store]

try:
    df_emp, df_att = load_db_sheets(store_cfg["db_id"])
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

# 실근무자 이름만 깔끔하게 표시 (계좌 예금주 표기 제거)
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

# 날짜 선택 + 더 커진 굵은 요일 텍스트 + 우측 입력 방법 설명 (수평 중앙 정렬)
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
        '<div style="font-size:0.88rem; color:#475569;">💡 <b>신규 입력</b>: 아래에서 이름·시간 입력 후 저장 &nbsp;|&nbsp; <b>기존 수정</b>: 아래 표에서 해당 줄 체크 후 수정</div>',
        unsafe_allow_html=True,
    )

if "edited_banner" in st.session_state and st.session_state["edited_banner"]:
    st.success(st.session_state["edited_banner"])
    st.session_state["edited_banner"] = ""

# =========================================================================
# 4. [상단 구역] 좌측: 일 근무현황 그리드 | 우측: 매니저 전용 확인 (비밀번호 가로 배치)
# =========================================================================
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
            grid_state_key = f"att_grid_{date_str}"
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
        # '매니저 확인 비밀번호' 라벨 왼쪽 + 입력 박스 오른쪽 가로 배치
        p_lbl, p_inp = st.columns([1.05, 1.3], vertical_alignment="center")
        with p_lbl:
            st.markdown(
                '<div style="font-size:0.9rem; font-weight:700; color:#78350F; white-space:nowrap;">매니저 확인 비밀번호</div>',
                unsafe_allow_html=True,
            )
        with p_inp:
            pin_input = st.text_input(
                "매니저 확인 비밀번호",
                type="password",
                placeholder="비밀번호 입력",
                key="mgr_pin_top",
                label_visibility="collapsed",
            )

        if pin_input == store_cfg["manager_pin"]:
            t_app, t_unapp = st.tabs(["⏳ 미확인 승인", "🔓 승인 해제"])

            with t_app:
                pending_df = (
                    df_att[df_att["매니저확인"].astype(str).str.upper() != "TRUE"]
                    if not df_att.empty
                    else pd.DataFrame()
                )
                if pending_df.empty:
                    st.success("🎉 모든 근태 기록이 확인 완료되었습니다.")
                else:
                    approve_targets = []
                    for _, r in pending_df.iterrows():
                        chk_label = f"[{r['날짜'][5:]}] **{r['이름']}** ({r.get('근무타임', '')}) `{r['시작시간']}~{r['종료시간']}` ({r['총시간(h:m)']})"
                        if st.checkbox(chk_label, value=False, key=f"chk_app_{r['_sheet_row']}"):
                            approve_targets.append((int(r["_sheet_row"]), str(r.get("비고", ""))))

                    if st.button(
                        f"✅ 선택한 {len(approve_targets)}건 확인 완료",
                        type="primary",
                        use_container_width=True,
                        disabled=len(approve_targets) == 0,
                    ):
                        gc = get_gspread_client()
                        ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")
                        now_s = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                        now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        for r_num, old_n in approve_targets:
                            new_n = f"{old_n}\n[{now_s}] 매니저 확인 완료".strip()
                            ws.update(range_name=f"H{r_num}:J{r_num}", values=[["TRUE", new_n, now_f]])
                        st.success(f"{len(approve_targets)}건 확인 완료!")
                        st.cache_data.clear()
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
                        for _, r in approved_day.iterrows():
                            ca, cb = st.columns([2.5, 1], vertical_alignment="center")
                            ca.write(f"**{r['이름']}** {r['시작시간']}~{r['종료시간']}")
                            if cb.button("해제", key=f"btn_unapp_{r['_sheet_row']}", use_container_width=True):
                                gc = get_gspread_client()
                                ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")
                                now_s = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                                now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                new_n = f"{r.get('비고', '')}\n[{now_s}] 매니저 확인 해제".strip()
                                ws.update(
                                    range_name=f"H{int(r['_sheet_row'])}:J{int(r['_sheet_row'])}",
                                    values=[["FALSE", new_n, now_f]],
                                )
                                st.warning("승인이 해제되었습니다.")
                                st.cache_data.clear()
                                st.rerun()
        elif pin_input:
            st.error("비밀번호가 일치하지 않습니다.")
        else:
            st.caption("매니저 확인 전까지는 위의 표에서 행을 체크해 수정할 수 있습니다.")

# =========================================================================
# 5. [하단 구역] 좌측: 출퇴근 시간 입력/수정 | 우측: 월별 근무시간 조회
# =========================================================================
left_col, right_col = st.columns([1.5, 1.0])

with left_col:
    if selected_grid_record is not None:
        mode = "기존 수정"
        target_sheet_row = int(selected_grid_record["_sheet_row"])
        old_record = selected_grid_record
        real_emp_name = str(old_record.get("이름", "")).strip()
    else:
        mode = "신규 등록"
        target_sheet_row = None
        old_record = {}

    st.markdown('<div class="section-title">2. 출퇴근 시간 입력/수정</div>', unsafe_allow_html=True)

    with st.container(border=True):
        if not active_emp_names:
            st.warning("'직원목록' 탭에 재직 중인 직원이 없습니다.")
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

        # 이름(실근무자 단독 표기), 근무타임, 시작시간, 종료시간 4개 한 줄 배치
        c_name, c1, c2, c3 = st.columns([1.05, 1.05, 0.95, 0.95])
        with c_name:
            if mode == "기존 수정":
                st.text_input("본인 이름", value=real_emp_name, disabled=True)
            else:
                real_emp_name = st.selectbox("본인 이름 선택", options=active_emp_names)
        with c1:
            shift_type = st.selectbox(
                "근무 타임",
                options=SHIFT_OPTIONS,
                index=default_shift_idx,
                disabled=is_locked,
            )
        with c2:
            start_t = st.time_input("시작시간", value=def_s, step=600, disabled=is_locked)
        with c3:
            end_t = st.time_input("종료시간", value=def_e, step=600, disabled=is_locked)

        dt_s = datetime.datetime.combine(sel_date, start_t)
        dt_e = datetime.datetime.combine(sel_date, end_t)
        if dt_e < dt_s:
            dt_e += datetime.timedelta(days=1)
        diff_mins = int((dt_e - dt_s).total_seconds() // 60)
        hm_str = mins_to_hm(diff_mins)
        dec_hours = round(diff_mins / 60.0, 2)

        if diff_mins > 0:
            st.success(f"⏱️ 계산된 근무시간: **{hm_str}** ({mins_to_korean(diff_mins)})")
        else:
            st.warning("시작시간과 종료시간을 직접 입력해 주세요.")

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
                disabled=is_locked,
            )
            memo_val = str(old_record.get("비고", ""))
        else:
            edit_reason = ""
            memo_val = st.text_input(
                "비고 / 특이사항 (선택)",
                placeholder="예: 홀 마감 지원, 대타 등",
                disabled=is_locked,
            )

        can_submit = (not is_locked) and (diff_mins > 0) and (mode == "신규 등록" or len(edit_reason.strip()) > 0)
        btn_label = "💾 출퇴근 시간 저장하기" if mode == "신규 등록" else "🔄 수정 내역 반영하기"

        if st.button(btn_label, type="primary", use_container_width=True, disabled=not can_submit):
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
                ws.update(range_name=f"A{target_sheet_row}:J{target_sheet_row}", values=[row_values])

                st.session_state["last_edited_sheet_row"] = target_sheet_row
                st.session_state["edited_banner"] = f"✅ [{real_emp_name}] 님의 근무 기록({s_str}~{e_str}) 수정이 완료되었습니다."
            else:
                row_values = [date_str, real_emp_name, shift_type, s_str, e_str, hm_str, dec_hours, "FALSE", memo_val.strip(), now_full]
                ws.append_row(row_values, value_input_option="USER_ENTERED")
                st.session_state["last_edited_sheet_row"] = None
                st.session_state["edited_banner"] = f"✅ [{real_emp_name}] 님의 근무 기록({s_str}~{e_str})이 저장되었습니다."

            st.cache_data.clear()
            st.rerun()

with right_col:
    st.markdown(f'<div class="section-title">3. {real_emp_name} 님 월별 근무시간 조회</div>', unsafe_allow_html=True)

    month_options = get_recent_payroll_months(datetime.date.today(), count=6)
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
                m_disp["날짜"] = m_disp["날짜"].apply(lambda d: d[5:])
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
