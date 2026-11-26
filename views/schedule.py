"""
================================================================================
[파일명] views/schedule.py
[역할] 매니저/관리자 전용 '파트타임 주간 스케줄 관리 · 고정 템플릿 · 카톡/이미지 공유' 페이지
================================================================================
"""

from urllib.parse import urlencode
import pandas as pd
import streamlit as st

from store_registry import (
    load_all_stores,
    load_store_settings,
    dispatch_telegram_alert,
)
from ui_styles import apply_base_theme, render_section_banner
from schedule_utils import (
    DAY_NAMES,
    FIXED_HEADERS,
    OFF_REQUEST_TOKEN,
    get_selectable_weeks,
    get_week_dates,
    load_schedule_bundle,
    save_fixed_templates,
    save_confirmed_week_schedule,
    summarize_daily_staff,
    build_kakao_schedule_text,
    generate_schedule_png,
    normalize_time_cell,
)

APP_BASE_URL = "https://store-salary-auto-5xqyisbltbombukh3zltva.streamlit.app/"

apply_base_theme(max_width=1380)

# 주간스케줄 전용 컴팩트 스타일 주입
st.markdown(
    """
    <style>
    /* 상단 컨트롤 및 입력폼 여백 최소화 */
    .st-key-sched_top_bar div[data-testid="stHorizontalBlock"] {
        align-items: flex-end !important;
        gap: 0.75rem !important;
    }
    /* 버튼 텍스트 줄바꿈 방지 */
    .stButton button {
        white-space: nowrap !important;
        font-weight: 600 !important;
    }
    /* Expander 헤더 강조 및 여백 압축 */
    details[data-testid="stExpander"] summary {
        font-size: 0.88rem !important;
        font-weight: 700 !important;
        color: #334155 !important;
        padding-top: 0.4rem !important;
        padding-bottom: 0.4rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

STORES = load_all_stores()

h1, h2, h3 = st.columns([2.3, 1.0, 0.85], vertical_alignment="center")
with h1:
    st.markdown('<div class="app-title">▪&nbsp;&nbsp;주간스케줄</div>', unsafe_allow_html=True)
with h2:
    selected_store = st.selectbox("매장 선택", list(STORES.keys()), index=0, label_visibility="collapsed", key="sched_store_sel")
with h3:
    if st.button("새로고침", use_container_width=True, key="sched_refresh_btn"):
        st.cache_data.clear()
        st.rerun()

store_cfg = STORES[selected_store]
app_cfg = load_store_settings(store_cfg["db_id"], selected_store)
active_mgr_pin = str(app_cfg.get("manager_pin") or store_cfg.get("manager_pin") or "0524").strip()
store_title = str(app_cfg.get("store_title") or selected_store).strip()

is_unlocked = st.session_state.get("authenticated", False) or st.session_state.get("staff_mgr_unlocked", False)
if not is_unlocked:
    st.write("")
    _, c_mid, _ = st.columns([1.1, 1.4, 1.1])
    with c_mid:
        with st.container(border=True):
            st.markdown(f"#### 🔐 [{store_title}] 매니저 / 관리자 전용")
            st.caption("주간 스케줄 관리 및 확정을 위해 비밀번호를 입력하세요.")
            with st.form(key=f"sched_pin_form_{selected_store}", border=False):
                pin = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력", label_visibility="collapsed")
                submitted_pin = st.form_submit_button("확인", type="primary", use_container_width=True)
            if submitted_pin:
                if pin == active_mgr_pin:
                    st.session_state["staff_mgr_unlocked"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()

try:
    active_part_names, df_fixed, df_weekly = load_schedule_bundle(store_cfg["db_id"])
except Exception as e:
    st.error(f"스케줄 시트 연결 오류: {e}")
    st.stop()


def build_fixed_template_table(active_names: list, df_fix: pd.DataFrame) -> pd.DataFrame:
    """재직 파트타임 명부 기준으로 고정/유동 템플릿 표를 동기화합니다."""
    fix_map = {}
    if df_fix is not None and not df_fix.empty:
        for _, r in df_fix.iterrows():
            nm = str(r.get("이름", "")).strip()
            if nm:
                fix_map[nm] = r.to_dict()

    rows = []
    seen = set()
    for nm in active_names:
        seen.add(nm)
        base = fix_map.get(nm, {})
        rows.append({
            "이름": nm,
            "구분": "고정" if str(base.get("구분", "")).strip() == "고정" else "유동",
            **{d: normalize_time_cell(base.get(d, "")) for d in DAY_NAMES},
            "메모": str(base.get("메모", "")).strip(),
        })
    for nm, base in fix_map.items():
        if nm not in seen:
            rows.append({
                "이름": nm,
                "구분": "고정" if str(base.get("구분", "")).strip() == "고정" else "유동",
                **{d: normalize_time_cell(base.get(d, "")) for d in DAY_NAMES},
                "메모": str(base.get("메모", "")).strip(),
            })
    return pd.DataFrame(rows, columns=FIXED_HEADERS)


def build_draft_schedule(
    active_names: list,
    df_fix_sync: pd.DataFrame,
    df_conf_week: pd.DataFrame,
    df_req_week: pd.DataFrame,
    mode: str = "existing",
) -> pd.DataFrame:
    """
    mode:
      - 'existing': 이미 확정된 스케줄이 있으면 우선 표시, 없으면 고정 템플릿 + 직원요청 병합
      - 'fixed_only': 고정 직원 기본 시간표만 자동 채우기
      - 'merge_requests': 고정 템플릿에 직원 요청(휴무요청 제거 + 시간 변경/유동 신청) 일괄 병합
    """
    fix_map = {str(r["이름"]).strip(): r.to_dict() for _, r in df_fix_sync.iterrows()} if not df_fix_sync.empty else {}
    conf_map = {str(r["이름"]).strip(): r.to_dict() for _, r in df_conf_week.iterrows()} if not df_conf_week.empty else {}
    req_map = {str(r["이름"]).strip(): r.to_dict() for _, r in df_req_week.iterrows()} if not df_req_week.empty else {}

    all_names = list(active_names)
    for m in (conf_map, req_map, fix_map):
        for nm in m.keys():
            if nm and nm not in all_names:
                all_names.append(nm)

    use_existing = (mode == "existing") and bool(conf_map)
    rows = []
    for nm in all_names:
        f_row = fix_map.get(nm, {})
        c_row = conf_map.get(nm, {})
        r_row = req_map.get(nm, {})
        emp_gubun = "고정" if str(f_row.get("구분", "")).strip() == "고정" else "유동"

        row_dict = {"이름": nm, "구분": emp_gubun}
        if use_existing:
            for d in DAY_NAMES:
                row_dict[d] = normalize_time_cell(c_row.get(d, ""))
            row_dict["메모"] = str(c_row.get("메모", "") or r_row.get("메모", "")).strip()
        elif mode == "fixed_only":
            for d in DAY_NAMES:
                row_dict[d] = normalize_time_cell(f_row.get(d, "")) if emp_gubun == "고정" else ""
            row_dict["메모"] = str(f_row.get("메모", "")).strip()
        else:
            # merge_requests (or existing when no confirmed schedule yet)
            for d in DAY_NAMES:
                if r_row:
                    rv = str(r_row.get(d, "")).strip()
                    if rv == OFF_REQUEST_TOKEN or rv in ("휴무", "-", "없음"):
                        row_dict[d] = ""
                    elif rv:
                        row_dict[d] = rv
                    else:
                        row_dict[d] = ""
                else:
                    row_dict[d] = normalize_time_cell(f_row.get(d, "")) if emp_gubun == "고정" else ""
            row_dict["메모"] = str(r_row.get("메모", "") or f_row.get("메모", "")).strip()

        rows.append(row_dict)

    return pd.DataFrame(rows, columns=["이름", "구분", *DAY_NAMES, "메모"])


def render_daily_headcount_cards(daily_summary: dict, week_dates: list) -> str:
    """요일별 출근 인원 요약 헤드카운트 바 HTML을 생성합니다."""
    cards_html = []
    total_shifts = sum(info["count"] for info in daily_summary.values())

    for i, d in enumerate(DAY_NAMES):
        info = daily_summary[d]
        cnt = info["count"]
        is_weekend = (i >= 5)

        if cnt == 0:
            bg, bd, tx, sub_tx = "#FFF1F2", "#FECDD3", "#BE123C", "#9F1239"
        elif cnt == 1:
            bg, bd, tx, sub_tx = "#FFFBEB", "#FDE68A", "#B45309", "#92400E"
        else:
            if not is_weekend:
                bg, bd, tx, sub_tx = "#F0FDF4", "#BBF7D0", "#15803D", "#166534"
            else:
                bg, bd, tx, sub_tx = "#EFF6FF", "#BFDBFE", "#1D4ED8", "#1E40AF"

        date_str = week_dates[i].strftime("%m/%d")

        if is_weekend and cnt > 0:
            l_cnt = len(info.get("lunch", []))
            d_cnt = len(info.get("dinner", []))
            extra_html = f"<div style='font-size:0.72rem; color:{sub_tx}; font-weight:600; margin-top:2px;'>점심 {l_cnt} · 저녁 {d_cnt}</div>"
        elif cnt > 0:
            extra_html = f"<div style='font-size:0.72rem; color:{sub_tx}; font-weight:500; margin-top:2px;'>저녁 배정</div>"
        else:
            extra_html = f"<div style='font-size:0.72rem; color:#BE123C; font-weight:700; margin-top:2px;'>인원 없음</div>"

        cards_html.append(
            f"<div style='flex:1 1 0; min-width:82px; background:{bg}; border:1.5px solid {bd}; "
            f"border-radius:10px; padding:7px 4px; text-align:center; box-shadow:0 1px 2px rgba(0,0,0,0.03);'>"
            f"<div style='font-size:0.78rem; font-weight:700; color:#334155;'>{d} <span style='font-size:0.73rem; font-weight:500; color:#64748B;'>{date_str}</span></div>"
            f"<div style='font-size:1.18rem; font-weight:800; color:{tx}; margin-top:1px; line-height:1.2;'>{cnt}명</div>"
            f"{extra_html}"
            f"</div>"
        )

    return f"""
    <div style='margin: 0.35rem 0 0.75rem 0;'>
      <div style='display:flex; justify-content:space-between; align-items:center; margin-bottom:0.35rem;'>
        <span style='font-size:0.83rem; font-weight:700; color:#475569;'>▪ 요일별 출근 인원 현황 (실시간 집계)</span>
        <span style='font-size:0.78rem; font-weight:700; background:#E2E8F0; color:#334155; padding:2px 9px; border-radius:12px;'>주간 총 {total_shifts}개 시프트 배정</span>
      </div>
      <div style='display:flex; flex-wrap:wrap; gap:6px;'>
        {''.join(cards_html)}
      </div>
    </div>
    """


df_fixed_synced = build_fixed_template_table(active_part_names, df_fixed)

tab_plan, tab_fixed, tab_hist = st.tabs([
    "1. 주간스케줄 작성 · 공유",
    "2. 고정 · 유동 템플릿 설정",
    "3. 확정 스케줄 이력",
])

# ==============================================================================
# [탭 1] 주간 스케줄 작성 · 확정 · 단톡방 공유 (카톡 텍스트 + PNG 이미지)
# ==============================================================================
with tab_plan:
    week_options, default_w_idx = get_selectable_weeks()

    # 상단 1줄 컴팩트 컨트롤 바 (주차 선택 + 단톡방 공지 신청 링크)
    top_c1, top_c2 = st.columns([1.15, 1.85], vertical_alignment="bottom")
    with top_c1:
        sel_week_label = st.selectbox(
            "작성할 주차 선택",
            options=list(week_options.keys()),
            index=default_w_idx,
            key=f"sched_week_sel_{selected_store}",
        )
        sel_monday = week_options[sel_week_label]
        week_str = sel_monday.strftime("%Y-%m-%d")
        week_dates = get_week_dates(sel_monday)

    with top_c2:
        submit_link = f"{APP_BASE_URL}?{urlencode({'schedule': selected_store})}"
        st.text_input(
            "직원 신청 링크 (클릭 후 복사하여 단톡방 공지 · 로그인 불필요)",
            value=submit_link,
            key=f"sched_link_input_{selected_store}",
            help="이 링크를 직원 단톡방에 공유하면 파트타이머들이 출근 희망 요일 및 휴무 요청을 간편하게 제출할 수 있습니다.",
        )

    df_conf_week = (
        df_weekly[
            (df_weekly["주차"].str.strip() == week_str) & (df_weekly["구분"].str.strip() == "확정")
        ].copy()
        if not df_weekly.empty
        else pd.DataFrame()
    )
    df_req_week = (
        df_weekly[
            (df_weekly["주차"].str.strip() == week_str) & (df_weekly["구분"].str.strip() == "직원요청")
        ].copy()
        if not df_weekly.empty
        else pd.DataFrame()
    )

    req_cnt = len(df_req_week)
    req_status_label = f"접수 {req_cnt}명 확인하기" if req_cnt > 0 else "접수 내역 없음 (고정 스케줄로 바로 작성 가능)"

    # 1) 직원 희망 · 휴무 요청 현황 (접수 건수 있을 때만 기본 펼침으로 화면 세로 공간 절약)
    with st.expander(f"1. 직원 희망 · 휴무 요청 현황 [{req_status_label}]", expanded=(req_cnt > 0)):
        if df_req_week.empty:
            st.info("아직 직원이 신청 링크로 제출한 요청이 없습니다. 아래에서 [고정 스케줄 자동 채우기]로 바로 시간표 작성을 시작할 수 있습니다.")
        else:
            req_disp = df_req_week[["이름", *DAY_NAMES, "메모", "수정일시"]].copy()
            req_disp["수정일시"] = req_disp["수정일시"].astype(str).str.slice(5, 16)
            st.dataframe(req_disp, use_container_width=True, hide_index=True, row_height=28)

    # 2) 초안 상태 관리 (버튼으로 고정 채우기 / 직원요청 병합 지원)
    draft_state_key = f"sched_draft_df_{selected_store}_{week_str}"
    draft_ver_key = f"sched_draft_ver_{selected_store}_{week_str}"
    if draft_ver_key not in st.session_state:
        st.session_state[draft_ver_key] = 0
    if draft_state_key not in st.session_state:
        st.session_state[draft_state_key] = build_draft_schedule(
            active_part_names, df_fixed_synced, df_conf_week, df_req_week, mode="existing"
        )

    is_confirmed = not df_conf_week.empty
    render_section_banner(
        f"2. [{sel_week_label}] 출근 스케줄 편집 · 확정",
        badge=("확정본 저장됨" if is_confirmed else "초안 작성중"),
        subtitle="출근 시간만 입력 (예: 17:00 / 12:00 / 빈칸=휴무 · 상단 인원수 실시간 집계)",
        accent=("emerald" if is_confirmed else "blue"),
    )

    # 액션 버튼 3종 (한눈에 알아보기 쉬운 라벨과 배치)
    act_c1, act_c2, act_c3 = st.columns([1.1, 1.3, 1.1])
    with act_c1:
        if st.button("고정 스케줄 자동 채우기", use_container_width=True, key=f"btn_fill_fixed_{selected_store}_{week_str}"):
            st.session_state[draft_state_key] = build_draft_schedule(
                active_part_names, df_fixed_synced, df_conf_week, df_req_week, mode="fixed_only"
            )
            st.session_state[draft_ver_key] += 1
            st.rerun()
    with act_c2:
        if st.button("고정 + 직원요청 자동 병합", type="secondary", use_container_width=True, key=f"btn_merge_req_{selected_store}_{week_str}", help="고정 직원의 기본 근무표에 링크로 접수된 휴무·변경 요청을 자동 병합합니다."):
            st.session_state[draft_state_key] = build_draft_schedule(
                active_part_names, df_fixed_synced, df_conf_week, df_req_week, mode="merge_requests"
            )
            st.session_state[draft_ver_key] += 1
            st.rerun()
    with act_c3:
        if st.button("저장된 확정본 다시 불러오기", use_container_width=True, key=f"btn_reload_conf_{selected_store}_{week_str}"):
            st.session_state[draft_state_key] = build_draft_schedule(
                active_part_names, df_fixed_synced, df_conf_week, df_req_week, mode="existing"
            )
            st.session_state[draft_ver_key] += 1
            st.rerun()

    # 인원수 요약 헤드카운트 바를 테이블 바로 위에 배치하기 위한 플레이스홀더
    summary_placeholder = st.empty()

    col_cfg = {
        "이름": st.column_config.TextColumn("이름", required=True, width="medium"),
        "구분": st.column_config.SelectboxColumn("구분", options=["고정", "유동"], default="유동", width="small"),
        "메모": st.column_config.TextColumn("메모", width="medium"),
    }
    for i, d in enumerate(DAY_NAMES):
        col_cfg[d] = st.column_config.TextColumn(
            f"{d} ({week_dates[i].strftime('%m/%d')})",
            help="출근시간 예: 17:00 / 12:00 / 빈칸=휴무",
            width="small",
        )

    current_draft_df = st.session_state[draft_state_key]
    row_count = len(current_draft_df)
    editor_height = min(460, max(210, 42 + 35 * (row_count + 1)))

    edited_schedule = st.data_editor(
        current_draft_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        height=editor_height,
        key=f"sched_editor_{selected_store}_{week_str}_{st.session_state[draft_ver_key]}",
        column_config=col_cfg,
    )

    # 테이블 바로 위 플레이스홀더에 실시간 계산된 요일별 인원 카드 주입
    daily_summary = summarize_daily_staff(edited_schedule)
    summary_placeholder.markdown(
        render_daily_headcount_cards(daily_summary, week_dates),
        unsafe_allow_html=True,
    )

    if st.button("주간 스케줄 확정 저장하기 (출퇴근기록부 자동 연동)", type="primary", use_container_width=True):
        with st.spinner("구글 시트 '주간스케줄' 탭에 확정 저장 중..."):
            save_confirmed_week_schedule(store_cfg["db_id"], week_str, edited_schedule)
            st.session_state[draft_state_key] = edited_schedule.copy()
            load_schedule_bundle.clear(store_cfg["db_id"])
            st.success(f"[{store_title}] {sel_week_label} 주간 스케줄이 확정 저장되었습니다.")
            st.rerun()

    # 3) 단톡방 공유 (카톡 텍스트 + 시간표 이미지 PNG)
    render_section_banner(
        "3. 카카오톡 단톡방 공유 (텍스트 복사 · 시간표 이미지)",
        badge="텍스트 + PNG",
        subtitle="단톡방에 텍스트를 복사하거나 이미지를 저장해 바로 공유하세요",
        accent="emerald",
    )

    kakao_text = build_kakao_schedule_text(store_title, sel_monday, edited_schedule)
    png_bytes = generate_schedule_png(store_title, sel_monday, edited_schedule)
    png_filename = f"{store_title}_주간스케줄_{sel_monday.strftime('%Y%m%d')}.png"

    sh_left, sh_right = st.columns([1.0, 1.25])
    with sh_left:
        with st.container(border=True):
            st.markdown("**카톡 단톡방 복사용 텍스트** *(우측 상단 복사 아이콘 클릭)*")
            st.code(kakao_text, language="text")
            if st.button("텔레그램으로 확정 스케줄 발송", use_container_width=True, key=f"btn_tg_sched_{selected_store}_{week_str}"):
                dispatch_telegram_alert(app_cfg, "tg_target_reg_change", kakao_text, default_target="모두")
                st.toast("텔레그램으로 확정 주간 스케줄을 발송했습니다.")
    with sh_right:
        with st.container(border=True):
            st.markdown("**모바일용 주간 시간표 이미지 (PNG)**")
            st.image(png_bytes, use_container_width=True)
            st.download_button(
                label="시간표 이미지(PNG) 다운로드",
                data=png_bytes,
                file_name=png_filename,
                mime="image/png",
                type="primary",
                use_container_width=True,
            )

# ==============================================================================
# [탭 2] 고정 · 유동 직원 템플릿 설정 (1회만 등록)
# ==============================================================================
with tab_fixed:
    render_section_banner(
        "파트타임 고정 · 유동 기본 스케줄 템플릿",
        badge="1회 설정 · 매주 자동 채우기",
        subtitle="고정 출근 직원은 구분을 '고정'으로 두고 요일별 기본 출근시간만 적어두세요 (예: 17:00, 12:00)",
        accent="indigo",
    )
    st.caption("재직 중인 파트타임 명부가 자동으로 불러와집니다. 고정 직원은 매주 금~토 신청 링크에 들어가도 기본 시간이 자동 입력되어 빠지는 날만 체크하면 됩니다.")

    fixed_col_cfg = {
        "이름": st.column_config.TextColumn("이름", required=True, width="medium"),
        "구분": st.column_config.SelectboxColumn("유형", options=["고정", "유동"], default="유동", width="small"),
        "메모": st.column_config.TextColumn("메모 (예: 주말 점심 고정)", width="medium"),
    }
    for d in DAY_NAMES:
        fixed_col_cfg[d] = st.column_config.TextColumn(f"{d}요일", help="출근시간 예: 17:00 / 빈칸=휴무", width="small")

    fixed_height = min(460, max(210, 42 + 35 * (len(df_fixed_synced) + 1)))

    edited_fixed = st.data_editor(
        df_fixed_synced,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        height=fixed_height,
        key=f"fixed_tpl_editor_{selected_store}",
        column_config=fixed_col_cfg,
    )

    if st.button("고정 · 유동 스케줄 템플릿 저장하기", type="primary", use_container_width=True):
        with st.spinner("구글 시트 '주간스케줄_고정' 탭에 저장 중..."):
            save_fixed_templates(store_cfg["db_id"], edited_fixed)
            load_schedule_bundle.clear(store_cfg["db_id"])
            st.success("고정 · 유동 스케줄 템플릿이 저장되었습니다.")
            st.rerun()

# ==============================================================================
# [탭 3] 과거 확정 스케줄 이력 조회
# ==============================================================================
with tab_hist:
    render_section_banner(
        "주간 확정 스케줄 이력 조회",
        badge="과거 기록",
        accent="slate",
    )
    df_all_conf = (
        df_weekly[df_weekly["구분"].str.strip() == "확정"].copy()
        if not df_weekly.empty
        else pd.DataFrame()
    )
    if df_all_conf.empty:
        st.info("아직 확정 저장된 주간 스케줄 이력이 없습니다.")
    else:
        saved_weeks = sorted(df_all_conf["주차"].unique().tolist(), reverse=True)
        sel_hist_w = st.selectbox("조회할 주차 (월요일 기준)", options=saved_weeks, index=0)
        hist_sub = df_all_conf[df_all_conf["주차"] == sel_hist_w][["이름", *DAY_NAMES, "메모", "수정일시"]].copy()

        hist_summary = summarize_daily_staff(hist_sub)
        hist_shifts = sum(info["count"] for info in hist_summary.values())
        st.caption(f"선택 주차 확정 배정: 총 {len(hist_sub)}명 · 총 {hist_shifts}개 시프트")

        st.dataframe(hist_sub, use_container_width=True, hide_index=True, row_height=28)
