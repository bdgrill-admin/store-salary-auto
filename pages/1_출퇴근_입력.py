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

# 매니저 사유 입력 강제 기준 (주의 필요 근무)
ALERT_MAX_HOURS_WEEKDAY = 6.5   # 평일 6.5시간 초과 시 주의
ALERT_MAX_HOURS_WEEKEND = 10.5  # 주말 10.5시간 초과 시 주의
SCHEDULE_DIFF_ALERT_MINS = 15   # 예정 스케줄 대비 15분 이상 차이 시 주의

st.set_page_config(page_title="분당그릴 출퇴근 기록부", page_icon="⏱️", layout="wide")


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
            padding-top: 2.2rem;
            padding-bottom: 3rem;
            max-width: 1380px;
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
            min-height: 2.6rem;
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
    """ref_date가 속한 급여 정산기간(5일 ~ 익월 4일) 반환"""
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
    """최근 N개월치 정산월 옵션 리스트 생성"""
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


def check_attendance_anomaly(row: dict, df_sched: pd.DataFrame) -> list:
    """매니저가 반드시 눈으로 확인해야 할 특이사항(장시간, 새벽퇴근, 스케줄 불일치) 검출"""
    flags = []
    d_str = str(row.get("날짜", ""))
    emp = str(row.get("이름", ""))
    s_time = str(row.get("시작시간", ""))
    e_time = str(row.get("종료시간", ""))
    dec_h = float(row.get("총시간(소수)", 0) or 0)

    try:
        d_obj = datetime.datetime.strptime(d_str, "%Y-%m-%d").date()
        is_weekend = d_obj.weekday() >= 5
    except Exception:
        is_weekend = False

    max_limit = ALERT_MAX_HOURS_WEEKEND if is_weekend else ALERT_MAX_HOURS_WEEKDAY
    if dec_h > max_limit:
        flags.append(f"장시간 근무({row.get('총시간(h:m)')})")

    # 심야 퇴근 체크 (00:30 ~ 05:00 사이 종료)
    try:
        eh, em = map(int, e_time.split(":"))
        if (eh == 0 and em >= 30) or (1 <= eh <= 5):
            flags.append(f"심야 퇴근({e_time})")
    except Exception:
        pass

    # 근무스케줄 탭에 예정 시간이 있는 경우 비교
    if not df_sched.empty and {"날짜", "이름", "예정출근", "예정퇴근"}.issubset(df_sched.columns):
        matched = df_sched[(df_sched["날짜"] == d_str) & (df_sched["이름"] == emp)]
        if not matched.empty:
            sc = matched.iloc[0]
            sc_s = str(sc.get("예정출근", "")).strip()
            sc_e = str(sc.get("예정퇴근", "")).strip()
            if sc_s and sc_e:
                try:
                    t1 = datetime.datetime.strptime(s_time, "%H:%M")
                    t2 = datetime.datetime.strptime(e_time, "%H:%M")
                    if t2 < t1:
                        t2 += datetime.timedelta(days=1)
                    st1 = datetime.datetime.strptime(sc_s, "%H:%M")
                    st2 = datetime.datetime.strptime(sc_e, "%H:%M")
                    if st2 < st1:
                        st2 += datetime.timedelta(days=1)
                    actual_m = (t2 - t1).total_seconds() / 60
                    sched_m = (st2 - st1).total_seconds() / 60
                    if abs(actual_m - sched_m) >= SCHEDULE_DIFF_ALERT_MINS:
                        flags.append(f"스케줄({sc_s}~{sc_e})과 {int(actual_m - sched_m):+d}분 차이")
                except Exception:
                    pass
    return flags


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

    try:
        df_sched = read_sheet("근무스케줄")
    except Exception:
        df_sched = pd.DataFrame()

    return df_emp, df_att, df_sched


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
    df_emp, df_att, df_sched = load_db_sheets(store_cfg["db_id"])
except Exception as e:
    st.error(f"구글 시트 연결 오류: {e}")
    st.stop()

display_to_real_name = {}
if not df_emp.empty:
    active_df = df_emp[df_emp["상태"] != "퇴사"] if "상태" in df_emp.columns else df_emp
    for _, r in active_df.iterrows():
        reg_name = str(r.get("이름", "")).strip()
        memo_name = str(r.get("메모", "")).strip()
        if not reg_name:
            continue
        if memo_name and "퇴사" not in memo_name and len(memo_name) <= 5:
            display_to_real_name[f"{memo_name} (계좌:{reg_name})"] = memo_name
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
top_left, top_right = st.columns([1.65, 1.1])

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
            st.dataframe(day_df[valid_cols], use_container_width=True, hide_index=True, height=270)
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
            placeholder="PIN 번호 입력 후 건별 확인",
            key="mgr_pin_top",
        )
        if pin_input == store_cfg["manager_pin"]:
            t_app, t_unapp = st.tabs(["⏳ 미확인 검토", "🔓 승인 해제"])

            with t_app:
                pending_df = (
                    df_att[df_att["매니저확인"].astype(str).str.upper() != "TRUE"]
                    if not df_att.empty
                    else pd.DataFrame()
                )
                if pending_df.empty:
                    st.success("🎉 모든 근태 기록이 확인 완료되었습니다.")
                else:
                    st.caption("※ 습관적 일괄 승인을 막기 위해 기본 해제되어 있습니다. 시간을 확인 후 직접 체크하세요.")
                    normal_targets = []
                    anomaly_rows = []

                    for _, r in pending_df.iterrows():
                        r_dict = r.to_dict()
                        anomalies = check_attendance_anomaly(r_dict, df_sched)
                        if anomalies:
                            anomaly_rows.append((r_dict, anomalies))
                        else:
                            chk_label = f"[{r['날짜'][5:]}] **{r['이름']}** ({r.get('근무타임', '')}) `{r['시작시간']}~{r['종료시간']}` ({r['총시간(h:m)']})"
                            # 기본값을 False로 두어 매니저가 건별로 눈으로 보고 클릭하게 강제
                            if st.checkbox(chk_label, value=False, key=f"chk_app_{r['_sheet_row']}"):
                                normal_targets.append((int(r["_sheet_row"]), str(r.get("비고", ""))))

                    if normal_targets:
                        if st.button(f"✅ 선택한 {len(normal_targets)}건 확인 완료", type="primary", use_container_width=True):
                            gc = get_gspread_client()
                            ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")
                            now_s = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                            now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            for r_num, old_n in normal_targets:
                                new_n = f"{old_n}\n[{now_s}] 매니저 확인 완료".strip()
                                ws.update(range_name=f"H{r_num}:J{r_num}", values=[["TRUE", new_n, now_f]])
                            st.success("확인 완료!")
                            st.cache_data.clear()
                            st.rerun()

                    # 특이사항(장시간/심야/스케줄 차이) 건은 확인 사유 입력 없이는 승인 불가
                    if anomaly_rows:
                        st.divider()
                        st.markdown("🚨 **특이 근무 건별 검토 (확인 사유 입력 필수)**")
                        for r_dict, flags in anomaly_rows:
                            r_num = int(r_dict["_sheet_row"])
                            flag_txt = ", ".join(flags)
                            st.warning(
                                f"[{r_dict['날짜'][5:]}] **{r_dict['이름']}** `{r_dict['시작시간']}~{r_dict['종료시간']}` ({r_dict['총시간(h:m)']})\n\n사유 감지: **{flag_txt}**"
                            )
                            mgr_note = st.text_input(
                                "매니저 확인 사유",
                                placeholder="예: 단체 손님 마감 정리로 연장 근무 확인",
                                key=f"anom_note_{r_num}",
                            )
                            if st.button(
                                f"사유 기록 후 {r_dict['이름']} 승인",
                                key=f"anom_btn_{r_num}",
                                disabled=len(mgr_note.strip()) == 0,
                                use_container_width=True,
                            ):
                                gc = get_gspread_client()
                                ws = gc.open_by_key(store_cfg["db_id"]).worksheet("통합근태DB")
                                now_s = datetime.datetime.now().strftime("%m/%d %H:%M:%S")
                                now_f = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                old_n = str(r_dict.get("비고", ""))
                                new_n = f"{old_n}\n[{now_s}] 매니저 특이승인({flag_txt}): {mgr_note.strip()}".strip()
                                ws.update(range_name=f"H{r_num}:J{r_num}", values=[["TRUE", new_n, now_f]])
                                st.success("특이 근무 승인 완료!")
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
                                st.warning("승인이 해제되어 직원이 다시 수정할 수 있습니다.")
                                st.cache_data.clear()
                                st.rerun()
        elif pin_input:
            st.error("매니저 PIN이 일치하지 않습니다.")
        else:
            st.caption("매니저 확인 전까지는 직원이 직접 수정할 수 있으며, 확인 완료 후에는 잠금 처리됩니다.")

# =========================================================================
# 5. [하단 구역] 좌측: 출퇴근 입력/수정 | 우측: 주간 & 지난 월별 누적 조회
# =========================================================================
left_col, right_col = st.columns([1.4, 1.05])

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
                badge = "확인완료🔒(수정불가)" if is_app else "대기중✏️(수정가능)"
                action_opts.append(
                    f"수정: [{r.get('근무타임', '')}] {r.get('시작시간')}~{r.get('종료시간')} ({badge}) (행:{r['_sheet_row']})"
                )

            chosen_action = st.radio("작업 선택", options=action_opts)
            if chosen_action.startswith("수정:"):
                mode = "기존 수정"
                target_sheet_row = int(chosen_action.split("(행:")[1].replace(")", ""))
                old_record = emp_today[emp_today["_sheet_row"] == target_sheet_row].iloc[0].to_dict()

        is_locked = (mode == "기존 수정") and (str(old_record.get("매니저확인", "")).strip().upper() == "TRUE")
        if is_locked:
            st.error("🚫 매니저 확인이 완료된 기록은 수정할 수 없습니다. 수정이 필요하면 매니저에게 확인 해제를 요청하세요.")

        default_shift_idx = 0
        if mode == "기존 수정":
            old_t = str(old_record.get("근무타임", "")).strip()
            if old_t in SHIFT_OPTIONS:
                default_shift_idx = SHIFT_OPTIONS.index(old_t)
        else:
            if sel_date.weekday() >= 5:
                default_shift_idx = 1 if len(emp_today) == 0 else 2
            else:
                default_shift_idx = 0

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
                st.success("✅ 수정 완료! 변경 전/후 시간과 사유가 기록되었습니다.")
            else:
                row_values = [date_str, real_emp_name, shift_type, s_str, e_str, hm_str, dec_hours, "FALSE", memo_val.strip(), now_full]
                ws.append_row(row_values, value_input_option="USER_ENTERED")
                st.success(f"✅ {real_emp_name} 님의 근무 기록({s_str}~{e_str})이 저장되었습니다.")

            st.cache_data.clear()
            st.rerun()

with right_col:
    st.markdown(f'<div class="section-title">3. {real_emp_name} 님 주간 / 월별 근무시간 조회</div>', unsafe_allow_html=True)

    # 최근 6개월 정산월 선택 드롭다운 (지난 월별 근무시간 간편 조회)
    month_options = get_recent_payroll_months(datetime.date.today(), count=6)
    sel_month_label = st.selectbox("조회할 정산월 선택", options=list(month_options.keys()), index=0)
    m_start, m_end = month_options[sel_month_label]

    w_start = sel_date - datetime.timedelta(days=sel_date.weekday())

    if not df_att.empty and "이름" in df_att.columns:
        emp_all = df_att[df_att["이름"] == real_emp_name]

        w_df = emp_all[(emp_all["날짜_dt"] >= w_start) & (emp_all["날짜_dt"] <= sel_date)]
        w_mins = int(round(w_df["총시간(소수)"].sum() * 60))

        m_df = emp_all[(emp_all["날짜_dt"] >= m_start) & (emp_all["날짜_dt"] <= m_end)]
        m_mins = int(round(m_df["총시간(소수)"].sum() * 60))
        confirmed_cnt = (
            len(m_df[m_df["매니저확인"].astype(str).str.upper() == "TRUE"])
            if "매니저확인" in m_df.columns
            else 0
        )

        mc1, mc2 = st.columns(2)
        with mc1:
            st.metric(
                label=f"선택 주간 ({w_start.strftime('%m/%d')}~{sel_date.strftime('%m/%d')})",
                value=mins_to_korean(w_mins),
                delta=f"{mins_to_hm(w_mins)} ({len(w_df)}건)",
                delta_color="off",
            )
        with mc2:
            st.metric(
                label=f"선택 정산월 ({m_start.strftime('%m/%d')}~{m_end.strftime('%m/%d')})",
                value=mins_to_korean(m_mins),
                delta=f"{mins_to_hm(m_mins)} · 확인 {confirmed_cnt}/{len(m_df)}건",
                delta_color="off",
            )

        with st.expander("📋 선택한 정산월 일별 근무 내역", expanded=True):
            if not m_df.empty:
                m_disp = m_df[["날짜", "근무타임", "시작시간", "종료시간", "총시간(h:m)", "매니저확인"]].sort_values(
                    "날짜", ascending=False
                )
                st.dataframe(m_disp, use_container_width=True, hide_index=True, height=230)
            else:
                st.caption("선택한 정산월에 등록된 근무 기록이 없습니다.")
    else:
        st.caption("누적 근무 내역이 없습니다.")
