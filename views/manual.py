"""
================================================================================
[파일명] views/manual.py
[역할] 아이폰(모바일) 및 매장 PC/태블릿 겸용 '매니저 실무 교육 매뉴얼' 전용 탭
[주요 기능]
1. 다매장 선택 및 지점별 환경설정(manager_pin, 정산 기준일, 입금알림 설정) 실시간 연동
2. 매니저 전용 비밀번호(PIN) 잠금 해제 (일반 직원 열람 차단, 직원관리/급여정산 로그인 연동)
3. 모바일·태블릿·PC 반응형 카드형 레이아웃 및 핵심 요약 체크리스트 제공
4. 5개 실무 탭(출퇴근·입금확인 | 주간스케줄 | 신규채용·계약서 | 퇴사·보건증·시급 | 급여정산·경영분석)
================================================================================
"""

import os
import streamlit as st
from store_registry import load_all_stores, load_store_settings
from ui_styles import apply_base_theme

STORES = load_all_stores()

apply_base_theme(max_width=960)
st.markdown(
    """<style>
.manual-header {
    background: linear-gradient(135deg, #1E293B 0%, #334155 100%);
    color: #FFFFFF;
    padding: 18px 20px;
    border-radius: 14px;
    margin-bottom: 14px;
}
.manual-header h2 {
    color: #FFFFFF !important;
    font-size: 1.3rem;
    font-weight: 800;
    margin: 0 0 6px 0;
}
.manual-header p {
    color: #E2E8F0;
    font-size: 0.9rem;
    margin: 0;
    line-height: 1.55;
}
.manual-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
}
.manual-chip {
    background: rgba(255, 255, 255, 0.14);
    border: 1px solid rgba(255, 255, 255, 0.22);
    color: #F8FAFC;
    font-size: 0.8rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 999px;
}
.rule-card {
    background-color: #FFFBEB;
    border: 1.5px solid #F59E0B;
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 16px;
}
.rule-title {
    font-size: 1.02rem;
    font-weight: 800;
    color: #B45309;
    margin-bottom: 8px;
}
.rule-list {
    margin: 0;
    padding-left: 1.15rem;
    font-size: 0.92rem;
    color: #78350F;
    line-height: 1.7;
}
.rule-list li {
    margin-bottom: 4px;
}
.step-card {
    background-color: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-left: 5px solid #1E293B;
    border-radius: 10px;
    padding: 15px 16px;
    margin-bottom: 13px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}
.step-card-blue {
    background-color: #F8FAFF;
    border: 1px solid #BFDBFE;
    border-left: 5px solid #2563EB;
    border-radius: 10px;
    padding: 15px 16px;
    margin-bottom: 13px;
}
.step-card-emerald {
    background-color: #F6FEF9;
    border: 1px solid #A7F3D0;
    border-left: 5px solid #059669;
    border-radius: 10px;
    padding: 15px 16px;
    margin-bottom: 13px;
}
.step-card-amber {
    background-color: #FFFDF7;
    border: 1px solid #FDE68A;
    border-left: 5px solid #D97706;
    border-radius: 10px;
    padding: 15px 16px;
    margin-bottom: 13px;
}
.step-badge {
    display: inline-block;
    background-color: #1E293B;
    color: #FFFFFF;
    font-size: 0.76rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 6px;
    margin-bottom: 6px;
}
.step-badge-blue {
    display: inline-block;
    background-color: #2563EB;
    color: #FFFFFF;
    font-size: 0.76rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 6px;
    margin-bottom: 6px;
}
.step-badge-emerald {
    display: inline-block;
    background-color: #059669;
    color: #FFFFFF;
    font-size: 0.76rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 6px;
    margin-bottom: 6px;
}
.step-badge-amber {
    display: inline-block;
    background-color: #D97706;
    color: #FFFFFF;
    font-size: 0.76rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 6px;
    margin-bottom: 6px;
}
.step-heading {
    font-size: 1.04rem;
    font-weight: 800;
    color: #0F172A;
    margin-bottom: 8px;
}
.step-body {
    font-size: 0.93rem;
    color: #334155;
    line-height: 1.68;
}
.step-body ul, .step-body ol {
    margin: 4px 0 0 0;
    padding-left: 1.2rem;
}
.step-body li {
    margin-bottom: 5px;
}
.ui-mock {
    background-color: #F8FAFC;
    border: 1px dashed #94A3B8;
    border-radius: 8px;
    padding: 10px 13px;
    margin-top: 10px;
    font-size: 0.86rem;
    color: #1E293B;
    line-height: 1.55;
}
.note-tip {
    background-color: #FFFBEB;
    border-left: 3px solid #D97706;
    padding: 8px 11px;
    border-radius: 6px;
    margin-top: 9px;
    font-size: 0.86rem;
    color: #92400E;
    line-height: 1.55;
}
.note-warn {
    background-color: #FEF2F2;
    border-left: 3px solid #DC2626;
    padding: 8px 11px;
    border-radius: 6px;
    margin-top: 9px;
    font-size: 0.86rem;
    color: #991B1B;
    line-height: 1.55;
}
.stButton > button, .stFormSubmitButton > button {
    border-radius: 8px;
    font-weight: 600;
    min-height: 2.55rem;
}
</style>""",
    unsafe_allow_html=True,
)


def render_step_card(
    badge: str,
    heading: str,
    body_html: str,
    tone: str = "slate",
    footer_html: str = "",
):
    """들여쓰기 코드블록 오작동 없이 안전하게 카드 HTML을 렌더링합니다."""
    card_cls = {
        "slate": "step-card",
        "blue": "step-card-blue",
        "emerald": "step-card-emerald",
        "amber": "step-card-amber",
    }.get(tone, "step-card")
    badge_cls = {
        "slate": "step-badge",
        "blue": "step-badge-blue",
        "emerald": "step-badge-emerald",
        "amber": "step-badge-amber",
    }.get(tone, "step-badge")
    html = (
        f'<div class="{card_cls}">'
        f'<span class="{badge_cls}">{badge}</span>'
        f'<div class="step-heading">{heading}</div>'
        f'<div class="step-body">{body_html}</div>'
        f"{footer_html}"
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def show_guide_image(file_candidates: list, caption: str):
    """폴더에 스크린샷/가이드 이미지 파일이 있으면 출력합니다."""
    for fp in file_candidates:
        resolved = fp if os.path.isabs(fp) else os.path.join(BASE_DIR, fp)
        if os.path.exists(resolved):
            st.image(resolved, caption=caption, use_container_width=True)
            return True
        if os.path.exists(fp):
            st.image(fp, caption=caption, use_container_width=True)
            return True
    return False


# ==============================================================================
# 매장 선택 및 지점별 환경설정 실시간 로드
# ==============================================================================
h_left, h_right = st.columns([2.6, 1.1], vertical_alignment="center")
with h_left:
    st.markdown('<div class="app-title">▪&nbsp;&nbsp;매니저매뉴얼</div>', unsafe_allow_html=True)
with h_right:
    selected_store = st.selectbox(
        "매장 선택",
        list(STORES.keys()),
        index=0,
        label_visibility="collapsed",
        key="manual_store_sel",
    )

store_cfg = STORES[selected_store]
app_cfg = load_store_settings(store_cfg["db_id"], selected_store)
active_mgr_pin = str(app_cfg.get("manager_pin") or store_cfg.get("manager_pin") or "0524").strip()
store_title = str(app_cfg.get("store_title") or selected_store).strip()
payroll_start_day = int(str(app_cfg.get("payroll_start_day") or "5").strip() or "5")
att_time_step = str(app_cfg.get("att_time_step_min") or "10").strip()
pay_wd_hours = str(app_cfg.get("payment_weekday_hours") or "16:00-22:00").strip()
pay_we_hours = str(app_cfg.get("payment_weekend_hours") or "12:00-22:00").strip()
pay_we_break = str(app_cfg.get("payment_weekend_break") or "15:00-17:00").strip()

# ==============================================================================
# 매니저 전용 비밀번호(PIN) 잠금 확인
# ==============================================================================
unlocked_stores = st.session_state.setdefault("manual_unlocked_stores", set())
is_unlocked = (
    st.session_state.get("authenticated", False)
    or st.session_state.get("staff_mgr_unlocked", False)
    or (selected_store in unlocked_stores)
)

if not is_unlocked:
    st.write("")
    _, c_mid, _ = st.columns([1.0, 1.4, 1.0])
    with c_mid:
        with st.container(border=True):
            st.markdown(f"#### [{store_title}] 매니저 전용")
            st.caption("업무 매뉴얼 열람을 위해 해당 지점의 매니저 비밀번호를 입력하세요.")
            with st.form(key=f"manual_pin_form_{selected_store}", border=False):
                pin = st.text_input(
                    "비밀번호",
                    type="password",
                    placeholder="비밀번호 입력",
                    label_visibility="collapsed",
                    key=f"manual_pin_input_{selected_store}",
                )
                submitted_pin = st.form_submit_button("확인", type="primary", use_container_width=True)

            if submitted_pin:
                if pin == active_mgr_pin:
                    unlocked_stores.add(selected_store)
                    st.session_state["staff_mgr_unlocked"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()


# ------------------------------------------------------------------------------
# 상단 잠금 버튼
# ------------------------------------------------------------------------------
_, top_c2 = st.columns([4.2, 1.0], vertical_alignment="center")
with top_c2:
    if st.button("매뉴얼 잠금", use_container_width=True):
        unlocked_stores.clear()
        st.session_state["staff_mgr_unlocked"] = False
        st.session_state["authenticated"] = False
        st.rerun()

st.markdown(
    (
        '<div class="manual-header">'
        f"<h2>[{store_title}] 매니저 업무 매뉴얼</h2>"
        "<p>아이폰·태블릿·매장 PC 어디서든 아래 탭을 눌러 실무 순서를 확인하세요.<br>"
        "좌측 메뉴 순서: <b>출퇴근기록부 → 주간스케줄 → 직원관리 → 급여정산 → 매니저매뉴얼 → 환경설정</b></p>"
        '<div class="manual-meta">'
        f'<span class="manual-chip">매니저 PIN: {active_mgr_pin}</span>'
        f'<span class="manual-chip">급여 정산 기준일: 매월 {payroll_start_day}일</span>'
        f'<span class="manual-chip">출퇴근 입력 단위: {att_time_step}분</span>'
        f'<span class="manual-chip">입금알림 영업시간: 평일 {pay_wd_hours} / 주말 {pay_we_hours}</span>'
        "</div>"
        "</div>"
    ),
    unsafe_allow_html=True,
)

st.markdown(
    (
        '<div class="rule-card">'
        '<div class="rule-title">매니저 핵심 체크리스트 5줄 요약</div>'
        '<ol class="rule-list">'
        '<li><b>[영업 중 · 계좌이체/chak 확인]</b> <code>출퇴근기록부</code> 상단 <b>입금·chak</b> 버튼(초록색 점등 시 미확인 건 있음)을 눌러 입금자명·금액을 확인한 뒤 <b>[미확인 N건 확인완료]</b> 처리합니다.</li>'
        f'<li><b>[매일 마감/오픈 · 근태 승인]</b> <code>출퇴근기록부</code> 상단 <b>매니저 승인 대기</b> 버튼(주황색 점등)에서 비밀번호(<code>{active_mgr_pin}</code>) 입력 후 <b>미확인 승인</b> 탭에서 파트타임 출퇴근을 일괄 승인합니다.</li>'
        '<li><b>[정규직 특근/휴무 즉시 등록]</b> 같은 팝업의 <b>정규직 특근/휴무</b> 탭에서 추가출근·기타휴무·대체휴무를 <b>발생 당일 바로 등록</b>합니다. (설정된 수신 대상에 텔레그램 자동 발송)</li>'
        '<li><b>[매주 · 주간스케줄 확정]</b> <code>주간스케줄</code>에서 직원 신청 링크를 단톡방에 공유 → <b>[고정 + 직원요청 자동 병합]</b> → 확정 저장 후 카톡 텍스트·시간표 이미지(PNG) 또는 텔레그램으로 공유합니다.</li>'
        '<li><b>[입사·시급변경·퇴사]</b> <code>직원관리</code>에서 명부 저장(신규 파트타임·시급 변경 시 텔레그램 자동 알림) 후 전자근로계약서 링크를 발급합니다. 퇴사 시에는 <b>행을 절대 지우지 말고 <code>상태</code>만 <code>퇴사</code>로 변경</b>합니다.</li>'
        "</ol>"
        "</div>"
    ),
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------------------
# 모바일 터치 친화형 5개 업무 탭 구성 (좌측 메뉴 순서와 동일)
# ------------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. 출퇴근 · 입금확인",
    "2. 주간스케줄",
    "3. 신규채용 · 계약서",
    "4. 퇴사 · 보건증 · 시급",
    "5. 급여정산 · 경영분석",
])

# ==============================================================================
# [탭 1] 출퇴근기록부 · 실시간 입금/chak 확인 · 매니저 승인 · 정규직 특근/휴무
# ==============================================================================
with tab1:
    show_guide_image(
        ["assets/manual_att.png"],
        "▲ [출퇴근기록부 메인 화면] ① 상단 3대 알림 팝업 · ② 당일 확정 스케줄 · ③ 체크박스 선택 수정 · ④ 저장/반영",
    )

    render_step_card(
        badge="STEP 1 · 상단 3대 알림 팝업 버튼",
        heading="출퇴근기록부 상단 버튼 색상으로 매장 현황 한눈에 보기",
        tone="blue",
        body_html=(
            "<code>출퇴근기록부</code> 상단에는 직원들이 보는 기본 화면을 깔끔하게 유지하면서, "
            "확인이 필요한 업무만 바로 열어볼 수 있는 <b>3개의 팝업 버튼</b>이 배치되어 있습니다."
            "<ul>"
            "<li><b>입금·chak 버튼 (초록색 점등):</b> 확인하지 않은 계좌이체·지역상품권(<code>chak</code>) 결제가 있을 때 초록색으로 강조됩니다.</li>"
            "<li><b>보건증 알림 버튼 (빨간색 점등):</b> 만료 30일 이내(D-30) 또는 만료된 직원이 있을 때 빨간색으로 강조됩니다.</li>"
            "<li><b>매니저 승인 버튼 (주황색 점등):</b> 매니저 승인이 필요한 파트타임 출퇴근 기록이 쌓여 있을 때 주황색으로 강조됩니다.</li>"
            "</ul>"
        ),
        footer_html=(
            '<div class="ui-mock">'
            "상단 알림이 모두 0건일 때는 차분한 회색 버튼으로 표시되며, 언제든 눌러서 상세 팝업을 열 수 있습니다."
            "</div>"
        ),
    )

    render_step_card(
        badge="STEP 2 · 실시간 입금·결제 확인 (카운터 직원 공용)",
        heading="우리은행 계좌이체 · 성남사랑상품권(chak) 실시간 확인",
        tone="emerald",
        body_html=(
            "손님이 계좌이체나 성남사랑상품권(<code>chak</code>)으로 결제하면 대표님 스마트폰 알림이 자동으로 매장 시스템과 텔레그램으로 전달됩니다."
            "<ol>"
            "<li>상단 <b>[● 입금·chak 미확인 N건]</b> 버튼을 눌러 팝업을 엽니다.</li>"
            "<li>입금 시각, 구분(<code>계좌입금</code> / <code>chak</code>), 입금자명(또는 가맹점 결제 내역), 금액을 확인합니다.</li>"
            "<li>새 입금이 방금 들어왔다면 <b>[입금 새로고침]</b>을 눌러 최신 내역을 불러옵니다.</li>"
            "<li>테이블 결제가 확인되면 <b>[미확인 N건 확인완료]</b> 버튼을 눌러 대기 상태를 완료로 처리합니다.</li>"
            "</ol>"
        ),
        footer_html=(
            '<div class="note-tip">'
            f"<b>보안 및 운영 기준:</b> 영업시간(평일 <code>{pay_wd_hours}</code>, 주말 <code>{pay_we_hours}</code> / 브레이크 <code>{pay_we_break}</code> 제외) 내 입금·결제 건만 수집되며, "
            "<b>통장 잔액·출금 내역·계좌번호·chak 금일 누적 결제금액</b> 및 지정된 제외 입금자(대표 본인 등)는 자동으로 필터링되어 화면에 노출되지 않습니다."
            "</div>"
        ),
    )

    render_step_card(
        badge="STEP 3 · 파트타임 직원 안내",
        heading="출퇴근 시간 입력 · 수정 지도 및 확정 스케줄 확인",
        tone="slate",
        body_html=(
            "<ul>"
            "<li><b>오늘 확정 스케줄 표시:</b> 날짜를 선택하면 <code>주간스케줄</code>에서 확정한 해당 날짜의 파트타임 출근 예정자와 시작 시간이 상단 배지로 자동 표시됩니다.</li>"
            "<li><b>신규 출퇴근 입력:</b> 하단 <code>2. 출퇴근 시간 입력/수정</code>에서 직원이 <b>본인 이름</b>을 먼저 선택해야 시간 입력칸이 열립니다. "
            f"시간({att_time_step}분 단위)을 맞추고 <b>[출퇴근 시간 저장하기]</b>를 누르면 시트에 즉시 저장되고 다음 직원을 위해 화면이 초기화됩니다.</li>"
            "<li><b>잘못 입력했을 때(수정):</b> 새로 중복 입력하지 말고, <code>1. 일 근무현황</code> 표에서 <b>본인 줄 왼쪽 체크박스</b>를 클릭하면 하단이 수정 모드로 바뀝니다. 수정 사유를 적고 <b>[수정 내역 반영하기]</b>를 누르면 됩니다.</li>"
            "<li><b>개인 누적 확인:</b> 우측 하단 <code>3. 개인별 월별 근무시간 조회</code>에서 직원 본인 또는 선택 직원의 정산월 누적 근무시간을 바로 확인할 수 있습니다.</li>"
            "</ul>"
        ),
    )

    render_step_card(
        badge="STEP 4 · 매니저 필수 업무",
        heading="파트타임 일일 근태 일괄 승인 및 승인 해제",
        tone="slate",
        body_html=(
            "<ul>"
            "<li><b>중요:</b> 매니저가 승인(<code>확인완료</code>)하지 않은 파트타임 기록은 <b>확정 급여 계산에서 제외</b>됩니다. (급여정산 상단의 실시간 합계 참고 카드에는 미승인분까지 합산 표시됨)</li>"
            "<li><b>일괄 승인 순서:</b>"
            f"<ol><li>상단 <b>[● 매니저 승인 대기 N건]</b> 버튼 클릭 → 비밀번호(<code>{active_mgr_pin}</code>) 입력 후 <b>[확인]</b></li>"
            "<li>팝업 내 <b><code>미확인 승인</code></b> 탭에서 출퇴근 시간 검토 후 전체 선택 또는 개별 체크박스 선택</li>"
            "<li><b>[선택한 내역 일괄 확인 완료]</b> 클릭 시 한 번에 승인 완료</li></ol></li>"
            "<li><b>승인 해제:</b> 확인 완료된 건은 직원이 임의로 고칠 수 없도록 잠깁니다. 수정이 필요하면 팝업의 <b><code>승인 해제</code></b> 탭에서 해당 건을 체크해 잠금을 풀어주세요.</li>"
            "</ul>"
        ),
    )

    render_step_card(
        badge="STEP 5 · 정규직 특근/휴무 즉시 기록 (누락 방지)",
        heading="정규직 추가출근 · 기타휴무 · 대체휴무 등록 및 수정/삭제",
        tone="amber",
        body_html=(
            "<ul>"
            "<li><b>기록 원칙:</b> 정규직 직원의 비정기 추가출근이나 급여 차감 휴무는 월말까지 기억해 두지 말고 <b>발생 당일 바로 등록</b>해 주세요.</li>"
            "<li><b>등록 순서:</b>"
            f"<ol><li>상단 <b>매니저 전용 확인</b> 팝업 잠금 해제(<code>{active_mgr_pin}</code>) → 세 번째 <b><code>정규직 특근/휴무</code></b> 탭 선택</li>"
            "<li>발생 날짜와 정규직 이름 선택</li>"
            "<li>변동 구분 선택: <code>추가출근</code> / <code>기타휴무</code> / <code>대체휴무</code></li>"
            "<li>단위(<code>1일</code> 또는 <code>시간단위</code>)와 사유 메모 작성 후 저장 → 구글 시트(<code>정규직근태변동</code>) 자동 누적 및 <b>텔레그램 즉시 알림</b> 발송</li></ol></li>"
            "<li><b>수정/삭제:</b> 탭 하단 이번 정산월 내역 표 아래의 <b><code>등록 내역 수정 / 삭제</code></b>에서 잘못 입력한 내역을 수정하거나 삭제할 수 있습니다. (수정·삭제 시에도 텔레그램 알림 발송)</li>"
            "</ul>"
        ),
        footer_html=(
            '<div class="ui-mock">'
            f"화면 위치: <b>출퇴근기록부</b> → 상단 <b>[매니저 확인]</b> 팝업 → <code>{active_mgr_pin}</code> 입력 → <b>[정규직 특근/휴무]</b> 탭"
            "</div>"
        ),
    )

    show_guide_image(
        ["assets/manual_popups.png"],
        "▲ [핵심 팝업 2종] ①·② 실시간 계좌입금·chak 확인 및 완료 처리 / ③·④ 매니저 PIN 해제 후 일괄 승인·정규직 특근/휴무",
    )

# ==============================================================================
# [탭 2] 주간스케줄 운영 (고정/유동 템플릿 · 직원 신청 · 확정 · 카톡/PNG 공유)
# ==============================================================================
with tab2:
    show_guide_image(
        ["assets/manual_schedule.png"],
        "▲ [주간스케줄 화면] ① 직원 신청 링크 공유 · ② 고정+요청 자동 병합 · ③ 확정 저장(출퇴근 연동) · ④ 카톡/PNG/텔레그램 공유",
    )

    render_step_card(
        badge="STEP 1 · 최초 1회 / 변경 시 설정",
        heading="고정 · 유동 파트타임 스케줄 템플릿 등록",
        tone="blue",
        body_html=(
            "좌측 메뉴 <code>주간스케줄</code>의 두 번째 탭 <b><code>2. 고정 · 유동 템플릿 설정</code></b>에서 재직 중인 파트타임 직원의 기본 근무 패턴을 설정합니다."
            "<ul>"
            "<li><b>고정 직원:</b> 매주 정해진 요일과 출근시간에 나오는 직원은 구분을 <code>고정</code>으로 두고 월~일 기본 출근시간을 입력합니다.</li>"
            "<li><b>유동 직원:</b> 매주 가능한 날을 신청받는 직원은 구분을 <code>유동</code>으로 두고 요일 칸은 비워둡니다.</li>"
            "<li>설정을 마친 뒤 하단 <b>[고정 · 유동 스케줄 템플릿 저장하기]</b>를 누르면 다음 주부터 자동으로 불러와집니다.</li>"
            "</ul>"
        ),
    )

    render_step_card(
        badge="STEP 2 · 직원 자가 신청 링크 배포",
        heading="직원용 스케줄 신청 링크 단톡방 공유",
        tone="emerald",
        body_html=(
            "첫 번째 탭 <b><code>1. 주간스케줄 작성 · 공유</code></b> 상단에서 <b>직원 신청용 전용 링크</b>(<code>?schedule=매장명</code>)를 복사해 파트타임 단톡방에 공유합니다."
            "<ul>"
            "<li>직원은 로그인 없이 스마트폰에서 링크를 열어 <b>본인 이름</b>과 <b>대상 주차</b>를 고른 뒤 <b>출근시간만 선택</b>해 제출합니다.</li>"
            "<li><b>고정 직원 편의 기능:</b> 고정 직원이 이름을 고르면 본인 고정 출근시간이 자동으로 채워지므로, <b>빠지는 날만 <code>휴무요청</code>으로 변경</b>해서 제출하면 됩니다.</li>"
            "<li>직원이 제출한 내역은 <code>1. 주간스케줄 작성 · 공유</code> 화면의 <b>직원 신청 현황</b> 표에 실시간으로 집계됩니다.</li>"
            "</ul>"
        ),
    )

    render_step_card(
        badge="STEP 3 · 시간표 병합 · 확정 · 단톡방 공유",
        heading="주간 시간표 확정 및 출퇴근기록부 자동 연동",
        tone="slate",
        body_html=(
            "<ol>"
            "<li><code>1. 주간스케줄 작성 · 공유</code>에서 작성할 주차를 선택하고 <b>[고정 + 직원요청 자동 병합]</b> 버튼을 누릅니다. (고정 인원 + 유동 직원 신청 + 고정 직원 휴무요청이 한 번에 표에 반영됩니다.)</li>"
            "<li>표 위의 <b>요일별 인원수 막대</b>를 보며 인원이 부족하거나 많은 요일의 출근시간을 직접 수정·조율합니다.</li>"
            "<li>조율이 끝나면 <b>[주간 스케줄 확정 저장하기 (출퇴근기록부 자동 연동)]</b>을 누릅니다. 확정된 시간표는 매일 <b><code>출퇴근기록부</code> 상단 당일 출근 예정자</b>에 자동으로 표시됩니다.</li>"
            "<li>하단 공유 영역에서 <b>① 카카오톡 공지 텍스트 복사</b>, <b>② 한글 시간표 이미지(.png) 다운로드</b>, <b>③ [텔레그램으로 확정 스케줄 발송]</b> 중 원하는 방식으로 즉시 공유할 수 있습니다.</li>"
            "</ol>"
        ),
        footer_html=(
            '<div class="ui-mock">'
            "지난주나 이전 주차 확정 내역은 세 번째 탭 <b>3. 확정 스케줄 이력</b>에서 언제든 다시 조회할 수 있습니다."
            "</div>"
        ),
    )

# ==============================================================================
# [탭 3] 신규 채용 및 전자 근로계약서 발급
# ==============================================================================
with tab3:
    show_guide_image(
        ["assets/manual_staff.png"],
        "▲ [직원관리 · 전자근로계약서 화면] ① 퇴사 시 상태만 변경 · ② 보건증 만료일 갱신 · ③ 1단계 직원 선택 · ④ 링크 발송/대기 삭제",
    )

    render_step_card(
        badge="STEP 1 · 명부 먼저 등록",
        heading="신규 직원 등록하기 (파트타임 · 정규직)",
        tone="slate",
        body_html=(
            f"좌측 메뉴 <code>직원관리</code>(비밀번호 <code>{active_mgr_pin}</code>)에 접속한 뒤, 반드시 <b>직원 명부에 먼저 등록</b>해야 계약서와 출퇴근기록부에 정보가 연동됩니다."
            "<ol>"
            "<li>상단 <b>신규 직원 등록</b> 영역을 열어 <b>파트타임(시급제)</b> 또는 <b>정규직(월급제)</b>을 선택합니다.</li>"
            "<li>입사일자, 이름(예금주명), 시급(또는 계약급여/제세금), 은행명, 계좌번호, 이메일을 입력하고 등록합니다.</li>"
            "<li>신규 파트타임 직원을 등록하면 <b>입사일자·책정 시급 알림</b>이 환경설정에 지정된 수신 대상(대표/매니저/모두) 텔레그램으로 자동 발송됩니다.</li>"
            "</ol>"
        ),
        footer_html=(
            '<div class="note-tip">'
            "<b>가족·타인 명의 계좌를 쓰는 직원인 경우:</b> <code>이름</code> 칸에는 통장 예금주명을 적고, <code>메모</code> 칸에 <b>실제 출근하는 직원 이름</b>(5자 이내)을 적으면 출퇴근기록부와 급여 이체가 모두 정확히 연동됩니다."
            "</div>"
        ),
    )

    render_step_card(
        badge="STEP 2 · 전자계약서 링크 발급",
        heading="1단계 직원 선택 후 전자 근로계약서 링크 생성",
        tone="blue",
        body_html=(
            "<ol>"
            "<li><code>직원관리</code> 하단의 <b>전자 근로계약서 발급 및 서명 현황</b>으로 이동합니다.</li>"
            "<li><b>1단계: 계약서를 작성할 직원 선택</b> 드롭다운에서 방금 등록한 직원을 선택합니다.</li>"
            "<li>직원을 선택하면 아래에 2단계 근로조건 입력창이 열리며, 시급/월급·입사일·계좌·이메일이 자동으로 채워집니다.</li>"
            "<li>근무 시작/종료시간, 휴게시간, 주 근무일수, 주휴요일을 확인한 뒤 <b>[전자 근로계약서 링크 발급]</b>을 누릅니다.</li>"
            "<li>생성된 매장 전용 링크를 복사해 카톡/문자로 보내거나, 아래 목록의 <b>[링크 발송]</b> 버튼으로 이메일 전송합니다.</li>"
            "</ol>"
        ),
        footer_html=(
            '<div class="note-warn">'
            "<b>잘못 발급했을 때:</b> 직원이 서명하기 전(<code>서명대기</code>)이라면 목록 우측의 <b>[대기 삭제]</b> 버튼으로 즉시 삭제할 수 있습니다."
            "</div>"
        ),
    )

    render_step_card(
        badge="STEP 3 · 직원 서명 및 자동 보관",
        heading="직원 스마트폰 전자서명 (만 18세 미만 연소근로자 자동 전환)",
        tone="emerald",
        body_html=(
            "<ul>"
            "<li>직원이 본인 스마트폰으로 링크에 접속해 <b>주민번호·주소·보건증 제출일 확인 → 정자 성명 입력(자동 사인) → [최종 제출]</b>을 누르면 완료됩니다.</li>"
            "<li><b>만 18세 미만(연소근로자) 자동 처리:</b> 주민번호 기준 만 18세 미만인 경우 자동으로 <b>연소근로자 배지</b>가 표시되며, <b>연소근로자 표준근로계약서 + 친권자(부모님) 동의서 + 비밀유지 서약서</b>까지 한 번에 전자서명해 합본 PDF로 생성됩니다.</li>"
            "<li><b>연타 주의 안내:</b> 제출 후 PDF 생성에 2~3초가 걸리므로 버튼을 여러 번 누르지 않도록 안내해 주세요.</li>"
            "<li>서명 완료 즉시 <b>지점별 전용 구글 드라이브 PDF 자동 보관 + 직원 이메일 사본 교부 + 직원 명부(보건증 만료일 +1년) 업데이트 + 텔레그램 알림</b>이 한 번에 완료됩니다.</li>"
            "</ul>"
        ),
    )

# ==============================================================================
# [탭 4] 퇴사 처리 · 보건증 만료 관리 · 시급 변경
# ==============================================================================
with tab4:
    show_guide_image(
        ["assets/manual_staff.png"],
        "▲ [직원관리 퇴사·보건증·시급 위치] ① 퇴사 시 행 삭제 금지(상태만 변경) · ② 보건증 만료일(+1년) 갱신",
    )

    render_step_card(
        badge="퇴사자 처리 원칙 · 행 삭제 금지",
        heading="직원이 퇴사할 때는 '상태'만 [퇴사]로 변경하세요",
        tone="amber",
        body_html=(
            "<ul>"
            "<li><b>절대 명부에서 행(줄)을 삭제하지 마세요.</b> 행을 지우면 그달에 일한 마지막 급여가 정산표에서 사라집니다.</li>"
            "<li><b>파트타임 퇴사 처리:</b>"
            "<ol><li><code>직원관리</code> 파트타임 명부 표에서 해당 직원의 <code>상태</code> 칸을 <code>재직</code> → <b><code>퇴사</code></b>로 변경</li>"
            "<li><code>메모</code> 칸에 퇴사일(예: <code>11/20 퇴사</code>)을 적고 하단 <b>[수정된 직원 명부 · 시급/계좌 · 보건증 정보 저장하기]</b> 클릭</li>"
            "<li>즉시 출퇴근기록부·주간스케줄 목록에서 제외되며, 이번 정산 기간 근무 기록이 있으면 마지막 월급날 급여는 정상 계산됩니다.</li></ol></li>"
            "<li><b>정규직 퇴사 처리:</b> 정규직은 <code>퇴사</code>로 바꾸면 급여 정산표에서 즉시 빠지므로, <b>반드시 마지막 달 급여(일할 계산 등) 정산과 이체를 모두 마친 뒤에 <code>퇴사</code>로 변경</b>해 주세요.</li>"
            "</ul>"
        ),
    )

    render_step_card(
        badge="위생 관리 · 과태료 예방",
        heading="보건증 만료 30일 전(D-30) 알림 및 갱신 처리",
        tone="slate",
        body_html=(
            "<ol>"
            "<li><b>자동 경고 확인:</b> 재직 직원의 보건증 만료일이 30일 이내로 다가오면 매일 보는 <code>출퇴근기록부</code> 상단의 <b>[▲ 보건증 갱신 N명 확인]</b> 버튼이 빨간색으로 점등됩니다. 버튼을 눌러 대상자와 남은 일수를 확인하고, 당사자가 출퇴근 시 이름을 선택할 때도 갱신 안내가 자동 표시됩니다.</li>"
            "<li><b>갱신 후 매니저 조치:</b> 직원이 새 보건증을 제출하면 <code>직원관리</code> 명부 표의 <b><code>보건증만료일 (YYYY-MM-DD)</code></b> 칸을 <b>새 검진일 + 1년 뒤 날짜</b>로 수정한 뒤 저장하세요. 즉시 경고 알림이 해제됩니다.</li>"
            "</ol>"
        ),
    )

    render_step_card(
        badge="근로계약 연장 · 시급 인상",
        heading="계약 연장 또는 파트타임 시급 변경 시",
        tone="slate",
        body_html=(
            "<ul>"
            "<li><code>직원관리</code> 표에서 파트타임 <b><code>시급</code></b>을 수정하고 저장하면, 변경 전·후 시급 차액이 자동 계산되어 <b>설정된 수신 대상(대표/매니저/모두) 텔레그램으로 즉시 알림</b>이 발송됩니다.</li>"
            "<li>재계약이 필요할 때는 기존 계약서를 지우지 말고 직원을 선택해 새 근로계약서 링크를 발급하면 되며, 구글 드라이브에는 서명 날짜별로 과거·신규 계약서 PDF가 모두 별도 보관됩니다.</li>"
            "</ul>"
        ),
    )

# ==============================================================================
# [탭 5] 급여정산 · 경영분석 · 환경설정
# ==============================================================================
with tab5:
    show_guide_image(
        ["assets/manual_payroll.png"],
        "▲ [급여정산 · 경영분석 화면] ① 파트타임 실시간 전체합계(미승인 포함) · ② 현재 진행월 누적 · ③ 원클릭 확정 발송 · ④ 최신순 그라데이션 분석",
    )

    render_step_card(
        badge="STEP 1 · 실시간 파트타임 인건비 모니터링",
        heading="급여정산 상단 실시간 요약 카드 확인",
        tone="blue",
        body_html=(
            f"<code>급여정산</code>(매월 {payroll_start_day}일 기준 정산) 상단 컨트롤 영역에서 현재 파트타임 누적 인건비를 실시간으로 확인할 수 있습니다."
            "<ul>"
            "<li><b>선택 정산 집계 기간:</b> 선택한 기준일에 해당하는 정산 구간(예: 전월 5일 ~ 당월 4일)을 표시합니다.</li>"
            "<li><b>파트타임 실시간 전체 합계 (미승인 포함):</b> 선택한 정산 기간의 <b>승인분 + 매니저 미승인분</b>을 모두 합산한 실지급 예상액, 세전 금액, 미승인 건수를 실시간 표시합니다.</li>"
            "<li><b>현재 진행월 파트타임 실시간 누적:</b> 지난 정산월을 조회 중일 때, 오늘 날짜가 속한 <b>현재 진행월의 파트타임 실시간 누적액</b>도 나란히 표시됩니다.</li>"
            "</ul>"
        ),
    )

    render_step_card(
        badge="STEP 2 · 매월 정산 실행 (관리자 전용)",
        heading="월별 급여 정산 · 대량이체 엑셀 · 원클릭 확정 발송",
        tone="slate",
        body_html=(
            "<ol>"
            "<li><b>미확인 근태 점검:</b> 상단에 빨간색 미확인 경고가 떠 있다면 <code>출퇴근기록부</code>에서 매니저 승인이 빠진 건이 있다는 뜻입니다. 먼저 일괄 승인을 마친 뒤 <b>[시트 새로고침]</b>을 누릅니다.</li>"
            "<li><b>정규직 급여 및 특근·휴무 변동 반영:</b>"
            "<ul><li>기본 공식: <b><code>계약급여 - 제세금 = 계산급여</code></b> → <b><code>계산급여 ± 변동급여 = 입금급여(실이체액)</code></b></li>"
            "<li>표 바로 위에 자동 표시되는 <b>정규직 특근·휴무 등록 내역</b>을 참고해 추가출근은 양수(예: <code>100000</code>), 기타휴무 차감은 음수(예: <code>-100000</code>)로 입력합니다.</li>"
            "<li>중도 입·퇴사자는 <b>정규직 중도 입·퇴사자 일할 계산기</b>에 근무일수만 입력하면 원클릭으로 표에 반영됩니다.</li></ul></li>"
            "<li><b>파트타임 급여 확인:</b> 매니저 승인된 총 근무시간 × 시급으로 자동 계산되며, 세전 100만 원 이상은 <code>3.3%</code>, 미만은 <code>0.9%</code> 공제율이 자동 적용됩니다.</li>"
            "<li><b>대량이체 엑셀 및 일괄 확정:</b> <b>[은행 대량이체 엑셀 (.xlsx)]</b>을 받아 이체하고, <b>[정산 확정 및 발송하기]</b>를 누르면 <b>① 급여히스토리 시트 백업 ② 정규직근태변동 완료 처리 ③ 세무사 이메일(.txt 첨부) 발송 ④ 전 직원 급여명세서 발송 ⑤ 텔레그램 정산 보고</b>가 한 번에 완료됩니다.</li>"
            "</ol>"
        ),
    )

    render_step_card(
        badge="STEP 3 · 매출 · 인건비 경영분석 탭",
        heading="최신순 월별 손익 · 전년 동월 대비(YoY) 색상 판독법",
        tone="emerald",
        body_html=(
            "<code>급여정산</code>의 두 번째 탭 <b><code>매출 · 인건비 경영분석</code></b>은 중요 데이터부터 바로 볼 수 있도록 <b>상세 내역 → 전년 동월 대비(YoY) → 추이 차트 → 직원별 누적 요약</b> 순서로 구성되어 있으며, 모든 표는 <b>최신월이 맨 위</b>에 표시됩니다."
            "<ul>"
            "<li><b>파란색 그라데이션 (긍정 지표):</b> 매출 증가, 인건비 절감, 인건비율 하락 등 개선 폭이 클수록 진한 파란색으로 표시됩니다.</li>"
            "<li><b>빨간색 그라데이션 (주의 지표):</b> 매출 감소, 인건비 증가, 인건비율 상승 등 주의 폭이 클수록 진한 빨간색으로 표시됩니다.</li>"
            "</ul>"
        ),
    )

    render_step_card(
        badge="STEP 4 · 환경설정 안내",
        heading="지점별 시스템 환경설정에서 변경 가능한 주요 항목",
        tone="slate",
        body_html=(
            "좌측 메뉴 <code>환경설정</code>에서 매장별 운영 규칙을 코드 수정 없이 직접 관리할 수 있습니다."
            "<ul>"
            "<li><b>보안 · 알림:</b> 매니저 PIN 변경, 텔레그램 봇 토큰 및 알림 종류별 수신 대상(<code>대표</code> / <code>매니저</code> / <code>모두</code> / <code>끄기</code>) 분기</li>"
            "<li><b>근태 · 급여:</b> 출퇴근 시간 입력 단위(분), 급여 정산 시작일, 파트타임 세율 및 목표 인건비율</li>"
            "<li><b>실시간 입금·chak 설정:</b> 평일·주말 영업시간, 주말 브레이크타임, 제외 입금자 목록 및 <b>[입금 알림 테스트]</b> 원클릭 진단 버튼</li>"
            "</ul>"
        ),
    )
