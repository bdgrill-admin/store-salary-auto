"""
================================================================================
[파일명] views/manual.py
[역할] 아이폰(모바일) 및 매장 PC/태블릿 겸용 '매니저 실무 교육 매뉴얼' 전용 탭
[주요 기능]
  1. 아이폰 세로 화면에 최적화된 큰 글씨·카드형 레이아웃 및 핵심 요약 배너 제공
  2. 상단 탭(일일 출퇴근/승인 | 신규채용/계약서 | 퇴사/보건증 | 월말 급여정산)으로 빠른 이동
  3. 폴더 내 스크린샷 이미지(manual_att.png, manual_staff.png, manual_contract.png)가
     있으면 자동으로 화면에 삽입하고, 없어도 시각적 UI 가이드 박스로 완벽히 대체 표시
================================================================================
"""

import os
import streamlit as st

st.markdown(
    """
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    }
    .block-container {
        padding-top: 2.5rem;
        padding-bottom: 3rem;
        max-width: 920px;
    }
    .manual-header {
        background: linear-gradient(135deg, #1E293B 0%, #334155 100%);
        color: #FFFFFF;
        padding: 18px 20px;
        border-radius: 14px;
        margin-bottom: 16px;
    }
    .manual-header h2 {
        color: #FFFFFF !important;
        font-size: 1.35rem;
        font-weight: 800;
        margin: 0 0 6px 0;
    }
    .manual-header p {
        color: #E2E8F0;
        font-size: 0.92rem;
        margin: 0;
        line-height: 1.45;
    }
    .rule-card {
        background-color: #FFFBEB;
        border: 2px solid #F59E0B;
        border-radius: 12px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }
    .rule-title {
        font-size: 1.05rem;
        font-weight: 800;
        color: #B45309;
        margin-bottom: 8px;
    }
    .step-card {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-left: 5px solid #1E293B;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 14px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }
    .step-badge {
        display: inline-block;
        background-color: #1E293B;
        color: #FFFFFF;
        font-size: 0.78rem;
        font-weight: 700;
        padding: 3px 9px;
        border-radius: 6px;
        margin-bottom: 6px;
    }
    .step-heading {
        font-size: 1.08rem;
        font-weight: 800;
        color: #0F172A;
        margin-bottom: 8px;
    }
    .step-body {
        font-size: 0.95rem;
        color: #334155;
        line-height: 1.65;
    }
    .ui-mock {
        background-color: #F8FAFC;
        border: 1px dashed #94A3B8;
        border-radius: 8px;
        padding: 12px 14px;
        margin-top: 10px;
        font-size: 0.88rem;
        color: #1E293B;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def show_guide_image(file_candidates: list, caption: str):
    """폴더에 스크린샷 파일이 있으면 출력합니다."""
    for fp in file_candidates:
        if os.path.exists(fp):
            st.image(fp, caption=caption, use_container_width=True)
            return True
    return False


# ------------------------------------------------------------------------------
# 상단 헤더 및 매니저 3대 핵심 원칙 요약 카드
# ------------------------------------------------------------------------------
st.markdown(
    """
    <div class="manual-header">
        <h2>📖 [분당그릴] 매니저 업무 매뉴얼</h2>
        <p>아이폰·태블릿·PC 어디서든 아래 탭을 눌러 업무 순서를 확인하세요.<br>
        • <b>매니저 전용 비밀번호(PIN):</b> <code>0524</code></p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="rule-card">
        <div class="rule-title">⭐ 매니저 핵심 체크리스트 3줄 요약</div>
        <div style="font-size:0.94rem; color:#78350F; line-height:1.65;">
            <b>1. [매일 마감/오픈]</b> <code>⏱️ 출퇴근 기록부</code> 우측 상단에서 비밀번호(<code>0524</code>) 입력 후 <b>미확인 근무 기록을 승인</b>합니다.<br>
            <b>2. [신규 채용 시]</b> <code>👥 직원 관리</code>에서 <b>① 명부에 먼저 등록</b>한 뒤 → <b>② 아래 전자계약서에서 직원을 선택해 링크를 발급</b>합니다.<br>
            <b>3. [직원 퇴사 시]</b> 명부에서 줄을 절대 지우지 말고 <b><code>상태</code>만 <code>퇴사</code>로 바꾼 뒤 저장</b>합니다.
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------------------
# 모바일 터치 친화형 4개 업무 탭 구성
# ------------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs([
    "⏱️ 1. 일일 출퇴근·승인",
    "📝 2. 신규채용·계약서",
    "🏥 3. 퇴사·보건증 관리",
    "💰 4. 월말 급여정산",
])

# ==============================================================================
# [탭 1] 일일 출퇴근 기록 및 매니저 승인
# ==============================================================================
with tab1:
    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">STEP 1 · 직원 안내</span>
            <div class="step-heading">출퇴근 시간 신규 입력 및 수정 지도</div>
            <div class="step-body">
                • <b>신규 출퇴근 입력:</b> 하단 <code>2. 출퇴근 시간 입력/수정</code>에서 직원이 <b><code>🔽 이름 선택</code></b>으로 본인 이름을 먼저 골라야 시간 입력칸이 열립니다.<br>
                • 시간을 맞추고 <b>[💾 출퇴근 시간 저장하기]</b>를 누르면 즉시 시트에 기록되고, 다음 사람을 위해 화면이 자동 초기화됩니다.<br>
                • <b>잘못 입력했을 때(수정):</b> 새로 또 입력하지 말고, 상단 <code>1. 일 근무현황</code> 표에서 <b>본인 줄 왼쪽 체크박스(☑️)를 클릭</b>하면 파란색으로 바뀌며 하단이 수정 모드로 전환됩니다. 수정 사유를 적고 <b>[🔄 수정 내역 반영하기]</b>를 누르면 됩니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">STEP 2 · 매니저 필수 업무 ⭐</span>
            <div class="step-heading">🔐 매니저 전용 확인 (일일 근태 승인)</div>
            <div class="step-body">
                • <b>중요:</b> 매니저가 승인(<code>✅ 확인완료</code>)하지 않은 기록은 <b>월급날 급여 자동 계산에서 아예 제외</b>됩니다.<br>
                • <b>승인 순서:</b><br>
                  &nbsp;&nbsp;① 우측 상단 주황색 <b><code>🔐 매니저 전용 확인</code></b> 박스에 비밀번호(<code>0524</code>) 입력<br>
                  &nbsp;&nbsp;② <b><code>⏳ 미확인 승인</code></b> 탭에서 직원들이 입력한 출퇴근 시간이 맞는지 확인 후 체크박스 선택<br>
                  &nbsp;&nbsp;③ <b>[✅ 선택한 N건 확인 완료]</b> 버튼 클릭<br>
                • <b>승인 해제:</b> 이미 확인 완료된 건은 직원이 임의로 고칠 수 없도록 잠깁니다. 수정이 필요하면 <b><code>🔓 승인 해제</code></b> 탭에서 <b>[해제]</b>를 눌러 잠금을 풀어주세요.
            </div>
            <div class="ui-mock">
                화면 위치: <b>⏱️ 출퇴근 기록부</b> ➔ 우측 상단 <b>[🔐 매니저 전용 확인]</b> 박스 ➔ 비밀번호 <b>0524</b> 입력
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    show_guide_image(
        ["assets/manual_att.png", "manual_att.png", "image_36f7d9.png"],
        "▲ [출퇴근 기록부 화면] 상단 보건증 알림 배너 · 우측 매니저 전용 확인 · 하단 출퇴근 입력창",
    )

# ==============================================================================
# [탭 2] 신규 채용 및 전자 근로계약서 발급
# ==============================================================================
with tab2:
    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">STEP 1 · 명부 먼저 등록</span>
            <div class="step-heading">➕ 신규 직원 등록하기 (파트타임 · 정규직)</div>
            <div class="step-body">
                좌측 메뉴 <b><code>👥 직원 관리</code></b>(비밀번호 <code>0524</code>)에 접속한 뒤, 반드시 <b>직원 명부에 먼저 등록</b>해야 계약서에 정보가 연동됩니다.<br><br>
                1. 상단 <b><code>➕ 신규 직원 등록하기 (파트타임 · 정규직)</code></b> 클릭<br>
                2. <b>파트타임(시급제)</b> 또는 <b>정규직(월급제)</b> 선택<br>
                3. 입사일자, 이름(예금주명), 시급(또는 계약급여/제세금), 은행명, 계좌번호, 이메일 입력 후 <b>[✅ 신규 직원 등록]</b> 클릭<br>
                <span style="color:#B45309; font-size:0.88rem;">💡 <b>가족/타인 명의 계좌를 쓰는 직원인 경우:</b> <code>이름</code> 칸에는 통장 예금주명을 적고, <code>메모</code> 칸에 <b>실제 출근하는 직원 이름</b>(5자 이내)을 적으면 출퇴근기록부와 급여 이체가 모두 정확히 연동됩니다.</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    show_guide_image(
        ["assets/manual_staff.png", "manual_staff.png", "image_36fafe.png"],
        "▲ [직원 관리 상단 화면] 신규 직원 등록 폼 및 파트타임/정규직 명부 표",
    )

    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">STEP 2 · 전자계약서 링크 발급</span>
            <div class="step-heading">📝 1단계 직원 선택 후 근로계약서 링크 생성</div>
            <div class="step-body">
                1. 화면 아래쪽 <b><code>📝 전자 근로계약서 발급 및 서명 현황</code></b>으로 이동합니다.<br>
                2. 노란색 박스인 <b><code>👤 1단계: 계약서를 작성할 직원을 먼저 선택해 주세요 (필수)</code></b> 드롭다운을 눌러 방금 등록한 직원을 선택합니다.<br>
                3. 직원을 선택하는 즉시 아래에 2단계 근로조건 입력창이 열리며, 시급/월급·입사일·계좌·이메일이 자동으로 채워집니다.<br>
                4. 근무 시작/종료시간, 휴게시간, 주 근무일수, 주휴요일만 확인한 뒤 <b>[🔗 전자 근로계약서 링크 발급]</b>을 누릅니다.<br>
                5. 생성된 전용 링크를 복사해 직원 카톡/문자로 보내거나, 아래 목록의 <b>[📨 링크 발송]</b> 버튼으로 이메일 전송합니다.<br>
                <span style="color:#DC2626; font-size:0.88rem;">🗑️ <b>잘못 발급했을 때:</b> 직원이 서명하기 전(<code>⏳ 서명대기</code>)이라면 목록 우측의 <b>[🗑️ 대기 삭제]</b> 버튼으로 즉시 지울 수 있습니다.</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    show_guide_image(
        ["assets/manual_contract.png", "manual_contract.png", "image_36fbb7.png"],
        "▲ [전자 근로계약서 발급 화면] 노란색 1단계 박스에서 직원을 선택해야 하단 입력창이 열립니다.",
    )

    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">STEP 3 · 직원 서명 및 자동 보관</span>
            <div class="step-heading">✍️ 직원 스마트폰 전자서명 안내</div>
            <div class="step-body">
                • 직원이 본인 스마트폰으로 링크에 접속해 <b>주민번호·주소·보건증 제출일 확인 ➔ 정자 성명 입력(자동 사인) ➔ [최종 제출]</b>을 누르면 완료됩니다.<br>
                • <b>연타 주의 안내:</b> 제출 후 PDF가 생성되는 2~3초 동안 버튼을 여러 번 누르지 않도록 안내해 주세요. (시스템에 중복 방지 잠금이 적용되어 있습니다.)<br>
                • 서명 완료 즉시 <b>구글 드라이브 PDF 자동 보관 + 직원 이메일 사본 교부 + 직원 명부(보건증 만료일 +1년) 업데이트</b>가 한 번에 끝납니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ==============================================================================
# [탭 3] 퇴사 처리 및 보건증 만료 관리
# ==============================================================================
with tab3:
    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">퇴사자 처리 원칙 ❌ 행 삭제 금지</span>
            <div class="step-heading">직원이 퇴사할 때는 '상태'만 [퇴사]로 변경하세요!</div>
            <div class="step-body">
                • <b>절대 명부에서 행(줄)을 삭제하지 마세요!</b> 행을 지워버리면 그달에 일한 마지막 급여가 정산표에서 사라집니다.<br>
                • <b>파트타임 퇴사 처리:</b><br>
                  &nbsp;&nbsp;① <code>👥 직원 관리</code>의 파트타임 명부 표에서 해당 직원의 <b><code>상태</code></b> 칸을 <code>재직</code> ➔ <b><code>퇴사</code></b>로 변경<br>
                  &nbsp;&nbsp;② 옆의 <b><code>메모</code></b> 칸에 퇴사일(예: <code>11/20 퇴사</code>)을 적고 하단 <b>[💾 저장하기]</b> 클릭<br>
                  &nbsp;&nbsp;③ 즉시 출퇴근기록부 이름 목록에서는 제외되고, 이번 정산 기간에 일한 기록이 있으면 마지막 월급날 급여는 정상 계산됩니다.<br>
                • <b>정규직 퇴사 처리:</b><br>
                  &nbsp;&nbsp;정규직은 <code>퇴사</code>로 바꾸면 급여 정산표에서 즉시 빠지므로, <b>반드시 마지막 달 급여(일할 계산 등) 정산과 이체를 모두 마친 뒤에 <code>퇴사</code>로 변경</b>해 주세요.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">위생 관리 · 과태료 예방</span>
            <div class="step-heading">🏥 보건증 만료 30일 전(D-30) 3중 알림 및 갱신 처리</div>
            <div class="step-body">
                1. <b>자동 경고 확인:</b> 재직 직원의 보건증 만료일이 30일 이내로 다가오면 매일 보는 <b><code>⏱️ 출퇴근 기록부</code> 최상단에 빨간색 경고 배너</b>가 뜨고, 당사자가 출퇴근 시 자기 이름을 고를 때마다 갱신 안내가 뜹니다.<br>
                2. <b>갱신 후 매니저 조치:</b> 직원이 새 보건증을 발급받아 오면 <b><code>👥 직원 관리</code></b> 명부 표 맨 오른쪽의 <b><code>보건증만료일 (YYYY-MM-DD)</code></b> 칸을 <b>새 검진일 + 1년 뒤 날짜</b>로 수정한 뒤 <b>[💾 저장하기]</b>를 눌러주세요. 즉시 경고 배너가 사라집니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">근로계약 연장 · 재계약</span>
            <div class="step-heading">🔄 계약 연장 또는 시급/월급 인상 시</div>
            <div class="step-body">
                • 기존 계약서를 지울 필요 없이, <code>👥 직원 관리</code> 표에서 시급(또는 계약급여)을 인상된 금액으로 수정·저장한 뒤 새 근로계약서 링크를 발급해 서명을 받으면 됩니다.<br>
                • 구글 드라이브에는 서명 날짜별로 과거 계약서와 신규 계약서 PDF가 모두 안전하게 따로 보존됩니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ==============================================================================
# [탭 4] 월말 급여 정산 (매월 5일)
# ==============================================================================
with tab4:
    st.markdown(
        """
        <div class="step-card">
            <span class="step-badge">매월 5일 · 관리자 전용</span>
            <div class="step-heading">💰 월별 급여 정산 (전월 5일 ~ 당월 4일 근무분)</div>
            <div class="step-body">
                1. <b>미확인 근태(🚨) 점검:</b> <code>💰 급여 정산</code> 상단에 빨간색 미확인 경고가 떠 있다면, <code>출퇴근 기록부</code>에서 매니저 승인이 빠진 건이 있다는 뜻입니다. 먼저 승인을 마친 후 <b>[🔄 시트 새로고침]</b>을 누릅니다.<br><br>
                2. <b>정규직 급여 확인:</b><br>
                   • 기본 공식: <b><code>계약급여 - 제세금 = 계산급여</code></b> ➔ <b><code>계산급여 ± 변동급여 = 입금급여(실이체액)</code></b><br>
                   • 추가근무 수당은 양수(예: <code>100000</code>), 휴무 차감은 음수(예: <code>-100000</code>)로 <b><code>변동급여 (+/-)</code></b> 칸에 입력하고 사유를 적으면 우측 <b><code>입금급여</code></b>가 자동 계산됩니다.<br>
                   • 중도 입·퇴사자는 표 위의 <b><code>🧮 정규직 중도 입·퇴사자 일할 계산기</code></b>를 열어 근무일수만 넣으면 원클릭으로 표에 반영됩니다.<br><br>
                3. <b>파트타임 급여 확인:</b><br>
                   • 매니저 승인된 총 근무시간 × 시급으로 자동 계산되며, 세전 100만 원 이상은 <code>3.3%</code>, 미만은 <code>0.9%</code> 공제율이 자동 적용됩니다.<br><br>
                4. <b>대량이체 엑셀 다운로드 및 일괄 확정:</b><br>
                   • 우측의 <b>[은행 대량이체 엑셀 (.xlsx)]</b>을 다운로드하여 은행 이체에 사용합니다.<br>
                   • <b>[정산 확정 및 발송하기]</b>를 누르면 <b>① 급여히스토리 시트 백업 + ② 세무사 이메일(.txt 첨부) 발송 + ③ 전 직원 급여명세서 발송 + ④ 대표님 텔레그램 보고</b>가 원클릭으로 완료됩니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
