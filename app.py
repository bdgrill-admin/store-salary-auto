"""
================================================================================
[파일명] app.py
[역할] 분당그릴 근태 · 급여 · 전자근로계약서 시스템의 메인 진입점 (라우터)
[주요 기능]
  1. 웹 브라우저 탭 제목("분당그릴 근태 · 급여 시스템"), 아이콘("🥩"), 와이드 화면 레이아웃 설정
  2. 접속 URL 주소 파라미터(?contract_id=...) 유무에 따른 화면 자동 분기(Routing):
     - [직원 서명 모드] URL에 'contract_id'가 있으면 -> 다른 관리 메뉴를 아예 로드하지 않고
       오직 '전자 근로계약서(views/contract_sign.py)' 서명 페이지만 단독 실행 (보안 유지)
     - [매장 운영/관리 모드] 일반 접속이면 -> 좌측 메뉴바에
       ① 출퇴근 기록부(views/attendance.py)
       ② 급여 정산(views/payroll.py)
       ③ 직원 관리(views/staff.py) 3개 페이지를 구성하여 실행
================================================================================
"""

import streamlit as st

st.set_page_config(
    page_title="분당그릴 통합 관리 시스템",
    layout="wide",
    initial_sidebar_state="collapsed",  # 최초 접속 시 좌측 사이드바를 접힌 상태로 시작
)

# ------------------------------------------------------------------------------
# 2. 접속 경로(URL 파라미터)에 따른 페이지 분기 처리
# ------------------------------------------------------------------------------
if "contract_id" in st.query_params:
    # [직원 전용] 매니저가 발급한 계약서 링크(?contract_id=xxxx)로 접속한 경우
    # -> 출퇴근 기록부나 급여 정산 등 매장 내부 메뉴는 원천 차단하고 계약서 화면만 연결
    pg = st.navigation([
        st.Page("views/contract_sign.py", title="▪\u00A0\u00A0전자근로계약서", default=True),
    ])
elif "schedule" in st.query_params:
    # [직원 전용] 주간 스케줄 신청 링크(?schedule=매장명)로 접속한 경우
    # -> 매장 내부 메뉴는 차단하고 본인 희망/휴무 신청 화면만 단독 실행
    pg = st.navigation([
        st.Page("views/schedule_submit.py", title="▪\u00A0\u00A0주간스케줄신청", default=True),
    ])
else:
    # [매장/관리자 전용] 기본 주소로 접속한 경우
    pg = st.navigation([
        st.Page("views/attendance.py", title="▪\u00A0\u00A0출퇴근기록부", default=True),
        st.Page("views/schedule.py", title="▪\u00A0\u00A0주간스케줄"),
        st.Page("views/staff.py", title="▪\u00A0\u00A0직원관리"),
        st.Page("views/payroll.py", title="▪\u00A0\u00A0급여정산"),
        st.Page("views/settlement.py", title="▪\u00A0\u00A0월말정산"),
        st.Page("views/manual.py", title="▪\u00A0\u00A0매니저매뉴얼"),
        st.Page("views/settings.py", title="▪\u00A0\u00A0환경설정"),
    ])

# ------------------------------------------------------------------------------
# 3. 선택된 페이지 실행
# ------------------------------------------------------------------------------
pg.run()
