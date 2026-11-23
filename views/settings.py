"""
================================================================================
[파일명] views/settings.py
[역할] 대표님/관리자 전용 '매장 통합 시스템 환경설정 & 다매장 관리' 페이지
[주요 기능]
1. 보안 · 권한: 매니저 PIN, 대표자 비밀번호, 매니저 급여정산 열람 허용 여부
2. 출퇴근 · 보건증 규칙: 출퇴근 시간 입력 단위(분), 보건증 만료 사전 경고일(D-Day)
3. 근로계약서 기본값: 사업체명, 대표자명, 매장 전화번호, 사업장 주소, 기본 근무조건
4. 급여 · 공제율 · 인건비 목표: 정산 기준일, 세무사 이메일, 파트타임 공제율/기준금액, 목표 인건비율(%)
5. 텔레그램 · 이메일 설정: 봇 토큰, 공동대표/매니저 채팅 ID(복수), 알림별 수신 대상 분기(대표/매니저/모두/끄기)
6. 다매장 · 지점 관리: 신규 지점(감동한점 등) 시트 ID 등록 및 수정, 외부 서비스 원클릭 진단
================================================================================
"""

import re
import json
import requests
import streamlit as st
from store_registry import (
    load_all_stores,
    save_all_stores,
    load_store_settings,
    save_store_settings,
    get_gspread_client,
    DEFAULT_CONTRACT_FOLDER_ID,
)
from ui_styles import apply_base_theme, render_section_banner

TG_TARGET_OPTIONS = ["대표", "매니저", "모두", "끄기"]


def normalize_tg_target(val: str, default: str = "대표") -> str:
    v = str(val).strip()
    if v.upper() == "FALSE" or v == "끄기":
        return "끄기"
    if v.upper() == "TRUE":
        return default
    if v in ("대표", "대표만"):
        return "대표"
    if v in ("매니저", "매니저만"):
        return "매니저"
    if v in ("모두", "둘 다"):
        return "모두"
    return default


apply_base_theme(max_width=1200)

all_stores_map = load_all_stores(include_inactive=True)
store_names = list(all_stores_map.keys())

h1, h2 = st.columns([3.2, 1.0], vertical_alignment="center")
with h1:
    st.markdown('<div class="app-title">⚙️ 시스템 환경설정</div>', unsafe_allow_html=True)
with h2:
    selected_store = st.selectbox("설정 매장", store_names, index=0, label_visibility="collapsed")

store_cfg = all_stores_map[selected_store]
current_cfg = load_store_settings(store_cfg["db_id"], selected_store)
active_admin_pwd = current_cfg.get("admin_password", "0524")

if not st.session_state.get("authenticated", False):
    st.write("")
    _, c_mid, _ = st.columns([1.1, 1.4, 1.1])
    with c_mid:
        with st.container(border=True):
            st.markdown("#### 🔒 대표자 / 관리자 전용")
            st.caption("매장 환경설정 변경 및 다매장 관리를 위해 관리자 비밀번호를 입력하세요.")
            pwd = st.text_input("관리자 비밀번호", type="password", placeholder="비밀번호 입력", label_visibility="collapsed")
            if st.button("확인", type="primary", use_container_width=True):
                if pwd == active_admin_pwd:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()

st.caption(f"💡 현재 선택된 **[{selected_store}]**의 설정은 구글 시트(`환경설정` 탭)에 영구 저장되며, 모든 화면에 즉시 반영됩니다.")

t_sec, t_att, t_con, t_pay, t_diag, t_stores = st.tabs([
    "🔐 보안 · 권한",
    "⏱️ 출퇴근 · 보건증 규칙",
    "📝 근로계약서 기본값",
    "💰 급여 · 공제율 · 인건비 목표",
    "📲 텔레그램 · 이메일 설정",
    "🏪 다매장 · 지점 관리",
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
                value=str(current_cfg.get("manager_pin", "0524")),
                max_chars=20,
            )
            in_admin_pwd = s2.text_input(
                "대표자/관리자 비밀번호 (급여 정산 · 환경설정)",
                value=str(current_cfg.get("admin_password", "0524")),
                max_chars=20,
            )
            in_allow_mgr_payroll = st.checkbox(
                "매니저에게도 '급여 정산' 페이지 열람 허용 (체크 해제 시 대표자 비밀번호만 허용)",
                value=(current_cfg.get("allow_mgr_payroll", "FALSE").upper() == "TRUE"),
            )

    # --------------------------------------------------------------------------
    # [탭 2] 출퇴근 입력 단위 및 보건증 만료 알림 기준
    # --------------------------------------------------------------------------
    with t_att:
        st.markdown('<div class="section-title">출퇴근 입력 단위 및 보건증 만료 사전 경고 기준일</div>', unsafe_allow_html=True)
        with st.container(border=True):
            a1, a2 = st.columns(2)
            cur_step_min = max(1, min(60, int(current_cfg.get("att_time_step_min", "10") or 10)))
            cur_health_days = max(7, min(90, int(current_cfg.get("health_alert_days", "30") or 30)))
            in_att_step_min = a1.number_input(
                "출퇴근 시간 입력 단위 (분, 예: 10분 단위 선택)",
                min_value=1,
                max_value=60,
                value=cur_step_min,
                step=1,
            )
            in_health_days = a2.number_input(
                "보건증 만료 사전 경고 기준일 (만료 며칠 전부터 알림 표시)",
                min_value=7,
                max_value=90,
                value=cur_health_days,
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
    # [탭 4] 급여 정산 · 공제율 · 인건비 목표 경고선 설정
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

        st.markdown('<div class="section-title">📊 파트타임 세금 공제율 및 인건비율 목표 경고선</div>', unsafe_allow_html=True)
        with st.container(border=True):
            r1, r2, r3 = st.columns(3)
            in_base_rate = r1.number_input(
                "파트타임 기본 공제율 (%)",
                min_value=0.0,
                max_value=20.0,
                value=float(current_cfg.get("part_base_tax_rate", "0.9") or 0.9),
                step=0.1,
                format="%.1f",
            )
            in_high_rate = r2.number_input(
                "기준금액 이상 상향 공제율 (%)",
                min_value=0.0,
                max_value=20.0,
                value=float(current_cfg.get("part_high_tax_rate", "3.3") or 3.3),
                step=0.1,
                format="%.1f",
            )
            in_high_thresh = r3.number_input(
                "상향 공제율 적용 기준금액 (세전 원)",
                min_value=0,
                max_value=10000000,
                value=int(float(current_cfg.get("part_high_tax_threshold", "1000000") or 1000000)),
                step=100000,
            )

            in_target_labor = st.number_input(
                "매출 대비 목표 인건비율 경고 기준선 (%) — 초과 시 급여정산·경영분석 화면에 경고 표시",
                min_value=5.0,
                max_value=80.0,
                value=float(current_cfg.get("target_labor_ratio", "28.0") or 28.0),
                step=0.5,
                format="%.1f",
            )

    # --------------------------------------------------------------------------
    # [탭 5] 텔레그램 & 이메일 발송 기본값 (공동대표 · 매니저 수신 분기)
    # --------------------------------------------------------------------------
    with t_diag:
        render_section_banner("📲 텔레그램 봇 토큰 및 수신자 채팅 ID", badge="알림 분기", accent="indigo")
        with st.container(border=True):
            in_tg_token = st.text_input(
                "텔레그램 봇 토큰 (TELEGRAM_BOT_TOKEN)",
                value=current_cfg.get("telegram_bot_token", ""),
                type="password",
            )
            id_c1, id_c2 = st.columns(2)
            in_tg_chat_id = id_c1.text_input(
                "대표 텔레그램 채팅 ID (공동대표 여러 명일 경우 쉼표 , 로 구분)",
                value=current_cfg.get("telegram_chat_id", ""),
                placeholder="예: 123456789, 987654321",
            )
            in_mgr_tg_chat_id = id_c2.text_input(
                "매니저 텔레그램 채팅 ID (여러 명일 경우 쉼표 , 로 구분)",
                value=current_cfg.get("manager_telegram_chat_id", ""),
                placeholder="예: 555666777",
            )
            st.caption("💡 각 수신자가 봇에게 먼저 `/start` 메시지를 보낸 뒤 발급된 숫자 채팅 ID를 입력하세요.")

            st.divider()
            st.markdown("**🔔 업무별 텔레그램 알림 수신 대상 지정** (`대표` / `매니저` / `모두` / `끄기`)")

            cur_t_health = normalize_tg_target(
                current_cfg.get("tg_target_health") or current_cfg.get("tg_alert_health", "모두"),
                default="모두",
            )
            cur_t_contract = normalize_tg_target(
                current_cfg.get("tg_target_contract") or current_cfg.get("tg_alert_contract", "모두"),
                default="모두",
            )
            cur_t_reg = normalize_tg_target(
                current_cfg.get("tg_target_reg_change") or current_cfg.get("tg_alert_reg_change", "대표"),
                default="대표",
            )
            cur_t_wage = normalize_tg_target(
                current_cfg.get("tg_target_wage_change") or current_cfg.get("tg_alert_wage_change", "대표"),
                default="대표",
            )
            cur_t_payroll = normalize_tg_target(
                current_cfg.get("tg_target_payroll") or current_cfg.get("tg_alert_payroll", "대표"),
                default="대표",
            )

            al1, al2, al3 = st.columns(3)
            in_target_health = al1.selectbox(
                "🏥 보건증 만료 대상자 알림",
                options=TG_TARGET_OPTIONS,
                index=TG_TARGET_OPTIONS.index(cur_t_health),
            )
            in_target_contract = al2.selectbox(
                "📝 전자 근로계약서 서명 완료",
                options=TG_TARGET_OPTIONS,
                index=TG_TARGET_OPTIONS.index(cur_t_contract),
            )
            in_target_payroll = al3.selectbox(
                "💰 월별 급여 정산 확정 보고",
                options=TG_TARGET_OPTIONS,
                index=TG_TARGET_OPTIONS.index(cur_t_payroll),
            )

            al4, al5, _ = st.columns(3)
            in_target_reg_change = al4.selectbox(
                "📌 정규직 특근·휴무 등록/수정/삭제",
                options=TG_TARGET_OPTIONS,
                index=TG_TARGET_OPTIONS.index(cur_t_reg),
            )
            in_target_wage_change = al5.selectbox(
                "💵 신규 파트타임 등록 · 시급 변경",
                options=TG_TARGET_OPTIONS,
                index=TG_TARGET_OPTIONS.index(cur_t_wage),
            )

        render_section_banner("📧 이메일 & 구글 드라이브 웹앱 발송 기본값", badge="Apps Script", accent="blue")
        with st.container(border=True):
            em_c1, em_c2 = st.columns([1.8, 1.2])
            in_webapp_url = em_c1.text_input(
                "Apps Script 웹앱 URL (DRIVE_UPLOAD_WEBAPP_URL)",
                value=current_cfg.get("drive_webapp_url", ""),
            )
            in_sender_email = em_c2.text_input(
                "발신 대표 이메일 / 테스트 수신 주소",
                value=current_cfg.get("sender_email", "bdgrill0524@gmail.com"),
            )

        render_section_banner("💳 실시간 계좌입금 · chak 지역상품권 자동 확인", badge="영업시간 · 잔액제거", accent="emerald")
        with st.container(border=True):
            pay_c1, pay_c2 = st.columns([1.5, 1.0])
            in_pay_tg_chat_id = pay_c1.text_input(
                "입금·chak 알림 전용 텔레그램 방/채팅 ID (그룹방은 음수 ID, 복수는 쉼표 구분)",
                value=current_cfg.get("payment_telegram_chat_id", ""),
                placeholder="예: -1001234567890",
            )
            in_pay_webhook_secret = pay_c2.text_input(
                "웹훅 보안키 (MacroDroid 전송 시 일치 확인용)",
                value=current_cfg.get("payment_webhook_secret", "bdgrill-pay-0524"),
                max_chars=50,
            )
            in_show_pay_board = st.checkbox(
                "출퇴근기록부 화면 상단에 '실시간 계좌입금 · chak 결제 확인' 패널 표시 (잔액·출금 제외, 당일 입금/결제만 노출)",
                value=(current_cfg.get("show_payment_board", "TRUE").upper() == "TRUE"),
            )
            in_pay_biz_only = st.checkbox(
                "영업시간 내 수신된 입금·chak 결제만 알림/기록 (영업시간 외 및 주말 브레이크타임 자동 무시)",
                value=(current_cfg.get("payment_biz_hours_only", "TRUE").upper() == "TRUE"),
            )
            wd_c1, wd_c2 = st.columns(2)
            in_pay_biz_start = wd_c1.text_input(
                "평일(월~금) 영업 시작 (HH:MM)",
                value=current_cfg.get("payment_biz_start", "16:00"),
                placeholder="16:00",
            )
            in_pay_biz_end = wd_c2.text_input(
                "평일(월~금) 영업 종료 (HH:MM)",
                value=current_cfg.get("payment_biz_end", "22:00"),
                placeholder="22:00",
            )
            wk_c1, wk_c2 = st.columns(2)
            in_pay_wknd_start = wk_c1.text_input(
                "주말(토·일) 영업 시작 (HH:MM)",
                value=current_cfg.get("payment_wknd_biz_start", "12:00"),
                placeholder="12:00",
            )
            in_pay_wknd_end = wk_c2.text_input(
                "주말(토·일) 영업 종료 (HH:MM)",
                value=current_cfg.get("payment_wknd_biz_end", "22:00"),
                placeholder="22:00",
            )
            brk_c1, brk_c2 = st.columns(2)
            in_pay_wknd_brk_start = brk_c1.text_input(
                "주말 브레이크 시작 (선택 · 비우면 없음)",
                value=current_cfg.get("payment_wknd_break_start", "15:00"),
                placeholder="15:00",
            )
            in_pay_wknd_brk_end = brk_c2.text_input(
                "주말 브레이크 종료 (선택 · 비우면 없음)",
                value=current_cfg.get("payment_wknd_break_end", "17:00"),
                placeholder="17:00",
            )
            in_pay_excluded_senders = st.text_input(
                "계좌입금 알림 제외 입금자명 (대표 본인 이체 등 제외, 여러 명이면 쉼표 , 로 구분)",
                value=current_cfg.get("payment_excluded_senders", "이용석"),
                placeholder="예: 이용석, 분당그릴",
            )
            st.caption(
                f"💡 MacroDroid 웹훅 전송 시 `dbId`에 현재 지점 시트 ID (`{store_cfg['db_id']}`)와 위 보안키를 입력하면 "
                "평일/주말 영업시간(브레이크타임 제외) 내 알림만 잔액 제거 후 시트(`입금확인로그`) 기록 및 전용 텔레그램 방으로 발송됩니다. "
                "(마감·브레이크 직후 결제까지 받으려면 종료시간에 10~20분 여유를 두셔도 됩니다.)"
            )

    st.write("")
    if st.form_submit_button(f"💾 [{selected_store}] 환경설정 저장하기", type="primary", use_container_width=True):
        if not in_mgr_pin.strip() or not in_admin_pwd.strip():
            st.error("비밀번호는 비워둘 수 없습니다.")
        else:
            updated_cfg = {
                "manager_pin": in_mgr_pin.strip(),
                "admin_password": in_admin_pwd.strip(),
                "allow_mgr_payroll": "TRUE" if in_allow_mgr_payroll else "FALSE",
                "att_time_step_min": str(int(in_att_step_min)),
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
                "part_base_tax_rate": f"{in_base_rate:g}",
                "part_high_tax_rate": f"{in_high_rate:g}",
                "part_high_tax_threshold": str(int(in_high_thresh)),
                "target_labor_ratio": f"{in_target_labor:.1f}",
                "telegram_bot_token": in_tg_token.strip(),
                "telegram_chat_id": in_tg_chat_id.strip(),
                "manager_telegram_chat_id": in_mgr_tg_chat_id.strip(),
                "drive_webapp_url": in_webapp_url.strip(),
                "sender_email": in_sender_email.strip(),
                "tg_target_health": in_target_health,
                "tg_target_contract": in_target_contract,
                "tg_target_payroll": in_target_payroll,
                "tg_target_reg_change": in_target_reg_change,
                "tg_target_wage_change": in_target_wage_change,
                # 기존 모듈 하위 호환 키 동기화
                "tg_alert_health": "FALSE" if in_target_health == "끄기" else "TRUE",
                "tg_alert_contract": "FALSE" if in_target_contract == "끄기" else "TRUE",
                "tg_alert_payroll": "FALSE" if in_target_payroll == "끄기" else "TRUE",
                "tg_alert_reg_change": "FALSE" if in_target_reg_change == "끄기" else "TRUE",
                "tg_alert_wage_change": "FALSE" if in_target_wage_change == "끄기" else "TRUE",
                # 실시간 계좌입금 · chak 확인 연동
                "payment_telegram_chat_id": in_pay_tg_chat_id.strip(),
                "payment_webhook_secret": in_pay_webhook_secret.strip(),
                "show_payment_board": "TRUE" if in_show_pay_board else "FALSE",
                "payment_biz_hours_only": "TRUE" if in_pay_biz_only else "FALSE",
                "payment_biz_start": in_pay_biz_start.strip() or "16:00",
                "payment_biz_end": in_pay_biz_end.strip() or "22:00",
                "payment_wknd_biz_start": in_pay_wknd_start.strip() or "12:00",
                "payment_wknd_biz_end": in_pay_wknd_end.strip() or "22:00",
                "payment_wknd_break_start": in_pay_wknd_brk_start.strip(),
                "payment_wknd_break_end": in_pay_wknd_brk_end.strip(),
                "payment_excluded_senders": in_pay_excluded_senders.strip(),
            }
            with st.spinner("구글 시트 '환경설정' 탭에 저장 중..."):
                save_store_settings(store_cfg["db_id"], updated_cfg)
                st.cache_data.clear()
                st.success(f"✅ [{selected_store}] 환경설정이 저장되었습니다!")
                st.rerun()

# ==============================================================================
# [탭 6] 다매장 · 지점 통합 관리
# ==============================================================================
with t_stores:
    st.markdown('<div class="section-title">🏪 등록된 매장 목록 및 시트 ID 관리</div>', unsafe_allow_html=True)
    st.caption("새로운 지점(예: 감동한점) 오픈 시 아래에서 시트 ID만 등록하면, 프로그램 전체 상단 '매장 선택' 메뉴에 즉시 추가됩니다.")

    for s_name, s_info in all_stores_map.items():
        with st.expander(f"🏢 {s_name} ({'운영중' if s_info.get('active', True) else '비활성'})", expanded=(s_name == selected_store)):
            with st.form(f"edit_store_form_{s_name}"):
                sc1, sc2 = st.columns([2.0, 1.0])
                ed_db_id = sc1.text_input("통합근태DB 시트 ID (필수)", value=s_info.get("db_id", ""))
                ed_pin = sc2.text_input("매니저 PIN", value=s_info.get("manager_pin", "0524"))

                sc3, sc4, sc5 = st.columns(3)
                ed_hist_id = sc3.text_input("급여히스토리 시트 ID", value=s_info.get("hist_id", ""))
                ed_sales_id = sc4.text_input("매출관리 시트 ID", value=s_info.get("sales_id", ""))
                ed_folder_id = sc5.text_input("계약서 드라이브 폴더 ID", value=s_info.get("folder_id", DEFAULT_CONTRACT_FOLDER_ID))

                ed_active = st.checkbox("매장 선택 메뉴에 표시 (활성화)", value=s_info.get("active", True))

                if st.form_submit_button(f"💾 [{s_name}] 지점 시트 정보 수정 저장", use_container_width=True):
                    if not ed_db_id.strip():
                        st.error("통합근태DB 시트 ID는 필수입니다.")
                    else:
                        all_stores_map[s_name] = {
                            "db_id": ed_db_id.strip(),
                            "hist_id": ed_hist_id.strip(),
                            "sales_id": ed_sales_id.strip(),
                            "folder_id": ed_folder_id.strip() or DEFAULT_CONTRACT_FOLDER_ID,
                            "manager_pin": ed_pin.strip() or "0524",
                            "active": ed_active,
                        }
                        save_all_stores(all_stores_map)
                        st.cache_data.clear()
                        st.success(f"✅ [{s_name}] 지점 정보가 저장되었습니다!")
                        st.rerun()

    st.markdown('<div class="section-title">➕ 신규 매장(2호점 등) 추가 등록</div>', unsafe_allow_html=True)
    with st.container(border=True):
        with st.form("add_new_store_form", clear_on_submit=True):
            nc1, nc2, nc3 = st.columns([1.2, 2.0, 1.0])
            new_s_name = nc1.text_input("신규 매장명*", placeholder="예: 감동한점")
            new_s_db = nc2.text_input("통합근태DB 시트 ID*", placeholder="구글 시트 URL의 /d/ 뒤 문자열")
            new_s_pin = nc3.text_input("초기 매니저 PIN", value="0524")

            nc4, nc5, nc6 = st.columns(3)
            new_s_hist = nc4.text_input("급여히스토리 시트 ID (선택)")
            new_s_sales = nc5.text_input("매출관리 시트 ID (선택)")
            new_s_folder = nc6.text_input("계약서 드라이브 폴더 ID", value=DEFAULT_CONTRACT_FOLDER_ID)

            if st.form_submit_button("➕ 신규 매장 등록하기", type="primary", use_container_width=True):
                clean_sn = new_s_name.strip()
                if not clean_sn or not new_s_db.strip():
                    st.error("신규 매장명과 통합근태DB 시트 ID를 입력해 주세요.")
                elif clean_sn in all_stores_map:
                    st.error("이미 등록된 매장명입니다.")
                else:
                    all_stores_map[clean_sn] = {
                        "db_id": new_s_db.strip(),
                        "hist_id": new_s_hist.strip(),
                        "sales_id": new_s_sales.strip(),
                        "folder_id": new_s_folder.strip() or DEFAULT_CONTRACT_FOLDER_ID,
                        "manager_pin": new_s_pin.strip() or "0524",
                        "active": True,
                    }
                    save_all_stores(all_stores_map)
                    st.cache_data.clear()
                    st.success(f"🎉 [{clean_sn}] 매장이 등록되었습니다! 상단 매장 선택 메뉴에서 바로 전환할 수 있습니다.")
                    st.rerun()

# ==============================================================================
# 3. 원클릭 외부 서비스 연동 상태 진단 패널
# ==============================================================================
st.divider()
render_section_banner(
    "📡 외부 연동 상태 실시간 점검 (원클릭 테스트)",
    badge="진단 도구",
    subtitle="구글 시트 · 텔레그램 · 이메일 · 입금 웹훅 연결을 한 번에 점검합니다",
    accent="amber",
)

d1, d2 = st.columns(2)

with d1:
    with st.container(border=True):
        st.markdown("**1. 구글 시트 DB 연결**")
        st.caption(f"[{selected_store}] 통합근태DB 연결 상태 확인")
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
        st.caption("등록된 대표·매니저 채팅 ID로 테스트 전송")
        if st.button("텔레그램 테스트 발송", use_container_width=True):
            bot_token = current_cfg.get("telegram_bot_token", "").strip()
            owner_ids = [x.strip() for x in re.split(r"[,;\s]+", str(current_cfg.get("telegram_chat_id", ""))) if x.strip()]
            mgr_ids = [x.strip() for x in re.split(r"[,;\s]+", str(current_cfg.get("manager_telegram_chat_id", ""))) if x.strip()]
            if not bot_token or (not owner_ids and not mgr_ids):
                st.warning("텔레그램 봇 토큰 또는 수신 채팅 ID가 비어 있습니다.")
            else:
                sent_logs = []
                for role_label, id_list in [("대표", owner_ids), ("매니저", mgr_ids)]:
                    for cid in dict.fromkeys(id_list):
                        try:
                            r = requests.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": cid, "text": f"✅ [{selected_store}] 환경설정 연동 테스트 메시지입니다. ({role_label} 수신)"},
                                timeout=6,
                            )
                            sent_logs.append(f"{role_label}({cid}): {'성공' if r.status_code == 200 else f'오류({r.status_code})'}")
                        except Exception as e:
                            sent_logs.append(f"{role_label}({cid}): 실패({e})")
                st.success(" / ".join(sent_logs))

d3, d4 = st.columns(2)

with d3:
    with st.container(border=True):
        st.markdown("**3. Apps Script 이메일**")
        st.caption("설정된 웹앱 URL·발신 이메일로 테스트 메일 발송")
        if st.button("이메일 테스트 발송", use_container_width=True):
            webapp_url = current_cfg.get("drive_webapp_url", "").strip()
            test_to = current_cfg.get("sender_email", "").strip()
            if not webapp_url or not test_to:
                st.warning("웹앱 URL 또는 이메일 주소가 비어 있습니다.")
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

with d4:
    with st.container(border=True):
        st.markdown("**4. 입금·chak 웹훅**")
        st.caption("테스트 입금 전송 (잔액 제거 · 시트 · 텔레그램 확인)")
        if st.button("입금 알림 테스트", use_container_width=True):
            webapp_url = current_cfg.get("drive_webapp_url", "").strip()
            secret_key = current_cfg.get("payment_webhook_secret", "").strip()
            if not webapp_url:
                st.warning("Apps Script 웹앱 URL이 비어 있습니다.")
            else:
                try:
                    payload = {
                        "action": "payment_alert",
                        "secretKey": secret_key,
                        "dbId": store_cfg["db_id"],
                        "storeName": selected_store,
                        "source": "우리은행",
                        "title": "우리WON뱅킹 입금 알림",
                        "body": "[우리은행] 1002-***-123456 입금 1,000원 테스트손님 잔액 99,999,999원",
                        "ignoreBusinessHours": "TRUE",
                    }
                    res = requests.post(
                        webapp_url,
                        data=json.dumps(payload),
                        headers={"Content-Type": "text/plain; charset=utf-8"},
                        allow_redirects=True,
                        timeout=20,
                    )
                    rj = res.json()
                    if rj.get("ok"):
                        st.success(f"성공! ({rj.get('category', '계좌입금')} / {rj.get('amount', 0):,}원)")
                    else:
                        st.error(f"실패: {rj.get('error')}")
                except Exception as e:
                    st.error(f"오류: {e}")
