"""
================================================================================
[파일명] views/settings.py
[역할] 대표님/관리자 전용 '매장 통합 시스템 환경설정 & 연동 상태 진단' 페이지
[주요 기능]
  1. 관리자 비밀번호 보안 잠금
  2. 구글 시트('환경설정' 탭)에 설정값 영구 저장 및 불러오기 (서버 재시작 시에도 유지)
     - 🔐 보안 및 권한: 매니저 PIN, 관리자 비밀번호, 매니저 급여정산 메뉴 열람 허용 여부
     - ⏱️ 출퇴근 및 보건증 규칙: 시간 선택 단위(분), 보건증 만료 알림 기준일(D-Day)
     - 📝 전자 근로계약서 기본값: 사업장명, 대표자명, 주소, 연락처, 기본 근무시간/휴게시간/업무내용
     - 💰 급여 정산 및 발송 설정: 급여 정산 기준일, 세무사 수신 이메일, 통장 표기 문구
     - 📲 텔레그램 알림 설정: 보건증 일일 브리핑 / 계약서 서명 완료 / 급여 정산 보고 ON·OFF
  3. 원클릭 시스템 연동 상태 진단 (구글 시트 · 텔레그램 · Apps Script 이메일 테스트)
================================================================================
"""

import os
import json
import datetime
import requests
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()


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
    },
    # 향후 감동한점 오픈 시 주석 해제
    # "감동한점": {
    #     "db_id": "여기에_감동한점_통합근태DB_ID",
    # },
}

CREDENTIALS_FILE = "credentials.json"
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD", "0524")

# 환경설정 기본값 정의
DEFAULT_SETTINGS = {
    # 1. 보안 및 권한
    "manager_pin": get_secret("MANAGER_PIN_BUNDANG", "0524"),
    "admin_password": get_secret("ADMIN_PASSWORD", "0524"),
    "allow_mgr_payroll": "FALSE",
    # 2. 출퇴근 및 보건증 규칙
    "att_time_step_min": "10",
    "health_alert_days": "30",
    # 3. 전자 근로계약서 기본 템플릿
    "store_title": "분당그릴",
    "owner_name": "이용석",
    "store_phone": "031-713-0342",
    "store_address": "경기도 성남시 분당구 미금일로 74번길 13-3 1층",
    "default_work_start": "17:00",
    "default_work_end": "22:00",
    "default_break_min": "30",
    "default_job_desc": "홀 서빙 및 주방 보조 등 매장 운영 전반",
    # 4. 급여 정산 및 발송 설정
    "payroll_start_day": "5",
    "tax_accountant_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
    "bank_transfer_prefix": "분당그릴",
    "auto_send_payslip": "TRUE",
    # 5. 텔레그램 알림 ON/OFF
    "tg_alert_health": "TRUE",
    "tg_alert_contract": "TRUE",
    "tg_alert_payroll": "TRUE",
}

st.markdown(
    """
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    }
    .block-container {
        padding-top: 2.8rem;
        padding-bottom: 3rem;
        max-width: 1180px;
    }
    .app-title {
        font-size: 1.55rem;
        font-weight: 700;
        color: #1E293B;
        margin: 0;
    }
    .section-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1E293B;
        margin: 0.8rem 0 0.5rem 0;
        padding-left: 0.6rem;
        border-left: 4px solid #334155;
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


@st.cache_data(ttl=30, show_spinner="환경설정 데이터를 불러오는 중...")
def load_settings_from_sheet(db_id: str) -> dict:
    """구글 시트 '환경설정' 탭에서 설정값을 로드합니다. 탭이 없으면 기본값을 반환합니다."""
    cfg = dict(DEFAULT_SETTINGS)
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(db_id)
        titles = [ws.title.strip() for ws in ss.worksheets()]
        if "환경설정" not in titles:
            return cfg
        ws = ss.worksheet("환경설정")
        rows = ws.get_all_values()
        for r in rows[1:]:
            if len(r) >= 2 and r[0].strip():
                cfg[r[0].strip()] = r[1].strip()
    except Exception:
        pass
    return cfg


def save_settings_to_sheet(db_id: str, new_cfg: dict):
    """구글 시트 '환경설정' 탭에 설정값을 저장합니다. 탭이 없으면 자동 생성합니다."""
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    titles = [ws.title.strip() for ws in ss.worksheets()]
    if "환경설정" in titles:
        ws = ss.worksheet("환경설정")
        ws.clear()
    else:
        ws = ss.add_worksheet(title="환경설정", rows=100, cols=4)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [["설정키", "설정값", "최종수정일시"]]
    for k, v in new_cfg.items():
        rows.append([str(k), str(v), now_str])

    ws.update(range_name="A1", values=rows, value_input_option="USER_ENTERED")


# ==============================================================================
# 1. 관리자 보안 로그인 확인
# ==============================================================================
h1, h2 = st.columns([3.2, 1.0], vertical_alignment="center")
with h1:
    st.markdown('<div class="app-title">⚙️ 시스템 환경설정</div>', unsafe_allow_html=True)
with h2:
    selected_store = st.selectbox("설정 매장", list(STORES.keys()), index=0, label_visibility="collapsed")

store_cfg = STORES[selected_store]
current_cfg = load_settings_from_sheet(store_cfg["db_id"])
active_admin_pwd = current_cfg.get("admin_password") or ADMIN_PASSWORD

if not st.session_state.get("authenticated", False):
    st.write("")
    _, c_mid, _ = st.columns([1.1, 1.4, 1.1])
    with c_mid:
        with st.container(border=True):
            st.markdown("#### 🔒 대표자 / 관리자 전용")
            st.caption("매장 환경설정 변경 및 연동 테스트를 위해 관리자 비밀번호를 입력하세요.")
            pwd = st.text_input("관리자 비밀번호", type="password", placeholder="비밀번호 입력", label_visibility="collapsed")
            if st.button("확인", type="primary", use_container_width=True):
                if pwd == active_admin_pwd:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()

st.caption("💡 여기서 변경한 설정은 구글 시트(`환경설정` 탭)에 영구 저장되며, 매장 PC·태블릿·아이폰에 즉시 동기화됩니다.")

# ==============================================================================
# 2. 5개 카테고리 탭 UI
# ==============================================================================
t_sec, t_att, t_con, t_pay, t_diag = st.tabs([
    "🔐 보안 · 권한",
    "⏱️ 출퇴근 · 보건증",
    "📝 근로계약서 기본값",
    "💰 급여 · 세무사 발송",
    "📡 알림 · 연동 진단",
])

with st.form("settings_main_form"):
    # --------------------------------------------------------------------------
    # [탭 1] 보안 및 권한 관리
    # --------------------------------------------------------------------------
    with t_sec:
        st.markdown('<div class="section-title">비밀번호 및 매니저 접근 권한</div>', unsafe_allow_html=True)
        with st.container(border=True):
            s1, s2 = st.columns(2)
            in_mgr_pin = s1.text_input(
                "매니저 전용 PIN 번호 (출퇴근 승인 · 직원 관리 · 매뉴얼)",
                value=current_cfg.get("manager_pin", "0524"),
                max_chars=10,
            )
            in_admin_pwd = s2.text_input(
                "대표자/관리자 비밀번호 (급여 정산 · 환경설정)",
                value=current_cfg.get("admin_password", "0524"),
                max_chars=20,
            )
            in_allow_mgr_payroll = st.checkbox(
                "매니저에게도 '급여 정산' 페이지 열람 허용 (체크 해제 시 대표자 비밀번호만 허용)",
                value=(current_cfg.get("allow_mgr_payroll", "FALSE").upper() == "TRUE"),
            )

    # --------------------------------------------------------------------------
    # [탭 2] 출퇴근 및 보건증 규칙
    # --------------------------------------------------------------------------
    with t_att:
        st.markdown('<div class="section-title">출퇴근 입력 및 보건증 만료 알림 기준</div>', unsafe_allow_html=True)
        with st.container(border=True):
            a1, a2 = st.columns(2)
            step_options = ["5", "10", "15", "30"]
            cur_step = current_cfg.get("att_time_step_min", "10")
            step_idx = step_options.index(cur_step) if cur_step in step_options else 1
            in_time_step = a1.selectbox(
                "출퇴근 시간 선택 단위 (분)",
                options=step_options,
                index=step_idx,
                format_func=lambda x: f"{x}분 단위",
            )
            in_health_days = a2.number_input(
                "보건증 만료 사전 경고 기준일 (만료 며칠 전부터 알림)",
                min_value=7,
                max_value=90,
                value=int(current_cfg.get("health_alert_days", "30") or 30),
                step=1,
            )

    # --------------------------------------------------------------------------
    # [탭 3] 전자 근로계약서 기본 템플릿
    # --------------------------------------------------------------------------
    with t_con:
        st.markdown('<div class="section-title">사업장 정보 및 계약서 기본 근무조건</div>', unsafe_allow_html=True)
        with st.container(border=True):
            c1, c2, c3 = st.columns([1.2, 1.0, 1.2])
            in_store_title = c1.text_input("사업체명 (계약서 표기)", value=current_cfg.get("store_title", selected_store))
            in_owner_name = c2.text_input("대표자 성명", value=current_cfg.get("owner_name", "이용석"))
            in_store_phone = c3.text_input("매장 전화번호", value=current_cfg.get("store_phone", "031-713-0342"))

            in_store_addr = st.text_input(
                "사업장 소재지 (근무장소)",
                value=current_cfg.get("store_address", "경기도 성남시 분당구 미금일로 74번길 13-3 1층"),
            )

            c4, c5, c6 = st.columns(3)
            in_w_start = c4.text_input("기본 소정근로 시작시간", value=current_cfg.get("default_work_start", "17:00"))
            in_w_end = c5.text_input("기본 소정근로 종료시간", value=current_cfg.get("default_work_end", "22:00"))
            in_break_m = c6.number_input(
                "기본 휴게시간 (분)",
                min_value=0,
                max_value=180,
                value=int(current_cfg.get("default_break_min", "30") or 30),
                step=10,
            )
            in_job_desc = st.text_input(
                "기본 업무의 내용",
                value=current_cfg.get("default_job_desc", "홀 서빙 및 주방 보조 등 매장 운영 전반"),
            )

    # --------------------------------------------------------------------------
    # [탭 4] 급여 정산 및 발송 설정
    # --------------------------------------------------------------------------
    with t_pay:
        st.markdown('<div class="section-title">월별 급여 정산일 · 세무사 수신처 · 통장 표기</div>', unsafe_allow_html=True)
        with st.container(border=True):
            p1, p2 = st.columns(2)
            in_pay_day = p1.number_input(
                "매월 급여 정산 기준일 (예: 5일 = 전월 5일 ~ 당월 4일)",
                min_value=1,
                max_value=28,
                value=int(current_cfg.get("payroll_start_day", "5") or 5),
                step=1,
            )
            in_bank_prefix = p2.text_input(
                "은행 대량이체 통장 표기 매장명 (예: 분당그릴11월급여)",
                value=current_cfg.get("bank_transfer_prefix", selected_store),
            )
            in_tax_email = st.text_input(
                "세무사 기본 수신 이메일 (여러 곳이면 쉼표 , 로 구분)",
                value=current_cfg.get("tax_accountant_email", ""),
                placeholder="예: tax@example.com, bdgrill0524@gmail.com",
            )
            in_auto_payslip = st.checkbox(
                "정산 확정 시 '직원 개별 급여명세서 동시 발송' 체크박스 기본 활성화",
                value=(current_cfg.get("auto_send_payslip", "TRUE").upper() == "TRUE"),
            )

    # --------------------------------------------------------------------------
    # [탭 5] 텔레그램 알림 스위치
    # --------------------------------------------------------------------------
    with t_diag:
        st.markdown('<div class="section-title">텔레그램 자동 알림 수신 설정</div>', unsafe_allow_html=True)
        with st.container(border=True):
            in_tg_health = st.checkbox(
                "🏥 일일 보건증 만료(D-30) 대상자 텔레그램 자동 브리핑 (하루 1회)",
                value=(current_cfg.get("tg_alert_health", "TRUE").upper() == "TRUE"),
            )
            in_tg_contract = st.checkbox(
                "📝 직원 전자 근로계약서 서명 완료 즉시 텔레그램 알림",
                value=(current_cfg.get("tg_alert_contract", "TRUE").upper() == "TRUE"),
            )
            in_tg_payroll = st.checkbox(
                "💰 월별 급여 정산 확정 및 총 이체내역 텔레그램 보고",
                value=(current_cfg.get("tg_alert_payroll", "TRUE").upper() == "TRUE"),
            )

    st.write("")
    if st.form_submit_button("💾 모든 환경설정 구글 시트에 저장하기", type="primary", use_container_width=True):
        if not in_mgr_pin.strip() or not in_admin_pwd.strip():
            st.error("비밀번호는 비워둘 수 없습니다.")
        else:
            updated_cfg = {
                "manager_pin": in_mgr_pin.strip(),
                "admin_password": in_admin_pwd.strip(),
                "allow_mgr_payroll": "TRUE" if in_allow_mgr_payroll else "FALSE",
                "att_time_step_min": str(in_time_step),
                "health_alert_days": str(int(in_health_days)),
                "store_title": in_store_title.strip(),
                "owner_name": in_owner_name.strip(),
                "store_phone": in_store_phone.strip(),
                "store_address": in_store_addr.strip(),
                "default_work_start": in_w_start.strip(),
                "default_work_end": in_w_end.strip(),
                "default_break_min": str(int(in_break_m)),
                "default_job_desc": in_job_desc.strip(),
                "payroll_start_day": str(int(in_pay_day)),
                "tax_accountant_email": in_tax_email.strip(),
                "bank_transfer_prefix": in_bank_prefix.strip(),
                "auto_send_payslip": "TRUE" if in_auto_payslip else "FALSE",
                "tg_alert_health": "TRUE" if in_tg_health else "FALSE",
                "tg_alert_contract": "TRUE" if in_tg_contract else "FALSE",
                "tg_alert_payroll": "TRUE" if in_tg_payroll else "FALSE",
            }
            with st.spinner("구글 시트 '환경설정' 탭에 저장 중..."):
                save_settings_to_sheet(store_cfg["db_id"], updated_cfg)
                st.cache_data.clear()
                st.success("✅ 모든 환경설정이 구글 시트(`환경설정` 탭)에 안전하게 저장되었습니다!")
                st.rerun()

# ==============================================================================
# 3. 원클릭 외부 서비스(시트 · 텔레그램 · 이메일) 연동 상태 진단 패널
# ==============================================================================
st.divider()
st.markdown('<div class="section-title">📡 외부 연동 상태 실시간 점검 (원클릭 테스트)</div>', unsafe_allow_html=True)

d1, d2, d3 = st.columns(3)

with d1:
    with st.container(border=True):
        st.markdown("**1. 구글 시트 DB 연결**")
        st.caption("통합근태DB 및 시트 탭 읽기/쓰기 상태 확인")
        if st.button("시트 연결 테스트", use_container_width=True):
            try:
                gc = get_gspread_client()
                ss = gc.open_by_key(store_cfg["db_id"])
                tab_names = [ws.title for ws in ss.worksheets()]
                st.success(f"연결 정상! ({len(tab_names)}개 탭 확인)")
            except Exception as e:
                st.error(f"연결 실패: {e}")

with d2:
    with st.container(border=True):
        st.markdown("**2. 텔레그램 봇 알림**")
        st.caption("대표님 텔레그램으로 테스트 메시지 즉시 전송")
        if st.button("텔레그램 테스트 발송", use_container_width=True):
            bot_token = get_secret("TELEGRAM_BOT_TOKEN", "")
            chat_id = get_secret("TELEGRAM_CHAT_ID", "")
            if not bot_token or not chat_id:
                st.warning("Secrets에 텔레그램 토큰/ID가 없습니다.")
            else:
                try:
                    r = requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": f"✅ [{selected_store}] 환경설정 연동 테스트 메시지입니다."},
                        timeout=6,
                    )
                    if r.status_code == 200:
                        st.success("텔레그램 발송 성공!")
                    else:
                        st.error(f"발송 오류 (HTTP {r.status_code})")
                except Exception as e:
                    st.error(f"오류: {e}")

with d3:
    with st.container(border=True):
        st.markdown("**3. Apps Script 이메일**")
        st.caption("웹앱 서버를 통한 Gmail 발송 정상 작동 확인")
        if st.button("이메일 테스트 발송", use_container_width=True):
            webapp_url = get_secret("DRIVE_UPLOAD_WEBAPP_URL", "").strip()
            test_to = get_secret("SENDER_EMAIL", "bdgrill0524@gmail.com")
            if not webapp_url:
                st.warning("Secrets에 DRIVE_UPLOAD_WEBAPP_URL이 없습니다.")
            else:
                try:
                    payload = {
                        "action": "send_email",
                        "toEmail": test_to,
                        "subject": f"[{selected_store}] 시스템 이메일 연동 테스트",
                        "body": f"{selected_store} 통합 관리 시스템에서 발송한 테스트 메일입니다.",
                    }
                    res = requests.post(
                        webapp_url,
                        data=json.dumps(payload),
                        headers={"Content-Type": "text/plain; charset=utf-8"},
                        allow_redirects=True,
                        timeout=20,
                    )
                    if res.json().get("ok"):
                        st.success(f"발송 성공! ({test_to})")
                    else:
                        st.error(f"실패: {res.json().get('error')}")
                except Exception as e:
                    st.error(f"오류: {e}")
