"""
================================================================================
[파일명] views/schedule_submit.py
[역할] 파트타임 직원이 전용 링크(?schedule=매장명)로 접속해 다음 주 출근 희망시간
       또는 고정 스케줄 예외(휴무 요청)를 제출하는 모바일 최적화 전용 페이지
================================================================================
"""

from urllib.parse import unquote
import streamlit as st

from store_registry import load_all_stores, load_store_settings, MASTER_DB_ID
from ui_styles import apply_base_theme, render_section_banner
from schedule_utils import (
    DAY_NAMES,
    WEEKDAY_TIME_PRESETS,
    WEEKEND_TIME_PRESETS,
    OFF_REQUEST_TOKEN,
    get_selectable_weeks,
    get_week_dates,
    load_schedule_bundle,
    upsert_employee_request,
    normalize_time_cell,
)

apply_base_theme(max_width=760)
st.markdown(
    """
    <style>
        [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

raw_store_param = str(st.query_params.get("schedule", "")).strip()
all_stores_map = load_all_stores(include_inactive=True)

if raw_store_param and raw_store_param.lower() not in ("1", "true", "default"):
    store_name = raw_store_param
    if store_name not in all_stores_map:
        decoded = unquote(raw_store_param).strip()
        if decoded in all_stores_map:
            store_name = decoded
    if store_name not in all_stores_map:
        st.error(f"등록되지 않은 매장('{raw_store_param}')의 스케줄 링크입니다. 매니저에게 링크를 다시 요청해 주세요.")
        st.stop()
    store_info = all_stores_map[store_name]
else:
    store_name = "분당그릴"
    store_info = None
    for s_nm, s_inf in all_stores_map.items():
        if s_inf.get("db_id") == MASTER_DB_ID:
            store_name = s_nm
            store_info = s_inf
            break
    if store_info is None and all_stores_map:
        store_name = next(iter(all_stores_map))
        store_info = all_stores_map[store_name]

target_db_id = store_info["db_id"]
app_cfg = load_store_settings(target_db_id, store_name)
store_title = str(app_cfg.get("store_title") or store_name).strip()

st.markdown(
    f"""
    <div class="page-hero">
        <div class="page-hero-title">▪&nbsp;&nbsp;[{store_title}] 파트타임 주간스케줄 신청</div>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    active_part_names, df_fixed, df_weekly = load_schedule_bundle(target_db_id)
except Exception as e:
    st.error(f"스케줄 정보를 불러오는 중 오류가 발생했습니다: {e}")
    st.stop()

if not active_part_names:
    st.warning("현재 등록된 재직 파트타임 직원이 없습니다. 매니저에게 문의해 주세요.")
    st.stop()

week_options, default_w_idx = get_selectable_weeks()
c_w, c_n = st.columns(2)
with c_w:
    sel_week_label = st.selectbox("1. 신청할 주차 선택", options=list(week_options.keys()), index=default_w_idx)
    sel_monday = week_options[sel_week_label]
    week_str = sel_monday.strftime("%Y-%m-%d")
    week_dates = get_week_dates(sel_monday)

with c_n:
    PLACEHOLDER = "본인 이름을 선택하세요"
    sel_emp = st.selectbox("2. 본인 이름 선택", options=[PLACEHOLDER] + active_part_names, index=0)

if sel_emp == PLACEHOLDER:
    st.info("위에서 **신청할 주차**와 **본인 이름**을 선택하면 요일별 출근시간 입력창이 열립니다.")
    st.stop()

# 고정 스케줄 템플릿 조회
emp_fixed_row = {}
is_fixed_emp = False
if not df_fixed.empty:
    matched_f = df_fixed[df_fixed["이름"].str.strip() == sel_emp]
    if not matched_f.empty:
        emp_fixed_row = matched_f.iloc[0].to_dict()
        is_fixed_emp = str(emp_fixed_row.get("구분", "")).strip() == "고정"

# 기존에 제출한 요청이 있는지 조회
prev_req_row = {}
if not df_weekly.empty:
    matched_r = df_weekly[
        (df_weekly["주차"].str.strip() == week_str)
        & (df_weekly["구분"].str.strip() == "직원요청")
        & (df_weekly["이름"].str.strip() == sel_emp)
    ]
    if not matched_r.empty:
        prev_req_row = matched_r.iloc[-1].to_dict()

if is_fixed_emp:
    render_section_banner(
        f"{sel_emp} 님 — 고정 스케줄 직원",
        badge="예외(휴무·변경)만 수정",
        subtitle="평소 고정 출근시간이 미리 채워져 있습니다. 변동이 없으면 제출하지 않으셔도 그대로 반영됩니다.",
        accent="blue",
    )
else:
    render_section_banner(
        f"{sel_emp} 님 — 출근 가능 시간 신청",
        badge="출근시간만 선택",
        subtitle="출근 가능한 요일의 출근시간만 선택해 주세요. (못 나오는 날은 '휴무' 유지)",
        accent="emerald",
    )

if prev_req_row:
    st.success(f"이미 제출된 내역이 있습니다 (최근 제출: {prev_req_row.get('수정일시', '')}). 내용을 수정해서 다시 제출하면 최신 내용으로 덮어씌워집니다.")

st.write("")
chosen_days = {}

with st.container(border=True):
    for idx, d in enumerate(DAY_NAMES):
        dt = week_dates[idx]
        is_wknd = idx >= 5
        fixed_val = normalize_time_cell(emp_fixed_row.get(d, "")) if is_fixed_emp else ""
        prev_val = str(prev_req_row.get(d, "")).strip() if prev_req_row else ""

        # 초기 표시값 결정: 기존 제출값 우선 -> 없으면 고정 템플릿 -> 없으면 휴무
        if prev_req_row:
            init_val = prev_val if prev_val else "휴무"
        elif fixed_val:
            init_val = fixed_val
        else:
            init_val = "휴무"

        base_presets = list(WEEKEND_TIME_PRESETS if is_wknd else WEEKDAY_TIME_PRESETS)
        if is_fixed_emp and fixed_val:
            # 고정 근무일이면 '❌휴무요청'을 맨 앞 옵션 중 하나로 노출해 직관적으로 선택 가능
            presets = [OFF_REQUEST_TOKEN] + [x for x in base_presets if x != "휴무"]
        else:
            presets = base_presets

        if init_val in presets:
            def_opt_idx = presets.index(init_val)
            def_custom = ""
        else:
            def_opt_idx = presets.index("직접입력")
            def_custom = init_val

        day_color = "#DC2626" if idx == 6 else ("#2563EB" if idx == 5 else "#0F172A")
        fixed_tag = (
            f' <span style="font-size:0.78rem; background:#DBEAFE; color:#1E40AF; padding:2px 7px; border-radius:999px; font-weight:700;">고정 {fixed_val}</span>'
            if fixed_val
            else ""
        )

        rc1, rc2, rc3 = st.columns([1.15, 1.35, 1.0], vertical_alignment="center")
        with rc1:
            st.markdown(
                f'<div style="font-size:0.98rem; font-weight:800; color:{day_color};">{d}요일 ({dt.strftime("%m/%d")}){fixed_tag}</div>',
                unsafe_allow_html=True,
            )
        with rc2:
            sel_t = st.selectbox(
                f"{d}요일 출근시간",
                options=presets,
                index=def_opt_idx,
                key=f"sub_t_{store_name}_{week_str}_{sel_emp}_{d}",
                label_visibility="collapsed",
            )
        with rc3:
            if sel_t == "직접입력":
                custom_t = st.text_input(
                    f"{d}요일 직접입력",
                    value=def_custom,
                    placeholder="예: 16:30",
                    key=f"sub_c_{store_name}_{week_str}_{sel_emp}_{d}",
                    label_visibility="collapsed",
                )
                chosen_days[d] = custom_t.strip()
            elif sel_t == "휴무":
                chosen_days[d] = ""
            else:
                chosen_days[d] = sel_t

    memo_in = st.text_input(
        "매니저에게 남길 메모 (선택)",
        value=str(prev_req_row.get("메모", "")),
        placeholder="예: 수요일 시험이라 18시 출근 가능 / 토요일 점심만 가능",
        key=f"sub_memo_{store_name}_{week_str}_{sel_emp}",
    )

    if st.button("다음 주 희망 스케줄 제출하기", type="primary", use_container_width=True):
        with st.spinner("매니저에게 스케줄 요청을 저장하는 중..."):
            upsert_employee_request(target_db_id, week_str, sel_emp, chosen_days, memo_in)
            load_schedule_bundle.clear(target_db_id)

        summary_parts = []
        for idx, d in enumerate(DAY_NAMES):
            v = chosen_days.get(d, "")
            if v:
                summary_parts.append(f"{d}({v})")
        summary_str = ", ".join(summary_parts) if summary_parts else "전체 휴무"
        st.success(f"**{sel_emp}** 님의 {sel_week_label} 스케줄 요청이 접수되었습니다.\n\n• 제출 내용: `{summary_str}`")
