"""
================================================================================
[파일명] views/settlement.py
[역할] 매장 월말정산 · 말일결제 체크 · 통장/카드 자동분류 · 손익/원가변동 대시보드
[주요 기능]
  1. 월말정산 1사이클 연동: 정산월(YY.MM) 매출·지출(말일 마감) + 급여히스토리 익월 탭(N월5일~N+1월4일, N+1월5일 입금) 인건비 자동 매칭
  2. 초록색 말일 후불 결제(9개 거래처) 전용 이체 체크리스트 + 선결제/수시결제 구분 관리
  3. 은행 거래내역 · 신용카드 · 네이버/쿠팡 쇼핑 엑셀 다중 업로드 → 키워드 자동 분류·합산·횟수 집계
  4. 종합 손익(매출·지출·인건비·순이익·원가율·인건비율) & 고기 부위별 원가변동 대시보드 + 엑셀 다운로드
  5. 기존 엑셀(★월말정산내역_분당그릴★.xlsx) 13개월 과거 데이터 원클릭 구글 시트 이관
================================================================================
"""

import datetime
import pandas as pd
import streamlit as st

from store_registry import (
    load_all_stores,
    load_store_settings,
)
from ui_styles import apply_base_theme, render_section_banner
from settlement_utils import (
    ENTRIES_HEADERS,
    MISC_HEADERS,
    MEAT_HEADERS,
    MEAT_MENU_SPECS,
    clean_int,
    clean_float,
    normalize_ym,
    next_ym,
    prev_ym,
    ym_to_kor,
    list_selectable_months,
    load_settlement_bundle,
    save_settlement_items_master,
    save_month_settlement,
    save_bulk_imported_settlement,
    load_sales_map,
    upsert_month_sales,
    load_payroll_history_map,
    parse_legacy_settlement_excel,
    read_uploaded_table,
    guess_tx_columns,
    classify_transactions,
    build_monthly_summary_df,
    build_meat_cost_trend_df,
    build_settlement_excel,
)

KST = datetime.timezone(datetime.timedelta(hours=9))
STORES = load_all_stores()

apply_base_theme(max_width=1360)
st.markdown(
    """
    <style>
    .app-header { padding: 0.1rem 0 0.4rem 0; }
    .kpi-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 0.4rem 0 0.9rem 0;
    }
    .kpi-card {
        flex: 1 1 200px;
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 0.75rem 0.95rem;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    }
    .kpi-label { font-size: 0.78rem; font-weight: 700; color: #64748B; }
    .kpi-val { font-size: 1.2rem; font-weight: 800; color: #0F172A; margin-top: 2px; }
    .kpi-sub { font-size: 0.76rem; color: #475569; margin-top: 3px; }
    .eom-pill {
        display: inline-block;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 700;
        margin-right: 6px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def kst_today() -> datetime.date:
    return datetime.datetime.now(KST).date()


# =========================================================================
# 1. 상단 헤더 & 지점 선택 + 관리자 인증
# =========================================================================
head_c1, head_c2 = st.columns([3.2, 1], vertical_alignment="center")
with head_c1:
    st.markdown(
        """
        <div class="app-header">
            <div class="app-title">▪&nbsp;&nbsp;월말정산 · 손익 · 원가분석</div>
            <div class="app-subtitle">말일 결제 체크 · 통장/카드 자동분류 · 급여히스토리(익월 5일 입금분) 연동 순이익 분석</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with head_c2:
    selected_store = st.selectbox("정산 매장", list(STORES.keys()), index=0, key="settle_store_sel")

store_cfg = STORES[selected_store]
app_cfg = load_store_settings(store_cfg["db_id"], selected_store)
admin_pw = str(app_cfg.get("admin_password", "0524")).strip()

auth_key = f"settle_auth_{selected_store}"
if not st.session_state.get(auth_key, False):
    with st.container(border=True):
        st.markdown(f"#### 🔒 [{selected_store}] 월말정산 관리자 인증")
        st.caption("매출·매입·순이익 정보가 포함되어 있어 관리자 비밀번호 입력 후 열람할 수 있습니다.")
        with st.form("settle_login_form", clear_on_submit=True):
            pw_in = st.text_input("관리자 비밀번호", type="password")
            submitted = st.form_submit_button("인증하기", type="primary", use_container_width=True)
            if submitted:
                if pw_in.strip() == admin_pw:
                    st.session_state[auth_key] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()


# =========================================================================
# 2. 데이터 일괄 로드 & 정산월 선택
# =========================================================================
bundle = load_settlement_bundle(store_cfg["db_id"])
df_items_master = bundle["items"]
df_entries_all = bundle["entries"]
df_misc_all = bundle["misc"]
df_meat_all = bundle["meat"]

sales_map = load_sales_map(store_cfg.get("sales_id", ""))
payroll_map = load_payroll_history_map(store_cfg.get("hist_id", ""))

existing_months = []
if not df_entries_all.empty:
    existing_months.extend(df_entries_all["정산월"].unique().tolist())
existing_months.extend(list(sales_map.keys()))

month_options = list_selectable_months(existing_months, today=kst_today())

with st.container(border=True):
    mc1, mc2, mc3, mc4 = st.columns([1.4, 1.5, 1.3, 0.9], vertical_alignment="bottom")
    with mc1:
        selected_ym = st.selectbox(
            "정산월 선택",
            options=month_options,
            index=0,
            format_func=lambda x: f"{ym_to_kor(x)} ({x})",
            key="settle_ym_sel",
        )
    with mc2:
        pay_offset = st.checkbox(
            "인건비 익월 탭(+1개월) 매칭",
            value=True,
            help="예: 11월 정산(말일 마감) ↔ 급여히스토리 12월 탭(11/5~12/4 근무 · 12/5 입금분)",
            key="settle_pay_offset",
        )
    with mc3:
        linked_pay_ym = next_ym(selected_ym) if pay_offset else selected_ym
        st.caption(
            f"📅 정산 사이클: **{selected_ym}** 말일결제 + 급여 **`{linked_pay_ym}`** 탭"
        )
    with mc4:
        if st.button("새로고침", use_container_width=True, key="settle_refresh"):
            st.cache_data.clear()
            st.rerun()


# =========================================================================
# 3. 선택 정산월 작업용 데이터 준비 (세션 버퍼 지원 -> 자동분류/전월복사 즉시 반영)
# =========================================================================
def _build_month_entries_df(ym: str) -> pd.DataFrame:
    """마스터 항목 기준으로 해당 정산월의 항목 테이블 구성 (저장분 우선, 미입력은 0원)."""
    saved = df_entries_all[df_entries_all["정산월"] == ym].copy() if not df_entries_all.empty else pd.DataFrame()
    saved_map = {}
    if not saved.empty:
        for _, r in saved.iterrows():
            saved_map[str(r["항목명"]).strip()] = r

    active_master = df_items_master[df_items_master["사용여부"].astype(str).str.upper() != "FALSE"].copy()
    active_master = active_master.sort_values(["정렬순서", "항목명"])

    rows = []
    used_names = set()
    for _, m in active_master.iterrows():
        nm = str(m["항목명"]).strip()
        used_names.add(nm)
        if nm in saved_map:
            sr = saved_map[nm]
            rows.append({
                "정산월": ym,
                "항목명": nm,
                "대분류": str(m["대분류"]),
                "결제방식": str(m["결제방식"]),
                "부분합계그룹": str(m["부분합계그룹"]),
                "납부일": str(m.get("납부일메모", "")),
                "금액": clean_int(sr["금액"]),
                "횟수": clean_int(sr["횟수"]),
                "결제완료": bool(sr["결제완료"]),
                "메모": str(sr["메모"]),
            })
        else:
            rows.append({
                "정산월": ym,
                "항목명": nm,
                "대분류": str(m["대분류"]),
                "결제방식": str(m["결제방식"]),
                "부분합계그룹": str(m["부분합계그룹"]),
                "납부일": str(m.get("납부일메모", "")),
                "금액": 0,
                "횟수": 0,
                "결제완료": False,
                "메모": "",
            })

    # 과거 데이터에 있지만 현재 마스터에 없는 항목도 보존
    for nm, sr in saved_map.items():
        if nm not in used_names:
            rows.append({
                "정산월": ym,
                "항목명": nm,
                "대분류": str(sr["대분류"]),
                "결제방식": str(sr["결제방식"]),
                "부분합계그룹": str(sr["부분합계그룹"]),
                "납부일": "",
                "금액": clean_int(sr["금액"]),
                "횟수": clean_int(sr["횟수"]),
                "결제완료": bool(sr["결제완료"]),
                "메모": str(sr["메모"]),
            })

    return pd.DataFrame(rows)


def _build_month_misc_df(ym: str) -> pd.DataFrame:
    if not df_misc_all.empty:
        sub = df_misc_all[df_misc_all["정산월"] == ym][["일자", "내용", "금액", "메모"]].copy()
        if not sub.empty:
            return sub.reset_index(drop=True)
    return pd.DataFrame(columns=["일자", "내용", "금액", "메모"])


def _build_month_meat_df(ym: str) -> pd.DataFrame:
    saved = df_meat_all[df_meat_all["정산월"] == ym].copy() if not df_meat_all.empty else pd.DataFrame()
    smap = {}
    if not saved.empty:
        for _, r in saved.iterrows():
            smap[str(r["부위명"]).strip()] = (clean_int(r["kg단가"]), clean_float(r["총량(kg)"]))

    rows = []
    for sp in MEAT_MENU_SPECS:
        part = sp["부위명"]
        if part == "돼지갈비" and part not in smap:
            continue
        p_val, kg_val = smap.get(part, (0, 0.0))
        rows.append({
            "부위명": part,
            "kg단가": p_val,
            "총량(kg)": kg_val,
            "1인분중량(g)": sp["중량g"],
            "판매가": sp["판매가"],
        })
    return pd.DataFrame(rows)


# 세션 상태 초기화 (매장 또는 정산월이 바뀌면 시트 데이터로 리로드)
state_sig = f"{selected_store}__{selected_ym}"
if st.session_state.get("settle_loaded_sig") != state_sig:
    st.session_state["settle_loaded_sig"] = state_sig
    st.session_state["settle_df_entries"] = _build_month_entries_df(selected_ym)
    st.session_state["settle_df_misc"] = _build_month_misc_df(selected_ym)
    st.session_state["settle_df_meat"] = _build_month_meat_df(selected_ym)
    st.session_state["settle_editor_ver"] = st.session_state.get("settle_editor_ver", 0) + 1

work_entries = st.session_state["settle_df_entries"]
work_misc = st.session_state["settle_df_misc"]
work_meat = st.session_state["settle_df_meat"]
ed_ver = st.session_state.get("settle_editor_ver", 0)

# 매출 · 인건비 계산
cur_sales = int(sales_map.get(selected_ym, 0))
pay_info = payroll_map.get(linked_pay_ym, {})
cur_labor = int(pay_info.get("총인건비", 0))
labor_confirmed = cur_labor > 0

fixed_sum = int(work_entries[work_entries["대분류"] == "공통"]["금액"].sum()) if not work_entries.empty else 0
mgmt_sum = int(work_entries[work_entries["대분류"] == "관리비"]["금액"].sum()) if not work_entries.empty else 0
var_sum = int(work_entries[work_entries["대분류"] == "변동매입"]["금액"].sum()) if not work_entries.empty else 0
misc_sum = int(work_misc["금액"].apply(clean_int).sum()) if not work_misc.empty else 0
total_exp = fixed_sum + mgmt_sum + var_sum + misc_sum

meat_sum = int(work_entries[work_entries["부분합계그룹"] == "고기"]["금액"].sum()) if not work_entries.empty else 0
food_sum = int(work_entries[work_entries["부분합계그룹"] == "식자재"]["금액"].sum()) if not work_entries.empty else 0
net_profit = cur_sales - total_exp - cur_labor if cur_sales > 0 else 0

cogs_pct = round((meat_sum + food_sum) / cur_sales * 100, 1) if cur_sales > 0 else 0.0
labor_pct = round(cur_labor / cur_sales * 100, 1) if (cur_sales > 0 and cur_labor > 0) else 0.0
op_pct = round(net_profit / cur_sales * 100, 1) if (cur_sales > 0 and cur_labor > 0) else 0.0

labor_val_html = f"{cur_labor:,}원" if labor_confirmed else "확정 대기"
labor_sub_html = (
    f"급여히스토리 [{linked_pay_ym}] · 매출 대비 {labor_pct:.1f}%"
    if labor_confirmed
    else f"[{linked_pay_ym}] 급여정산 확정 시 자동 반영"
)
profit_color = "#059669" if net_profit >= 0 else "#E11D48"

st.markdown(
    f"""
    <div class="kpi-grid">
        <div class="kpi-card" style="border-left:4px solid #2563EB;">
            <div class="kpi-label">{ym_to_kor(selected_ym)} 매출 (POS)</div>
            <div class="kpi-val">{cur_sales:,}원</div>
            <div class="kpi-sub">매출관리 시트 연동</div>
        </div>
        <div class="kpi-card" style="border-left:4px solid #D97706;">
            <div class="kpi-label">총 지출 (인건비 제외)</div>
            <div class="kpi-val">{total_exp:,}원</div>
            <div class="kpi-sub">고기 {meat_sum:,} · 식자재 {food_sum:,} (원가율 {cogs_pct:.1f}%)</div>
        </div>
        <div class="kpi-card" style="border-left:4px solid #4F46E5;">
            <div class="kpi-label">대응 인건비 ({linked_pay_ym} 입금분)</div>
            <div class="kpi-val">{labor_val_html}</div>
            <div class="kpi-sub">{labor_sub_html}</div>
        </div>
        <div class="kpi-card" style="border-left:4px solid {profit_color};">
            <div class="kpi-label">월 순이익 (매출-지출-인건비)</div>
            <div class="kpi-val" style="color:{profit_color};">{net_profit:,}원</div>
            <div class="kpi-sub">영업이익률 {op_pct:.1f}% (인건비 반영 기준)</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================================================================
# 4. 4개 기능 탭
# =========================================================================
tab_input, tab_import_tx, tab_dash, tab_config = st.tabs([
    "1. 월말정산 · 말일결제 체크",
    "2. 통장 · 카드 · 쇼핑 자동분류",
    "3. 종합 손익 · 원가변동 대시보드",
    "4. 거래처 규칙 · 과거 엑셀 이관",
])


# -------------------------------------------------------------------------
# TAB 1: 월말 정산 입력 & 말일 결제 체크
# -------------------------------------------------------------------------
with tab_input:
    # 상단 액션 바: POS 매출 입력 + 전월 고정비 복사
    with st.container(border=True):
        ac1, ac2, ac3, ac4 = st.columns([1.6, 1.0, 1.3, 1.3], vertical_alignment="bottom")
        with ac1:
            new_sales = st.number_input(
                f"{selected_ym} POS 월 매출 (원)",
                min_value=0,
                step=10000,
                value=int(cur_sales),
                key=f"pos_sales_in_{selected_ym}",
            )
            st.caption(f"입력 금액: **{int(new_sales):,}원**")
        with ac2:
            if st.button("매출 저장", use_container_width=True, key="btn_save_sales"):
                if store_cfg.get("sales_id"):
                    upsert_month_sales(store_cfg["sales_id"], selected_ym, int(new_sales))
                    st.cache_data.clear()
                    st.success(f"{selected_ym} 매출 {int(new_sales):,}원 저장 완료")
                    st.rerun()
                else:
                    st.warning("환경설정에서 매출관리 시트 ID가 등록되어 있지 않습니다.")
        with ac3:
            p_ym = prev_ym(selected_ym)
            if st.button(f"전월({p_ym}) 고정비 복사", use_container_width=True, key="btn_copy_prev_fixed"):
                prev_rows = df_entries_all[
                    (df_entries_all["정산월"] == p_ym) & (df_entries_all["대분류"] == "공통")
                ] if not df_entries_all.empty else pd.DataFrame()
                if prev_rows.empty:
                    # 전월 데이터가 없으면 마스터 기본금액 적용
                    m_defaults = dict(zip(df_items_master["항목명"], df_items_master["기본금액"]))
                    df_tmp = work_entries.copy()
                    for idx, r in df_tmp.iterrows():
                        if r["대분류"] == "공통" and clean_int(m_defaults.get(r["항목명"], 0)) > 0:
                            df_tmp.at[idx, "금액"] = clean_int(m_defaults[r["항목명"]])
                            df_tmp.at[idx, "횟수"] = 1
                    st.session_state["settle_df_entries"] = df_tmp
                    st.session_state["settle_editor_ver"] = ed_ver + 1
                    st.toast("전월 기록이 없어 기본 고정비 금액을 불러왔습니다.")
                    st.rerun()
                else:
                    pmap = dict(zip(prev_rows["항목명"], prev_rows["금액"]))
                    df_tmp = work_entries.copy()
                    for idx, r in df_tmp.iterrows():
                        if r["대분류"] == "공통" and r["항목명"] in pmap:
                            df_tmp.at[idx, "금액"] = clean_int(pmap[r["항목명"]])
                            df_tmp.at[idx, "횟수"] = 1
                    st.session_state["settle_df_entries"] = df_tmp
                    st.session_state["settle_editor_ver"] = ed_ver + 1
                    st.toast(f"{p_ym} 공통 고정비를 복사했습니다.")
                    st.rerun()
        with ac4:
            if st.button("시트 원본으로 되돌리기", use_container_width=True, key="btn_reset_month"):
                st.session_state["settle_loaded_sig"] = ""
                st.rerun()

    # 섹션 A: 말일 결제 거래처 (초록색 9곳)
    df_eom = work_entries[work_entries["결제방식"] == "말일결제"].copy().reset_index(drop=True)
    eom_total = int(df_eom["금액"].sum()) if not df_eom.empty else 0
    eom_done = int(df_eom[df_eom["결제완료"] == True]["금액"].sum()) if not df_eom.empty else 0
    eom_remain = eom_total - eom_done

    render_section_banner(
        "A. 말일 결제 거래처 (월말 후불 정산)",
        badge=f"총 {eom_total:,}원 · 미결제 {eom_remain:,}원",
        subtitle="거래명세서·월매입자료 확인 후 말일에 이체하는 거래처입니다. 송금 후 [결제완료]를 체크하세요.",
        accent="emerald",
    )
    st.markdown(
        f"""
        <div style="margin-bottom:6px;">
            <span class="eom-pill" style="background:#ECFDF5; color:#065F46; border:1px solid #A7F3D0;">말일 결제 합계: {eom_total:,}원</span>
            <span class="eom-pill" style="background:#EFF6FF; color:#1E40AF; border:1px solid #BFDBFE;">이체 완료: {eom_done:,}원</span>
            <span class="eom-pill" style="background:#FFF1F2; color:#9F1239; border:1px solid #FECDD3;">남은 이체액: {eom_remain:,}원</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    ed_eom = st.data_editor(
        df_eom[["항목명", "부분합계그룹", "금액", "결제완료", "메모"]],
        use_container_width=True,
        hide_index=True,
        disabled=["항목명", "부분합계그룹"],
        column_config={
            "항목명": st.column_config.TextColumn("거래처(항목)", width="medium"),
            "부분합계그룹": st.column_config.TextColumn("분류", width="small"),
            "금액": st.column_config.NumberColumn("말일 결제금액", format="%,d원", step=1000),
            "결제완료": st.column_config.CheckboxColumn("이체완료"),
            "메모": st.column_config.TextColumn("비고/미수메모"),
        },
        key=f"ed_eom_{selected_ym}_{ed_ver}",
    )

    # 섹션 B & C: 공통 고정비 + 관리비·세금
    col_fix, col_mgmt = st.columns(2)
    with col_fix:
        df_fix = work_entries[work_entries["대분류"] == "공통"].copy().reset_index(drop=True)
        render_section_banner(
            "B. 공통 고정비",
            badge=f"소계 {int(df_fix['금액'].sum()):,}원",
            subtitle="매월 동일하게 발생하는 고정 지출",
            accent="slate",
        )
        ed_fix = st.data_editor(
            df_fix[["항목명", "금액", "결제완료", "메모"]],
            use_container_width=True,
            hide_index=True,
            disabled=["항목명"],
            column_config={
                "금액": st.column_config.NumberColumn("금액", format="%,d원", step=1000),
                "결제완료": st.column_config.CheckboxColumn("완료"),
            },
            key=f"ed_fix_{selected_ym}_{ed_ver}",
        )

    with col_mgmt:
        df_mgmt = work_entries[work_entries["대분류"] == "관리비"].copy().reset_index(drop=True)
        render_section_banner(
            "C. 관리비 · 세금",
            badge=f"소계 {int(df_mgmt['금액'].sum()):,}원",
            subtitle="4대보험(10일) · 전기(5일) · 수도(말일) · 가스(26일) · 세금",
            accent="amber",
        )
        ed_mgmt = st.data_editor(
            df_mgmt[["항목명", "납부일", "금액", "결제완료", "메모"]],
            use_container_width=True,
            hide_index=True,
            disabled=["항목명", "납부일"],
            column_config={
                "납부일": st.column_config.TextColumn("납부일", width="small"),
                "금액": st.column_config.NumberColumn("금액", format="%,d원", step=1000),
                "결제완료": st.column_config.CheckboxColumn("완료"),
            },
            key=f"ed_mgmt_{selected_ym}_{ed_ver}",
        )

    # 섹션 D: 선결제 / 수시결제
    df_pre = work_entries[work_entries["결제방식"] == "선결제/수시"].copy().reset_index(drop=True)
    render_section_banner(
        "D. 선결제 · 수시결제 (네이버 · 쿠팡 · 마트 · 소모품 · 광고비)",
        badge=f"소계 {int(df_pre['금액'].sum()):,}원",
        subtitle="2번 탭 [통장·카드·쇼핑 자동분류]에서 엑셀을 올리면 금액과 결제 횟수가 자동 합산됩니다.",
        accent="blue",
    )
    ed_pre = st.data_editor(
        df_pre[["항목명", "부분합계그룹", "금액", "횟수", "메모"]],
        use_container_width=True,
        hide_index=True,
        disabled=["항목명", "부분합계그룹"],
        column_config={
            "항목명": st.column_config.TextColumn("항목명", width="medium"),
            "부분합계그룹": st.column_config.TextColumn("분류", width="small"),
            "금액": st.column_config.NumberColumn("합계금액", format="%,d원", step=1000),
            "횟수": st.column_config.NumberColumn("횟수", format="%d회", step=1, min_value=0),
        },
        key=f"ed_pre_{selected_ym}_{ed_ver}",
    )

    # 섹션 E & F: 기타지출 + 고기 단가/총량(kg)
    col_misc, col_meat = st.columns([1.15, 1.0])
    with col_misc:
        render_section_banner(
            "E. 기타지출 (비정기)",
            badge=f"소계 {misc_sum:,}원",
            subtitle="부가세, 수리비, 철물, 상여 등 비정기 지출 (행 추가/삭제 가능)",
            accent="rose",
        )
        ed_misc = st.data_editor(
            work_misc,
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "일자": st.column_config.TextColumn("일자 (예: 10.16)", width="small"),
                "내용": st.column_config.TextColumn("지출 내용", width="medium"),
                "금액": st.column_config.NumberColumn("금액", format="%,d원", step=1000),
                "메모": st.column_config.TextColumn("메모"),
            },
            key=f"ed_misc_{selected_ym}_{ed_ver}",
        )

    with col_meat:
        tot_kg = round(float(work_meat["총량(kg)"].apply(clean_float).sum()), 2) if not work_meat.empty else 0.0
        render_section_banner(
            "F. 고기 말일 단가 & 월 총량(kg)",
            badge=f"총량 {tot_kg:.2f} kg",
            subtitle="말일 기준 kg 단가 입력 시 1인분 원가율 자동 계산",
            accent="indigo",
        )
        ed_meat = st.data_editor(
            work_meat[["부위명", "kg단가", "총량(kg)"]],
            use_container_width=True,
            hide_index=True,
            disabled=["부위명"],
            column_config={
                "kg단가": st.column_config.NumberColumn("1kg 단가", format="%,d원", step=100),
                "총량(kg)": st.column_config.NumberColumn("월 총량", format="%.2f kg", step=0.5),
            },
            key=f"ed_meat_{selected_ym}_{ed_ver}",
        )

    # 편집 결과를 하나의 entries DataFrame으로 재조합하는 헬퍼
    def _collect_edited_entries() -> pd.DataFrame:
        merged = work_entries.copy()
        for sub_df, cols in [
            (ed_eom, ["금액", "결제완료", "메모"]),
            (ed_fix, ["금액", "결제완료", "메모"]),
            (ed_mgmt, ["금액", "결제완료", "메모"]),
            (ed_pre, ["금액", "횟수", "메모"]),
        ]:
            if sub_df is None or sub_df.empty:
                continue
            for _, r in sub_df.iterrows():
                mask = merged["항목명"] == r["항목명"]
                for c in cols:
                    merged.loc[mask, c] = r[c]
        return merged

    st.divider()
    sv1, sv2 = st.columns([1.4, 1.0])
    with sv1:
        if st.button(f"💾 [{selected_ym}] 월말정산 구글 시트 저장", type="primary", use_container_width=True, key="btn_save_all_month"):
            final_entries = _collect_edited_entries()
            final_misc = ed_misc.copy() if ed_misc is not None else pd.DataFrame(columns=["일자", "내용", "금액", "메모"])
            final_meat = ed_meat.copy() if ed_meat is not None else pd.DataFrame(columns=["부위명", "kg단가", "총량(kg)"])

            with st.spinner("구글 시트에 저장 중..."):
                save_month_settlement(
                    store_cfg["db_id"],
                    selected_ym,
                    final_entries[ENTRIES_HEADERS],
                    final_misc,
                    final_meat,
                )
                if store_cfg.get("sales_id") and int(new_sales) != cur_sales:
                    upsert_month_sales(store_cfg["sales_id"], selected_ym, int(new_sales))

            st.cache_data.clear()
            st.session_state["settle_loaded_sig"] = ""
            st.success(f"[{selected_store}] {ym_to_kor(selected_ym)} 월말정산 저장이 완료되었습니다!")
            st.rerun()

    with sv2:
        final_entries_dl = _collect_edited_entries()
        df_sum_dl = build_monthly_summary_df(
            df_entries_all, df_misc_all, df_meat_all, sales_map, payroll_map, payroll_offset_next_month=pay_offset
        )
        df_mt_dl = build_meat_cost_trend_df(df_meat_all)
        xlsx_bytes = build_settlement_excel(
            store_name=selected_store,
            ym=selected_ym,
            sales=int(new_sales),
            labor_cost=cur_labor,
            labor_tab_ym=linked_pay_ym,
            df_entries_m=final_entries_dl,
            df_misc_m=ed_misc if ed_misc is not None else pd.DataFrame(),
            df_meat_m=ed_meat if ed_meat is not None else pd.DataFrame(),
            df_summary_all=df_sum_dl,
            df_meat_trend=df_mt_dl,
        )
        st.download_button(
            label=f"📥 {selected_ym} 정산 엑셀(.xlsx) 다운로드",
            data=xlsx_bytes,
            file_name=f"월말정산_{selected_store}_{selected_ym}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


# -------------------------------------------------------------------------
# TAB 2: 통장 · 카드 · 네이버/쿠팡 거래내역 자동 분류기
# -------------------------------------------------------------------------
with tab_import_tx:
    render_section_banner(
        "통장 · 신용카드 · 네이버/쿠팡 거래내역 자동 분류기",
        badge="다중 파일 업로드",
        subtitle="은행/카드/쇼핑몰에서 내려받은 엑셀(.xlsx, .csv)을 올리면 키워드 규칙으로 자동 분류·합산·횟수 집계합니다.",
        accent="blue",
    )

    uploaded_files = st.file_uploader(
        "거래내역 파일 업로드 (은행 입출금, 신용카드, 네이버/쿠팡 내역 등 여러 개 동시 선택 가능)",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        key="tx_multi_uploader",
    )

    if uploaded_files:
        parsed_chunks = []
        for idx, uf in enumerate(uploaded_files):
            df_raw = read_uploaded_table(uf.name, uf.getvalue())
            if df_raw.empty:
                st.warning(f"⚠️ `{uf.name}` 파일을 읽지 못했습니다. (빈 파일이거나 지원되지 않는 형식)")
                continue

            guess = guess_tx_columns(df_raw)
            cols = list(df_raw.columns)
            with st.expander(f"📄 {uf.name} ({len(df_raw)}행) — 컬럼 매핑 확인", expanded=(idx == 0)):
                cc1, cc2, cc3 = st.columns([1.0, 1.4, 1.0])
                date_col = cc1.selectbox(
                    "일자 컬럼",
                    options=cols,
                    index=cols.index(guess["date_col"]) if guess["date_col"] in cols else 0,
                    key=f"tx_dcol_{idx}_{uf.name}",
                )
                desc_cols = cc2.multiselect(
                    "거래처/적요/상품명 컬럼 (복수 선택 가능)",
                    options=cols,
                    default=guess["desc_cols"],
                    key=f"tx_desccol_{idx}_{uf.name}",
                )
                amt_col = cc3.selectbox(
                    "출금/결제금액 컬럼",
                    options=cols,
                    index=cols.index(guess["amount_col"]) if guess["amount_col"] in cols else 0,
                    key=f"tx_acol_{idx}_{uf.name}",
                )
                if not desc_cols:
                    desc_cols = [cols[0]]

            df_cls = classify_transactions(
                df_raw,
                date_col=date_col,
                desc_cols=desc_cols,
                amount_col=amt_col,
                master_df=df_items_master,
                source_label=uf.name.rsplit(".", 1)[0][:18],
            )
            if not df_cls.empty:
                parsed_chunks.append(df_cls)

        if parsed_chunks:
            df_all_cls = pd.concat(parsed_chunks, ignore_index=True)
            item_choices = ["미분류(기타지출)", "제외"] + df_items_master["항목명"].astype(str).tolist()

            total_cnt = len(df_all_cls)
            auto_cnt = int((df_all_cls["분류항목"] != "미분류(기타지출)").sum())
            unmatched_cnt = total_cnt - auto_cnt

            st.info(
                f"✅ 총 **{total_cnt}건** 중 **{auto_cnt}건** 자동 분류 완료 · 미분류 **{unmatched_cnt}건** "
                "(아래 표에서 분류항목을 직접 바꾸거나 [포함] 체크를 해제할 수 있습니다.)"
            )

            only_unmatched = st.checkbox("미분류 항목만 먼저 보기", value=False, key="tx_only_unmatched")
            view_df = df_all_cls[df_all_cls["분류항목"] == "미분류(기타지출)"].copy() if only_unmatched else df_all_cls.copy()

            ed_tx = st.data_editor(
                view_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "포함": st.column_config.CheckboxColumn("포함", width="small"),
                    "출처": st.column_config.TextColumn("출처", disabled=True, width="small"),
                    "일자": st.column_config.TextColumn("일자", width="small"),
                    "거래내용": st.column_config.TextColumn("거래내용(적요/가맹점)", width="large"),
                    "금액": st.column_config.NumberColumn("금액", format="%,d원"),
                    "분류항목": st.column_config.SelectboxColumn("분류항목", options=item_choices, width="medium"),
                    "구분": st.column_config.TextColumn("구분", disabled=True, width="small"),
                },
                key="tx_classified_editor",
            )

            # 집계 미리보기 (미분류 필터가 꺼져 있을 때 전체 기준)
            target_tx = ed_tx[(ed_tx["포함"] == True) & (ed_tx["분류항목"] != "제외")].copy()
            if not target_tx.empty:
                matched_tx = target_tx[target_tx["분류항목"] != "미분류(기타지출)"]
                misc_tx = target_tx[target_tx["분류항목"] == "미분류(기타지출)"]

                if not matched_tx.empty:
                    agg_preview = (
                        matched_tx.groupby("분류항목", as_index=False)
                        .agg(금액=("금액", "sum"), 횟수=("금액", "count"))
                        .sort_values("금액", ascending=False)
                    )
                    st.markdown("##### 📊 항목별 자동 집계 미리보기")
                    st.dataframe(
                        agg_preview,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "금액": st.column_config.NumberColumn("합계", format="%,d원"),
                            "횟수": st.column_config.NumberColumn("횟수", format="%d회"),
                        },
                    )

                apply_mode = st.radio(
                    "정산표 반영 방식",
                    options=["기존 금액에 합산(+)", "분류된 항목 금액 덮어쓰기"],
                    horizontal=True,
                    key="tx_apply_mode",
                )
                if st.button(f"⚡ [{selected_ym}] 정산표(1번 탭)에 일괄 반영하기", type="primary", use_container_width=True):
                    new_entries = st.session_state["settle_df_entries"].copy()
                    if not matched_tx.empty:
                        agg_map = matched_tx.groupby("분류항목").agg(amt=("금액", "sum"), cnt=("금액", "count")).to_dict("index")
                        for nm, info in agg_map.items():
                            mask = new_entries["항목명"] == nm
                            if mask.any():
                                if apply_mode.startswith("기존"):
                                    new_entries.loc[mask, "금액"] = new_entries.loc[mask, "금액"].apply(clean_int) + int(info["amt"])
                                    new_entries.loc[mask, "횟수"] = new_entries.loc[mask, "횟수"].apply(clean_int) + int(info["cnt"])
                                else:
                                    new_entries.loc[mask, "금액"] = int(info["amt"])
                                    new_entries.loc[mask, "횟수"] = int(info["cnt"])

                    new_misc = st.session_state["settle_df_misc"].copy()
                    if not misc_tx.empty:
                        add_misc = pd.DataFrame([
                            {
                                "일자": str(r["일자"]),
                                "내용": str(r["거래내용"])[:40],
                                "금액": clean_int(r["금액"]),
                                "메모": f"자동분류({r['출처']})",
                            }
                            for _, r in misc_tx.iterrows()
                        ])
                        new_misc = pd.concat([new_misc, add_misc], ignore_index=True)

                    st.session_state["settle_df_entries"] = new_entries
                    st.session_state["settle_df_misc"] = new_misc
                    st.session_state["settle_editor_ver"] = st.session_state.get("settle_editor_ver", 0) + 1
                    st.success(
                        f"반영 완료! (분류 항목 {len(matched_tx)}건 + 기타지출 {len(misc_tx)}건) "
                        "1번 탭에서 확인 후 [구글 시트 저장]을 눌러 확정하세요."
                    )
                    st.rerun()
    else:
        st.caption("💡 팁: 자주 나오는 거래처가 미분류로 뜨면 **4번 탭 [거래처 규칙 관리]**에 키워드를 추가해 두세요. 다음 달부터는 자동으로 분류됩니다.")


# -------------------------------------------------------------------------
# TAB 3: 종합 손익 · 원가변동 대시보드
# -------------------------------------------------------------------------
with tab_dash:
    df_summary = build_monthly_summary_df(
        df_entries_all, df_misc_all, df_meat_all, sales_map, payroll_map, payroll_offset_next_month=pay_offset
    )
    df_meat_trend = build_meat_cost_trend_df(df_meat_all)

    render_section_banner(
        "월별 종합 손익 · 원가율 추이 (종합 시트 자동화)",
        badge=f"누적 {len(df_summary)}개월",
        subtitle="매출 · 총지출 · 인건비(익월 5일 입금분) · 순이익 및 전월 대비 증감을 자동 집계합니다.",
        accent="indigo",
    )

    if df_summary.empty:
        st.info("아직 저장된 월말정산 데이터가 없습니다. 4번 탭에서 기존 엑셀을 이관하거나 1번 탭에서 첫 정산을 저장해 보세요.")
    else:
        ch1, ch2 = st.columns(2)
        with ch1:
            st.markdown("##### 📈 매출 · 총지출 · 인건비 · 순이익 추이")
            chart_pl = df_summary.set_index("정산월")[["매출", "총지출(인건비제외)", "인건비", "순이익"]]
            st.line_chart(chart_pl, height=280)
        with ch2:
            st.markdown("##### 🥩 고기값 · 식자재 추이")
            chart_cogs = df_summary.set_index("정산월")[["고기값", "식자재"]]
            st.bar_chart(chart_cogs, height=280)

        st.markdown("##### 📋 월별 종합 손익표")
        disp_cols = [
            "정산월", "매출", "매출증감", "고기값", "고기값증감", "식자재", "식자재증감",
            "고기량(kg)", "총지출(인건비제외)", "인건비", "순이익",
            "고기+식자재율(%)", "인건비율(%)", "영업이익률(%)",
        ]
        st.dataframe(
            df_summary[disp_cols].sort_values("정산월", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "매출": st.column_config.NumberColumn("매출", format="%,d원"),
                "매출증감": st.column_config.NumberColumn("매출증감", format="%+,d원"),
                "고기값": st.column_config.NumberColumn("고기값", format="%,d원"),
                "고기값증감": st.column_config.NumberColumn("고기값증감", format="%+,d원"),
                "식자재": st.column_config.NumberColumn("식자재", format="%,d원"),
                "식자재증감": st.column_config.NumberColumn("식자재증감", format="%+,d원"),
                "고기량(kg)": st.column_config.NumberColumn("고기량", format="%.2f kg"),
                "총지출(인건비제외)": st.column_config.NumberColumn("총지출(인건비제외)", format="%,d원"),
                "인건비": st.column_config.NumberColumn("인건비", format="%,d원"),
                "순이익": st.column_config.NumberColumn("순이익", format="%,d원"),
                "고기+식자재율(%)": st.column_config.NumberColumn("고기+식자재율", format="%.1f%%"),
                "인건비율(%)": st.column_config.NumberColumn("인건비율", format="%.1f%%"),
                "영업이익률(%)": st.column_config.NumberColumn("영업이익률", format="%.1f%%"),
            },
        )

    render_section_banner(
        "고기 부위별 원가변동 추이 (원가변동 시트 자동화)",
        badge="1인분 기준 원가율(%)",
        subtitle="삼겹·목살·갈매기·가브리·꼬들·늑간(180g), 항정(160g) 판매가 대비 월별 원가율",
        accent="emerald",
    )
    if df_meat_trend.empty:
        st.info("저장된 고기 단가 데이터가 없습니다.")
    else:
        ratio_cols = [c for c in df_meat_trend.columns if c.endswith("_원가율(%)")]
        if ratio_cols:
            chart_mt = df_meat_trend.set_index("정산월")[ratio_cols].rename(
                columns=lambda c: c.replace("_원가율(%)", "")
            )
            st.line_chart(chart_mt, height=260)
        mt_col_cfg = {}
        for c in df_meat_trend.columns:
            if c.endswith("_단가") or c.endswith("_원가"):
                mt_col_cfg[c] = st.column_config.NumberColumn(c, format="%,d원")
            elif c.endswith("_원가율(%)"):
                mt_col_cfg[c] = st.column_config.NumberColumn(c.replace("(%)", ""), format="%.1f%%")
        st.dataframe(
            df_meat_trend.sort_values("정산월", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config=mt_col_cfg,
        )


# -------------------------------------------------------------------------
# TAB 4: 거래처 규칙 관리 & 과거 엑셀 일괄 이관
# -------------------------------------------------------------------------
with tab_config:
    render_section_banner(
        "1. 기존 정산 엑셀(★월말정산내역_분당그릴★.xlsx) 원클릭 이관",
        badge="초기 세팅용",
        subtitle="기존 엑셀의 월별 시트(25.10~26.10 등)를 자동 파싱하여 구글 시트와 매출관리에 한 번에 저장합니다.",
        accent="amber",
    )
    legacy_file = st.file_uploader(
        "기존 월말정산 엑셀 파일 선택 (.xlsx)",
        type=["xlsx"],
        key="legacy_xlsx_uploader",
    )
    if legacy_file is not None:
        df_le, df_lm, df_lk, l_sales, l_logs = parse_legacy_settlement_excel(
            legacy_file.getvalue(), master_df=df_items_master
        )
        st.success(
            f"파싱 완료: **{len(l_logs)}개월** 시트 감지 · 내역 {len(df_le)}건 · 기타지출 {len(df_lm)}건 · 고기단가 {len(df_lk)}건"
        )
        with st.expander("파싱된 월별 요약 보기", expanded=False):
            for lg in l_logs:
                st.write(f"- {lg}")
        overwrite_opt = st.checkbox("이미 저장된 동일 월 데이터가 있으면 덮어쓰기", value=True, key="legacy_overwrite")
        if st.button("🚀 파싱된 과거 데이터를 구글 시트로 일괄 이관", type="primary", use_container_width=True):
            with st.spinner("구글 시트에 과거 정산 데이터를 저장하는 중..."):
                save_bulk_imported_settlement(
                    db_id=store_cfg["db_id"],
                    df_entries_all=df_le,
                    df_misc_all=df_lm,
                    df_meat_all=df_lk,
                    sales_id=store_cfg.get("sales_id", ""),
                    sales_dict=l_sales,
                    overwrite_existing=overwrite_opt,
                )
            st.cache_data.clear()
            st.session_state["settle_loaded_sig"] = ""
            st.success(f"{len(l_logs)}개월 과거 데이터 이관이 완료되었습니다!")
            st.rerun()

    st.divider()
    render_section_banner(
        "2. 거래처 · 항목 마스터 및 자동분류 키워드 규칙",
        badge=f"총 {len(df_items_master)}개 항목",
        subtitle="키워드는 쉼표(,)로 여러 개 입력할 수 있습니다. (예: 아성다,다이소)",
        accent="slate",
    )
    ed_master = st.data_editor(
        df_items_master,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "대분류": st.column_config.SelectboxColumn("대분류", options=["공통", "관리비", "변동매입"]),
            "결제방식": st.column_config.SelectboxColumn("결제방식", options=["자동이체", "고지납부", "말일결제", "선결제/수시"]),
            "부분합계그룹": st.column_config.SelectboxColumn("부분합계그룹", options=["고정비", "관리비", "고기", "식자재", "주류음료", "기타매입"]),
            "기본금액": st.column_config.NumberColumn("기본금액", format="%,d원", step=1000),
            "정렬순서": st.column_config.NumberColumn("정렬순서", format="%d", step=10),
            "사용여부": st.column_config.SelectboxColumn("사용여부", options=["TRUE", "FALSE"]),
        },
        key="ed_master_items",
    )
    if st.button("💾 거래처 마스터 · 키워드 규칙 저장", type="primary", use_container_width=True):
        with st.spinner("항목 마스터를 저장하는 중..."):
            save_settlement_items_master(store_cfg["db_id"], ed_master)
        st.cache_data.clear()
        st.session_state["settle_loaded_sig"] = ""
        st.success("거래처 마스터 및 자동분류 키워드가 저장되었습니다.")
        st.rerun()
