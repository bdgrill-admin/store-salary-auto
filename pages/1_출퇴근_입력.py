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

st.set_page_config(page_title="분당그릴 출퇴근 기록부", page_icon="⏱️", layout="wide")


# =========================================================================
# 1. 커스텀 스타일 (salary_auto.py와 디자인 통일)
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
            padding-top: 2.2rem;
            padding-bottom: 3rem;
            max-width: 1360px;
        }
        .app-title {
            font-size: 1.6rem;
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
            font-size: 1.08rem;
            font-weight: 700;
            color: #1E293B;
            margin: 1rem 0 0.6rem 0;
            padding-left: 0.6rem;
            border-left: 4px solid #334155;
        }
        div[data-testid="stMetric"] {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 10px;
            padding: 0.85rem 1rem;
        }
        .stButton > button {
            border-radius: 8px;
            font-weight: 600;
            min-height: 2.7rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_clean_style()


# =========================================================================
# 2. 구글 시트 연결 및 유틸리티 함수
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


def get_period_ranges(target_date: datetime.date, start_day: int = 5):
    """기준일 기준 이번 주(월~일)와 이번 달 정산기간(5일~익월 4일) 계산"""
    week_start = target_date - datetime.timedelta(days=target_date.weekday())
    week_end = week_start + datetime.timedelta(days=6)

    if target_date.day >= start_day:
        month_start = target_date.replace(day=start_day)
        if target_date.month == 12:
            next_m = target_date.replace(year=target_date.year + 1, month=1, day=start_day)
        else:
            next_m = target_date.replace(month=target_date.month + 1, day=start_day)
        month_end = next_m - datetime.timedelta(days=1)
    else:
        if target_date.month == 1:
            month_start = target_date.replace(year=target_date.year - 1, month=12, day=start_day)
        else:
            month_start = target_date.replace(month=target_date.month - 1, day=start_day)
        month_end = target_date.replace(day=start_day) - datetime.timedelta(days=1)

    return week_start, week_end, month_start, month_end


def mins_to_hm(total_mins: int) -> str:
    return f"{total_mins // 60:02d}:{total_mins % 60:02d}"


def mins_to_korean(total_mins: int) -> str:
    return f"{total_mins // 60}시간 {total_mins % 60}분"


@st.cache_data(ttl=20, show_spinner="근태 데이터를 불러오는 중...")
def load_db_sheets(db_id: str):
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)

    # 1) 직원목록 로드
    ws_emp = ss.worksheet("직원목록")
    emp_rows = ws_emp.get_all_values()
    emp_list = []
    if len(emp_rows) >= 2:
        headers = [c.strip() for c in emp_rows[0]]
        for r in emp_rows[1:]:
            row_d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
            if row_d.get("이름"):
                emp_list.append(row_d)
    df_emp = pd.DataFrame(emp_list)

    # 2) 통합근태DB 로드
    ws_att = ss.worksheet("통합근태DB")
    att_rows = ws_att.get_all_values()
    att_list = []
    if len(att_rows) >= 2:
        headers = [c.strip() for c in att_rows[0]]
        for idx, r in enumerate(att_rows[1:], start=2):
            row_d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
            if row_d.get("날짜") and row_d.get("이름"):
                row_d["_sheet_row"] = idx
                att_list.append(row_d)
    df_att = pd.DataFrame(att_list)

    return df_emp, df_att


# =========================================================================
# 3. 상단 헤더 및 매장/날짜 선택
# =========================================================================
h_col1, h_col2 = st.columns([3.2, 1], vertical_alignment="center")
with h_col1:
    st.markdown(
        """
        <div class="app-title">⏱️ 매장 출퇴근 기록부</div>
        <div class="app-subtitle">일별 근무 현황 · 개인별 주간/월간 누적 근무시간 조회</div>
        """,
        unsafe_allow_html=True,
    )
with h_col2:
    selected_store = st.selectbox("매장 선택", list(STORES.keys()), index=0)

store_cfg = STORES[selected_store]

try:
    df_emp, df_att = load_db_sheets(store_cfg["db_id"])
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.info("💡 통합근태DB 시트 우측 상단 [공유]에서 서비스 계정 이메일에 '편집자' 권한이 추가되어 있는지 확인해 주세요.")
    st.stop()

# 재직 직원 목록 구성 (메모에 실근무자 이름이 있으면 자동 매핑)
display_to_real_name = {}
if not df_emp.empty:
    active_df = df_emp[df_emp["상태"] != "퇴사"] if "상태" in df_emp.columns else df_emp
    for _, r in active_df.iterrows():
        reg_name = str(r.get("이름", "")).strip()
        memo_name = str(r.get("메모", "")).strip()
        if not reg_name:
            continue
        if memo_name and "퇴사" not in memo_name and len(memo_name) <= 5:
            disp_label = f"{memo_name} (계좌:{reg_name})"
            display_to_real_name[disp_label] = memo_name
        else:
            display_to_real_name[reg_name] = reg_name

if not df_att.empty:
    df_att["날짜_dt"] = pd.to_datetime(df_att["날짜"], errors="coerce").dt.date
    df_att["총시간(소수)"] = pd.to_numeric(df_att["총시간(소수)"], errors="coerce").fillna(0.0)

with st.container(border=True):
    d_c1, d_c2, d_c3 = st.columns([1.3, 2.4, 0.9], vertical_alignment="bottom")
    with d_c1:
        sel_date = st.date_input("📅 조회 및 입력 날짜", value=datetime.date.today())
        date_str = sel_date.strftime("%Y-%m-%d")
    with d_c2:
        weekdays_kr = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
        w_kr = weekdays_kr[sel_date.weekday()]
        st.markdown(
            f"""
            <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:0.55rem 0.9rem; font-size:0.9rem; color:#334155;">
                선택된 날짜: <b>{date_str} ({w_kr})</b>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with d_c3:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

# =========================================================================
# 4. [상단 구역] 좌측: 당일 근무 현황 그리드 | 우측: 매니저 확인 패널
# =========================================================================
top_left, top_right = st.columns([1.75, 1])

with top_left:
    st.markdown(f'<div class="section-title">1. {date_str} 당일 근무 현황</div>', unsafe_allow_html=True)
    if not df_att.empty and "날짜" in df_att.columns:
        day_df = df_att[df_att["날짜"] == date_str].copy()
        if not day_df.empty:
            day_df["확인상태"] = day_df["매니저확인"].apply(
                lambda x: "✅ 확인완료" if str(x).strip().upper() == "TRUE" else "⏳ 대기중"
            )
            show_cols = ["이름", "근무타임", "시작시간", "종료시간", "총시간(h:m)", "확인상태", "비고"]
            valid_cols = [c for c in show_cols if c in day_df.columns]
            st.dataframe(day_df[valid_cols], use_container_width=True, hide_index=True, height=250)
        else:
            st.info("해당 날짜에 등록된 근무 기록이 없습니다.")
    else:
        st.info("등록된 근무 기록이 없습니다.")

with top_right:
    st.markdown('<div class="section-title">✅ 매니저 확인 (승인 관리)</div>', unsafe_allow_html=True)
    with st.container(border=True):
        pin_input = st.text_input(
            "매니저 PIN 입력",
            type="password",
            placeholder="PIN 번호 입력 후 확인 처리",
            key="mgr_pin_top",
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
                    st.caption(f"미확인 건수: 총 {len(pending_df)}건")
                    approve_targets = []
                    for _, r in pending_df.iterrows():
                        chk_label = f"[{r['날짜'][5:]}] {r['이름']} ({r.get('근무타임', '')}) {r['시작시간']}~{r['종료시간']} ({r['총시간(h:m)']})"
                        if st.checkbox(chk_label, value=True, key=f"chk_app_{r['_sheet_row']}"):
                            approve_targets.append((int(r["_sheet_row"]), str(r.get("비고", ""))))

                    if st.button("✅ 선택 항목 확인 완료", type="primary", use_container_width=True):
                        gc = get_gspread_client()
                        ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")
                        now_s = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                        now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        for r_num, old_n in approve_targets:
                            new_n = (
                                f"{old_n}\n[{now_s}] 매니저 확인 완료".strip()
                                if "매니저 확인 완료" not in old_n
                                else old_n
                            )
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
            st.error("매니저 PIN이 일치하지 않습니다.")
        else:
            st.caption("매니저 PIN을 입력하면 미확인 근무 내역 일괄 승인 및 해제가 가능합니다.")

# =========================================================================
# 5. [하단 구역] 좌측: 출퇴근 입력/수정 | 우측: 개인별 누적 시간 조회
# =========================================================================
left_col, right_col = st.columns([1.45, 1])

with left_col:
    st.markdown('<div class="section-title">2. 출퇴근 시간 입력 / 수정</div>', unsafe_allow_html=True)
    with st.container(border=True):
        if not display_to_real_name:
            st.warning("'직원목록' 탭에 재직 중인 직원이 없습니다.")
            st.stop()

        sel_disp_name = st.selectbox("본인 이름 선택", options=list(display_to_real_name.keys()))
        real_emp_name = display_to_real_name[sel_disp_name]

        emp_today = pd.DataFrame()
        if not df_att.empty:
            emp_today = df_att[(df_att["날짜"] == date_str) & (df_att["이름"] == real_emp_name)]

        mode = "신규 등록"
        target_sheet_row = None
        old_record = {}

        if not emp_today.empty:
            st.info(f"📌 **{real_emp_name}** 님의 {date_str} 기록이 **{len(emp_today)}건** 등록되어 있습니다.")
            action_opts = ["➕ 추가 근무 타임 등록 (예: 점심 근무 후 저녁 재출근)"]
            for _, r in emp_today.iterrows():
                is_app = str(r.get("매니저확인", "")).strip().upper() == "TRUE"
                badge = "확인완료🔒" if is_app else "대기중"
                action_opts.append(
                    f"✏️ 기존 기록 수정 [{r.get('근무타임', '')}: {r.get('시작시간')}~{r.get('종료시간')} | {badge}] (행:{r['_sheet_row']})"
                )

            chosen_action = st.radio("작업 선택", options=action_opts)
            if chosen_action.startswith("✏️"):
                mode = "기존 수정"
                target_sheet_row = int(chosen_action.split("(행:")[1].replace(")", ""))
                old_record = emp_today[emp_today["_sheet_row"] == target_sheet_row].iloc[0].to_dict()

        is_locked = (mode == "기존 수정") and (str(old_record.get("매니저확인", "")).strip().upper() == "TRUE")
        if is_locked:
            st.error("🚫 이미 매니저 확인이 완료된 기록입니다. 수정이 필요하면 매니저에게 승인 해제를 요청하세요.")

        # 근무타임 기본값 (평일/주말 자동 추천 또는 기존값 유지)
        default_shift_idx = 0
        if mode == "기존 수정":
            old_t = str(old_record.get("근무타임", "")).strip()
            if old_t in SHIFT_OPTIONS:
                default_shift_idx = SHIFT_OPTIONS.index(old_t)
        else:
            # 주말(토/일)이면 주말(점심)을 기본 선택, 평일이면 평일 기본 선택
            if sel_date.weekday() >= 5:
                default_shift_idx = 1 if len(emp_today) == 0 else 2
            else:
                default_shift_idx = 0

        # 시작시간 / 종료시간: 신규는 모두 00:00, 수정은 기존 시간 로드
        if mode == "기존 수정":
            try:
                def_s = datetime.datetime.strptime(str(old_record.get("시작시간", "00:00")), "%H:%M").time()
                def_e = datetime.datetime.strptime(str(old_record.get("종료시간", "00:00")), "%H:%M").time()
            except Exception:
                def_s, def_e = datetime.time(0, 0), datetime.time(0, 0)
        else:
            def_s, def_e = datetime.time(0, 0), datetime.time(0, 0)

        c1, c2, c3 = st.columns(3)
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

        # 시간 계산 (자정 넘김 자동 보정)
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

        if mode == "기존 수정":
            edit_reason = st.text_input(
                "🚨 수정 사유 (필수 입력)",
                placeholder="예: 마감 정산 지연으로 퇴근시간 정정",
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
                st.success("✅ 수정 완료! 변경 전/후 시간과 사유가 기록되었습니다.")
            else:
                row_values = [date_str, real_emp_name, shift_type, s_str, e_str, hm_str, dec_hours, "FALSE", memo_val.strip(), now_full]
                ws.append_row(row_values, value_input_option="USER_ENTERED")
                st.success(f"✅ {real_emp_name} 님의 근무 기록({s_str}~{e_str})이 저장되었습니다.")

            st.cache_data.clear()
            st.rerun()

with right_col:
    st.markdown(f'<div class="section-title">3. {real_emp_name} 님 누적 근무시간</div>', unsafe_allow_html=True)
    w_start, w_end, m_start, m_end = get_period_ranges(sel_date, PAYROLL_START_DAY)

    if not df_att.empty and "이름" in df_att.columns:
        emp_all = df_att[df_att["이름"] == real_emp_name]

        w_df = emp_all[(emp_all["날짜_dt"] >= w_start) & (emp_all["날짜_dt"] <= sel_date)]
        w_mins = int(round(w_df["총시간(소수)"].sum() * 60))

        m_df = emp_all[(emp_all["날짜_dt"] >= m_start) & (emp_all["날짜_dt"] <= sel_date)]
        m_mins = int(round(m_df["총시간(소수)"].sum() * 60))
        unconfirmed_cnt = (
            len(m_df[m_df["매니저확인"].astype(str).str.upper() != "TRUE"])
            if "매니저확인" in m_df.columns
            else 0
        )

        st.metric(
            label=f"이번 주 누적 ({w_start.strftime('%m/%d')} ~ {sel_date.strftime('%m/%d')})",
            value=mins_to_korean(w_mins),
            delta=f"{mins_to_hm(w_mins)} (총 {len(w_df)}건 근무)",
            delta_color="off",
        )
        st.metric(
            label=f"이번 정산월 누적 ({m_start.strftime('%m/%d')} ~ {sel_date.strftime('%m/%d')})",
            value=mins_to_korean(m_mins),
            delta=f"{mins_to_hm(m_mins)} · 총 {len(m_df)}건 (미확인 {unconfirmed_cnt}건)",
            delta_color="off",
        )

        with st.expander("📋 이번 정산월 상세 근무 내역 보기", expanded=True):
            if not m_df.empty:
                m_disp = m_df[["날짜", "근무타임", "시작시간", "종료시간", "총시간(h:m)", "매니저확인"]].sort_values(
                    "날짜", ascending=False
                )
                st.dataframe(m_disp, use_container_width=True, hide_index=True)
            else:
                st.caption("이번 정산월 근무 기록이 없습니다.")
    else:
        st.caption("누적 근무 내역이 없습니다.")
