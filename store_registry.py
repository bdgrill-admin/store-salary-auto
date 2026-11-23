"""
================================================================================
[파일명] store_registry.py
[역할] 다매장(분당그릴 · 감동한점 등) 목록 및 지점별 환경설정 통합 관리 공용 모듈
[주요 기능]
1. 기준 DB('분당그릴') 내 '매장목록' 탭에서 등록된 전체 지점의 시트/폴더 ID 로드
2. 각 지점 DB 내 '환경설정' 탭에서 공제율, 목표 인건비율, 비밀번호, 기본 근무조건 등 로드
3. 구글 시트 저장 시 앞자리 '0' 유실 방지를 위한 RAW 모드 저장 지원
4. 공동대표 및 매니저 수신 대상 분기 텔레그램 발송 지원 (dispatch_telegram_alert)
================================================================================
"""

import os
import re
import datetime
import requests
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

MASTER_DB_ID = "1-PcmKzW2NCU2AQinTE6Hz8LwXuO-8-X3yux2_C7VKw8"
DEFAULT_CONTRACT_FOLDER_ID = "1I91dAXDQNrW-tZMFJz0v0o7XAXlbxVnn"
CREDENTIALS_FILE = "credentials.json"

STORE_LIST_HEADERS = [
    "매장명", "통합근태DB_ID", "급여히스토리_ID", "매출관리_ID", "계약서폴더_ID", "매니저PIN", "사용여부"
]


def get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


@st.cache_resource
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


def get_default_stores() -> dict:
    return {
        "분당그릴": {
            "db_id": MASTER_DB_ID,
            "hist_id": get_secret("HIST_SHEET_BUNDANG", ""),
            "sales_id": get_secret("SALES_SHEET_BUNDANG", ""),
            "folder_id": DEFAULT_CONTRACT_FOLDER_ID,
            "manager_pin": get_secret("MANAGER_PIN_BUNDANG", "0524"),
            "tax_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
            "active": True,
        }
    }


@st.cache_data(ttl=30, show_spinner=False)
def load_all_stores(include_inactive: bool = False) -> dict:
    """기준 시트의 '매장목록' 탭에서 등록된 지점 정보를 불러옵니다."""
    stores = get_default_stores()
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(MASTER_DB_ID)
        titles = [ws.title.strip() for ws in ss.worksheets()]
        if "매장목록" not in titles:
            return stores

        ws = ss.worksheet("매장목록")
        rows = ws.get_all_values()
        if len(rows) < 2:
            return stores

        loaded = {}
        for r in rows[1:]:
            if len(r) < 2 or not r[0].strip() or not r[1].strip():
                continue
            s_name = r[0].strip()
            is_active = (r[6].strip().upper() != "FALSE") if len(r) > 6 and r[6].strip() else True
            if not include_inactive and not is_active:
                continue
            loaded[s_name] = {
                "db_id": r[1].strip(),
                "hist_id": r[2].strip() if len(r) > 2 else "",
                "sales_id": r[3].strip() if len(r) > 3 else "",
                "folder_id": (r[4].strip() if len(r) > 4 and r[4].strip() else DEFAULT_CONTRACT_FOLDER_ID),
                "manager_pin": (r[5].strip() if len(r) > 5 and r[5].strip() else "0524"),
                "tax_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
                "active": is_active,
            }
        if loaded:
            return loaded
    except Exception:
        pass
    return stores


def save_all_stores(stores_dict: dict):
    """기준 시트('분당그릴' DB)의 '매장목록' 탭에 전체 지점 정보를 RAW 모드로 저장합니다."""
    gc = get_gspread_client()
    ss = gc.open_by_key(MASTER_DB_ID)
    titles = [ws.title.strip() for ws in ss.worksheets()]
    if "매장목록" in titles:
        ws = ss.worksheet("매장목록")
        ws.clear()
    else:
        ws = ss.add_worksheet(title="매장목록", rows=50, cols=len(STORE_LIST_HEADERS))

    rows = [STORE_LIST_HEADERS]
    for s_name, info in stores_dict.items():
        if not s_name.strip() or not info.get("db_id", "").strip():
            continue
        rows.append([
            s_name.strip(),
            info.get("db_id", "").strip(),
            info.get("hist_id", "").strip(),
            info.get("sales_id", "").strip(),
            info.get("folder_id", DEFAULT_CONTRACT_FOLDER_ID).strip(),
            info.get("manager_pin", "0524").strip(),
            "TRUE" if info.get("active", True) else "FALSE",
        ])

    ws.update(range_name="A1", values=rows, value_input_option="RAW")


def get_default_store_settings(store_name: str = "분당그릴") -> dict:
    return {
        # 1. 보안 및 권한
        "manager_pin": get_secret("MANAGER_PIN_BUNDANG", "0524"),
        "admin_password": get_secret("ADMIN_PASSWORD", "0524"),
        "allow_mgr_payroll": "FALSE",
        # 2. 출퇴근 및 보건증 규칙
        "att_time_step_min": "10",
        "health_alert_days": "30",
        # 3. 전자 근로계약서 기본 템플릿
        "store_title": store_name,
        "owner_name": "이용석",
        "store_phone": "031-713-0342",
        "store_address": "경기도 성남시 분당구 미금일로 74번길 13-3 1층",
        "default_work_start": "17:00",
        "default_work_end": "22:00",
        "default_break_min": "30",
        "default_job_desc": "홀 서빙 및 주방 보조 등 매장 운영 전반",
        # 4. 급여 정산 · 공제율 · 목표 인건비율 설정
        "payroll_start_day": "5",
        "tax_accountant_email": get_secret("TAX_ACCOUNTANT_EMAIL", ""),
        "bank_transfer_prefix": store_name,
        "auto_send_payslip": "TRUE",
        "part_base_tax_rate": "0.9",
        "part_high_tax_rate": "3.3",
        "part_high_tax_threshold": "1000000",
        "target_labor_ratio": "28.0",
        # 5. 텔레그램 & 이메일 발송 기본값 및 알림 수신자 분기 스위치
        "telegram_bot_token": get_secret("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": get_secret("TELEGRAM_CHAT_ID", ""),
        "manager_telegram_chat_id": "",
        "drive_webapp_url": get_secret("DRIVE_UPLOAD_WEBAPP_URL", ""),
        "sender_email": get_secret("SENDER_EMAIL", "bdgrill0524@gmail.com"),
        "tg_target_health": "모두",
        "tg_target_contract": "모두",
        "tg_target_reg_change": "대표",
        "tg_target_wage_change": "대표",
        "tg_target_payroll": "대표",
        # 하위 호환용 기존 키 유지
        "tg_alert_health": "TRUE",
        "tg_alert_contract": "TRUE",
        "tg_alert_payroll": "TRUE",
        "tg_alert_reg_change": "TRUE",
        "tg_alert_wage_change": "TRUE",
        # 6. 실시간 계좌입금 · chak 지역상품권 확인 연동
        "payment_telegram_chat_id": "",
        "payment_webhook_secret": "bdgrill-pay-0524",
        "show_payment_board": "TRUE",
        "payment_biz_hours_only": "TRUE",
        "payment_biz_start": "11:00",
        "payment_biz_end": "23:00",
        "payment_excluded_senders": "이용석",
    }


@st.cache_data(ttl=25, show_spinner=False)
def load_store_settings(db_id: str, store_name: str = "분당그릴") -> dict:
    """해당 지점 DB의 '환경설정' 탭에서 설정값을 로드합니다."""
    cfg = get_default_store_settings(store_name)
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(db_id)
        titles = [ws.title.strip() for ws in ss.worksheets()]
        if "환경설정" not in titles:
            return cfg
        ws = ss.worksheet("환경설정")
        for r in ws.get_all_values()[1:]:
            if len(r) >= 2 and r[0].strip() and r[1].strip() != "":
                cfg[r[0].strip()] = r[1].strip()
    except Exception:
        pass
    return cfg


def save_store_settings(db_id: str, new_cfg: dict):
    """해당 지점 DB의 '환경설정' 탭에 RAW 모드로 영구 저장합니다."""
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

    ws.update(range_name="A1", values=rows, value_input_option="RAW")


def dispatch_telegram_alert(app_cfg: dict, target_key: str, message: str, default_target: str = "대표"):
    """
    수신 대상 설정('대표', '매니저', '모두', '끄기')에 따라
    공동대표(telegram_chat_id) 및 매니저(manager_telegram_chat_id)에게 텔레그램 알림을 분기 발송합니다.
    """
    bot_token = str(app_cfg.get("telegram_bot_token", "")).strip()
    if not bot_token:
        return

    mode = str(app_cfg.get(target_key, default_target)).strip()
    if mode.upper() == "FALSE" or mode == "끄기":
        return
    if mode.upper() == "TRUE":
        mode = default_target

    owner_ids = [x.strip() for x in re.split(r"[,;\s]+", str(app_cfg.get("telegram_chat_id", ""))) if x.strip()]
    mgr_ids = [x.strip() for x in re.split(r"[,;\s]+", str(app_cfg.get("manager_telegram_chat_id", ""))) if x.strip()]

    recipients = []
    if mode in ("대표", "대표만", "모두", "둘 다"):
        recipients.extend(owner_ids)
    if mode in ("매니저", "매니저만", "모두", "둘 다"):
        recipients.extend(mgr_ids)

    for chat_id in dict.fromkeys(recipients):
        try:
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message},
                timeout=4,
            )
        except Exception:
            pass
