"""
================================================================================
[파일명] views/attendance.py
[역할] 매장 직원 및 매니저 공용 '일일 출퇴근기록부 및 월별 근무시간 조회' 페이지
[주요 기능]
  1. 날짜별 일 근무현황 실시간 표 조회 (선택된 행 파란색 / 방금 수정된 행 초록색 하이라이트)
  2. 매니저 전용 확인(PIN 번호 입력): 미확인 근태 일괄 승인 및 승인 완료 건 잠금 해제
  3. 직원 출퇴근 시간 신규 입력 및 기존 내역 선택 수정
     - [순차 입력 유도] '본인 이름'을 먼저 선택해야만 근무타임·시작/종료시간·비고 입력칸이 활성화됨
     - 출퇴근 기록 저장 완료 즉시 이름·시간·비고 입력창을 모두 초기 상태로 자동 리셋
     - 매니저 확인 완료('TRUE')된 기록은 직원이 임의로 수정하지 못하도록 자동 잠금
  4. 선택한 직원의 정산월 기준(매월 5일 ~ 익월 4일) 누적 출근일수 및 총 근무시간 실시간 집계
================================================================================
"""

import os
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
# 매장별 통합근태DB 시트 ID, 매니저 PIN, 급여 정산 기준일(매월 5일) 설정
# ------------------------------------------------------------------------------
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
PAYROLL_START_DAY = 5  # 급여 정산 시작일 (매월 5일 ~ 다음 달 4일)
SHIFT_OPTIONS = ["평일", "주말(점심)", "주말(저녁)", "기타"]
EMP_PLACEHOLDER = "🔽 이름 선택"


# ------------------------------------------------------------------------------
# 화면 UI 스타일(Pretendard 폰트, 매니저 박스 강조 색상, 여백 등) 설정
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# 구글 시트 API 클라이언트 인증 및 정산 기간/시간 포맷 변환 보조 함수들
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


def get_payroll_period(ref_date: datetime.date, start_day: int = 5):
    """기준 날짜가 속한 정산월의 시작일(5일)과 종료일(익월 4일)을 계산"""
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
    """최근 6개월치 정산월 드롭다운 선택지 생성"""
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
    """총 분(minutes)을 'HH:MM' 문자열로 변환"""
    return f"{total_mins // 60:02d}:{total_mins % 60:02d}"


def mins_to_korean(total_mins: int) -> str:
    """총 분(minutes)을 'X시간 Y분' 한글 문자열로 변환"""
    return f"{total_mins // 60}시간 {total_mins % 60}분"


def format_date_with_weekday(d_str: str) -> str:
    """'YYYY-MM-DD' 날짜를 'MM-DD (요일)' 형식으로 변환"""
    weekdays_short = ["월", "화", "수", "목", "금", "토", "일"]
    try:
        dt = datetime.datetime.strptime(str(d_str).strip(), "%Y-%m-%d").date()
        return f"{dt.strftime('%m-%d')} ({weekdays_short[dt.weekday()]})"
    except Exception:
        return str(d_str)[5:] if len(str(d_str)) >= 10 else str(d_str)


# ------------------------------------------------------------------------------
# 구글 시트에서 '파트타임'(직원명부) 및 '통합근태DB'(출퇴근기록) 로드
# ------------------------------------------------------------------------------
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
                        row_d["_sheet_row"] = idx  # 시트 실제 행 번호 저장 (수정/승인 시 정확한 행 업데이트용)
                    out.append(row_d)
        return pd.DataFrame(out)

    df_emp = read_sheet("파트타임")
    df_att = read_sheet("통합근태DB", with_row_num=True)
    if not df_att.empty:
        df_att = df_att[(df_att["날짜"] != "") & (df_att["이름"] != "")].copy()

    return df_emp, df_att


# ==============================================================================
# 상단 타이틀, 새로고침 버튼, 매장 선택 및 조회 날짜 선택기
# ==============================================================================
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

# 재직 중인 파트타임 직원 이름 목록 추출 (예금주와 실근무자가 달라 '메모'에 실근무자명이 적힌 경우 실근무자명 우선 사용)
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

# ==============================================================================
# 상단 좌/우 영역: [좌] 1. 일 근무현황 표  |  [우] 매니저 전용 확인(승인/해제)
# ==============================================================================
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

            # 선택된 행은 파란색, 방금 저장/수정한 행은 연초록색으로 배경 하이라이트
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

            # 표에서 특정 행을 체크하면 하단 입력창이 자동으로 '기존 수정' 모드로 전환됨
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
        p_lbl, p_inp = st.columns([0.75, 1.6], vertical_alignment="center")
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
                key="mgr_pin_top",
                label_visibility="collapsed",
            )

        # 매니저 비밀번호 일치 시: 미확인 건 일괄 승인 탭 & 승인 해제 탭 표시
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

# ==============================================================================
# 하단 좌/우 영역: [좌] 2. 출퇴근 시간 입력/수정  |  [우] 3. 개인별 월 누적 근무시간 조회
# ==============================================================================
if "form_reset_ver" not in st.session_state:
    st.session_state["form_reset_ver"] = 0

# 출퇴근 저장 직후 다음 사람을 위해 이름 선택창을 '미선택'으로 리셋하고 시간/비고 위젯 버전 갱신
if st.session_state.get("reset_emp_selector", False):
    st.session_state["att_emp_selector"] = EMP_PLACEHOLDER
    st.session_state["form_reset_ver"] += 1
    st.session_state["reset_emp_selector"] = False

left_col, right_col = st.columns([1.5, 1.0])

with left_col:
    # 위 표에서 행을 선택했으면 '기존 수정' 모드, 아니면 '신규 등록' 모드로 자동 전환
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

        # 매니저 확인이 완료된 건('TRUE')은 직원이 수정할 수 없도록 입력창 비활성화(Lock)
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

        # [핵심] 본인 이름을 선택하지 않았거나(not is_emp_selected) 매니저 잠금(is_locked) 상태면 나머지 입력칸 모두 비활성화
        inputs_disabled = is_locked or (not is_emp_selected)
        w_key_sfx = f"{mode}_{target_sheet_row}_{st.session_state['form_reset_ver']}"

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
                step=600,
                disabled=inputs_disabled,
                key=f"start_{w_key_sfx}",
            )
        with c3:
            end_t = st.time_input(
                "종료시간",
                value=def_e,
                step=600,
                disabled=inputs_disabled,
                key=f"end_{w_key_sfx}",
            )

        # 근무시간 자동 계산 (종료시간이 시작시간보다 빠르면 자정을 넘긴 익일 퇴근으로 자동 계산)
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

        # 저장 버튼 클릭 시 '통합근태DB' 시트에 추가(append) 또는 해당 행 업데이트(update) 후 전체 입력칸 초기화
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

            # 저장 직후 다음 직원을 위해 이름 선택창 및 시간/비고 입력칸 전체 리셋 예약
            st.session_state["reset_emp_selector"] = True
            st.cache_data.clear()
            st.rerun()

with right_col:
    # 직원이 본인 이름을 직접 선택했을 때만 우측에 해당 직원의 월 누적 근무시간을 표시
    if not is_emp_selected:
        st.markdown('<div class="section-title">3. 개인별 월별 근무시간 조회</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.info("👈 좌측 **'2. 출퇴근 시간 입력/수정'**에서 **본인 이름**을 선택하면, 여기에 본인의 이번 달 누적 출근일수와 근무시간이 표시됩니다.")
    else:
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
