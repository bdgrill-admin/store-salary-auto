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

apply_base_theme(max_width=1360)

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
    top_c1, top_c2 = st.columns([1.3, 1.7], vertical_alignment="bottom")
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
        st.caption("직원 단톡방 공지용 신청 링크 (로그인 없이 출근 희망·휴무 요청 제출)")
        st.code(submit_link, language="text")

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

    # 1) 직원 제출 현황 (요청 / 고정 예외)
    req_cnt = len(df_req_week)
    render_section_banner(
        "1. 직원 희망 · 휴무 요청 접수 현황",
        badge=f"제출 {req_cnt}명",
        subtitle="고정 직원은 빠지는 날(휴무요청)이나 시간 변경 시에만 제출합니다",
        accent="amber",
    )
    if df_req_week.empty:
        st.info("아직 직원이 링크로 제출한 요청이 없습니다. 아래에서 [고정 스케줄만 자동 채우기] 후 직접 수정하셔도 됩니다.")
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

    render_section_banner(
        f"2. [{sel_week_label}] 최종 출근 스케줄 편집 · 확정",
        badge=("확정본 저장됨" if not df_conf_week.empty else "초안 작성중"),
        subtitle="퇴근시간 없이 출근시간만 입력합니다 (예: 17:00, 12:00, 12:00/17:00 · 빈칸=휴무)",
        accent="blue",
    )

    act_c1, act_c2, act_c3 = st.columns(3)
    with act_c1:
        if st.button("고정 스케줄만 자동 채우기", use_container_width=True, key=f"btn_fill_fixed_{selected_store}_{week_str}"):
            st.session_state[draft_state_key] = build_draft_schedule(
                active_part_names, df_fixed_synced, df_conf_week, df_req_week, mode="fixed_only"
            )
            st.session_state[draft_ver_key] += 1
            st.rerun()
    with act_c2:
        if st.button("고정 + 직원요청 자동 병합", use_container_width=True, key=f"btn_merge_req_{selected_store}_{week_str}"):
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

    col_cfg = {
        "이름": st.column_config.TextColumn("이름", required=True),
        "구분": st.column_config.SelectboxColumn("구분", options=["고정", "유동"], default="유동"),
        "메모": st.column_config.TextColumn("메모"),
    }
    for i, d in enumerate(DAY_NAMES):
        col_cfg[d] = st.column_config.TextColumn(f"{d} ({week_dates[i].strftime('%m/%d')})", help="출근시간 예: 17:00 / 12:00 / 빈칸=휴무")

    edited_schedule = st.data_editor(
        st.session_state[draft_state_key],
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"sched_editor_{selected_store}_{week_str}_{st.session_state[draft_ver_key]}",
        column_config=col_cfg,
    )

    # 요일별 인원 요약 바 (실시간 계산)
    daily_summary = summarize_daily_staff(edited_schedule)
    summary_cards_html = []
    for i, d in enumerate(DAY_NAMES):
        info = daily_summary[d]
        cnt = info["count"]
        if cnt == 0:
            bg, bd, tx = "#FFF1F2", "#FECDD3", "#BE123C"
        elif cnt == 1:
            bg, bd, tx = "#FFFBEB", "#FDE68A", "#B45309"
        else:
            bg, bd, tx = "#ECFDF5", "#A7F3D0", "#047857"
        extra = ""
        if i >= 5 and cnt > 0:
            extra = f"<div style='font-size:0.74rem; color:#475569;'>점심 {len(info['lunch'])} · 저녁 {len(info['dinner'])}</div>"
        summary_cards_html.append(
            f"<div style='flex:1 1 110px; background:{bg}; border:1px solid {bd}; border-radius:10px; padding:8px 10px; text-align:center;'>"
            f"<div style='font-size:0.8rem; font-weight:700; color:#334155;'>{d} ({week_dates[i].strftime('%m/%d')})</div>"
            f"<div style='font-size:1.15rem; font-weight:800; color:{tx};'>{cnt}명</div>"
            f"{extra}</div>"
        )
    st.markdown(
        f"<div style='display:flex; flex-wrap:wrap; gap:8px; margin:8px 0 12px 0;'>{''.join(summary_cards_html)}</div>",
        unsafe_allow_html=True,
    )

    if st.button("주간 스케줄 확정 저장하기 (출퇴근기록부 자동 연동)", type="primary", use_container_width=True):
        with st.spinner("구글 시트 '주간스케줄' 탭에 확정 저장 중..."):
            save_confirmed_week_schedule(store_cfg["db_id"], week_str, edited_schedule)
            st.session_state[draft_state_key] = edited_schedule.copy()
            load_schedule_bundle.clear(store_cfg["db_id"])
            st.success(f"[{store_title}] {sel_week_label} 주간 스케줄이 확정 저장되었습니다.")
            st.rerun()

    # 3) 단톡방 공유 (카톡 텍스트 + 시간표 이미지 PNG 둘 다!)
    render_section_banner(
        "3. 카카오톡 단톡방 공유 (텍스트 복사 · 시간표 이미지)",
        badge="텍스트 + PNG",
        subtitle="아래 텍스트를 복사하거나 이미지를 저장해 직원 단톡방에 바로 올려주세요",
        accent="emerald",
    )

    kakao_text = build_kakao_schedule_text(store_title, sel_monday, edited_schedule)
    png_bytes = generate_schedule_png(store_title, sel_monday, edited_schedule)
    png_filename = f"{store_title}_주간스케줄_{sel_monday.strftime('%Y%m%d')}.png"

    sh_left, sh_right = st.columns([1.0, 1.35])
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
        "이름": st.column_config.TextColumn("이름", required=True),
        "구분": st.column_config.SelectboxColumn("유형", options=["고정", "유동"], default="유동"),
        "메모": st.column_config.TextColumn("메모 (예: 주말 점심 고정)"),
    }
    for d in DAY_NAMES:
        fixed_col_cfg[d] = st.column_config.TextColumn(f"{d}요일", help="출근시간 예: 17:00 / 빈칸=휴무")

    edited_fixed = st.data_editor(
        df_fixed_synced,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
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
        st.dataframe(hist_sub, use_container_width=True, hide_index=True, row_height=28)
