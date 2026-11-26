"""
================================================================================
[파일명] settlement_utils.py
[역할] 매장 월말정산(고정비 · 관리비 · 말일결제 · 선결제 · 기타지출 · 고기원가)
       구글 시트 CRUD, 거래내역 엑셀 자동분류, 과거 정산 엑셀 이관, 엑셀 내보내기 모듈
[핵심 사이클 규칙]
  - 정산월 YY.MM 기준: 매출 · 고정비 · 관리비 · 변동매입(말일결제/선결제) · 기타지출은 해당 월(말일 마감)
  - 대응 인건비: 해당 월 5일 ~ 익월 4일 근무분 (익월 5일 입금)
    -> views/payroll.py의 급여히스토리 시트에는 end_date 기준 익월 탭(YY.MM + 1개월)으로 저장되므로
       기본적으로 next_ym(정산월) 탭을 자동 매칭한다.
================================================================================
"""

import io
import re
import datetime
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
import streamlit as st

from store_registry import get_gspread_client

# =========================================================================
# 1. 시트명 · 컬럼 스키마 · 기본 마스터 정의
# =========================================================================
TAB_ITEMS = "월말정산_항목"
TAB_ENTRIES = "월말정산_내역"
TAB_MISC = "월말정산_기타"
TAB_MEAT = "월말정산_고기원가"

ITEMS_HEADERS = [
    "항목명", "대분류", "결제방식", "부분합계그룹", "납부일메모", "키워드", "기본금액", "정렬순서", "사용여부"
]
ENTRIES_HEADERS = [
    "정산월", "항목명", "대분류", "결제방식", "부분합계그룹", "금액", "횟수", "결제완료", "메모"
]
MISC_HEADERS = [
    "정산월", "일자", "내용", "금액", "메모"
]
MEAT_HEADERS = [
    "정산월", "부위명", "kg단가", "총량(kg)"
]

# 부위별 1인분 판매 기준 (원가변동 계산용)
MEAT_MENU_SPECS = [
    {"부위명": "삼겹살", "별칭": ["삼겹", "삼겹살"], "중량g": 180, "판매가": 18000},
    {"부위명": "목살", "별칭": ["목살"], "중량g": 180, "판매가": 18000},
    {"부위명": "갈매기살", "별칭": ["갈매기", "갈매기살"], "중량g": 180, "판매가": 19000},
    {"부위명": "항정살", "별칭": ["항정", "항정살"], "중량g": 160, "판매가": 19000},
    {"부위명": "가브리살", "별칭": ["가브리", "가브리살"], "중량g": 180, "판매가": 19000},
    {"부위명": "꼬들살", "별칭": ["꼬들", "꼬들살"], "중량g": 180, "판매가": 18000},
    {"부위명": "늑간살", "별칭": ["늑간", "늑간살"], "중량g": 180, "판매가": 19000},
    {"부위명": "돼지갈비", "별칭": ["돼지갈비", "갈비"], "중량g": 300, "판매가": 20000},
]

MEAT_ALIAS_MAP = {}
for _spec in MEAT_MENU_SPECS:
    for _al in _spec["별칭"]:
        MEAT_ALIAS_MAP[_al] = _spec["부위명"]


def get_default_items_df() -> pd.DataFrame:
    """분당그릴 월말정산 기본 항목 마스터 (말일결제 9개 거래처 + 고정비 + 관리비 + 선결제/수시)."""
    rows = [
        # 1. 공통 고정비
        ("월세", "공통", "자동이체", "고정비", "매월", "월세,임대료", 3050000, 10, "TRUE"),
        ("티오더", "공통", "자동이체", "고정비", "매월", "티오더,torder", 257400, 20, "TRUE"),
        ("집진기", "공통", "자동이체", "고정비", "매월", "집진기", 308000, 30, "TRUE"),
        ("정수기", "공통", "자동이체", "고정비", "매월", "정수기,코웨이,SK매직,청호", 27900, 40, "TRUE"),
        ("인터넷", "공통", "자동이체", "고정비", "매월", "인터넷,KT,SK브로드,LG유플러스", 16500, 50, "TRUE"),
        ("유선전화", "공통", "자동이체", "고정비", "매월", "유선전화,전화요금", 9500, 60, "TRUE"),
        ("기장료", "공통", "자동이체", "고정비", "매월", "기장료,세무", 110000, 70, "TRUE"),
        ("화재보험", "공통", "자동이체", "고정비", "매월", "화재보험,손해보험", 102000, 80, "TRUE"),
        # 2. 관리비 · 세금
        ("4대보험료", "관리비", "고지납부", "관리비", "10일", "4대보험,국민연금,건강보험,고용보험,산재보험", 0, 110, "TRUE"),
        ("전기", "관리비", "고지납부", "관리비", "5일", "한국전력,한전,전기요금", 0, 120, "TRUE"),
        ("수도", "관리비", "고지납부", "관리비", "말일", "수도요금,상하수도", 0, 130, "TRUE"),
        ("가스", "관리비", "고지납부", "관리비", "26일", "도시가스,코원에너지,가스요금", 0, 140, "TRUE"),
        ("국세(원천세)", "관리비", "고지납부", "관리비", "10일", "국세,원천세,세무서", 0, 150, "TRUE"),
        ("지방세", "관리비", "고지납부", "관리비", "10일", "지방세,지방소득세,위택스", 0, 160, "TRUE"),
        ("주민세", "관리비", "고지납부", "관리비", "수시", "주민세,등록면허세", 0, 170, "TRUE"),
        # 3. 변동매입 - 말일결제 (초록색 9곳)
        ("몬트락", "변동매입", "말일결제", "고기", "말일", "몬트락", 0, 210, "TRUE"),
        ("하람", "변동매입", "말일결제", "고기", "말일", "하람", 0, 220, "TRUE"),
        ("도원에프엔비", "변동매입", "말일결제", "고기", "말일", "도원에프엔비,도원F&B,도원", 0, 230, "TRUE"),
        ("식자재", "변동매입", "말일결제", "식자재", "말일", "식자재,CJ프레시,대상,동원홈푸드", 0, 240, "TRUE"),
        ("주류", "변동매입", "말일결제", "주류음료", "말일", "주류,종합주류", 0, 250, "TRUE"),
        ("음료", "변동매입", "말일결제", "주류음료", "말일", "음료,코카콜라,롯데칠성", 0, 260, "TRUE"),
        ("숯(비제이무역)", "변동매입", "말일결제", "기타매입", "말일", "비제이무역,비제이,숯", 0, 270, "TRUE"),
        ("반찬(단지)", "변동매입", "말일결제", "기타매입", "말일", "단지,반찬", 0, 280, "TRUE"),
        ("세탁비(이용실)", "변동매입", "말일결제", "기타매입", "말일", "이용실,세탁", 0, 290, "TRUE"),
        # 4. 변동매입 - 선결제 / 수시결제
        ("선결제[하람]", "변동매입", "선결제/수시", "고기", "수시", "선결제하람", 0, 310, "TRUE"),
        ("선결제[도원]", "변동매입", "선결제/수시", "고기", "수시", "선결제도원", 0, 320, "TRUE"),
        ("파김치(네이버)", "변동매입", "선결제/수시", "기타매입", "수시", "파김치", 0, 330, "TRUE"),
        ("묵은지(네이버)", "변동매입", "선결제/수시", "기타매입", "수시", "묵은지", 0, 340, "TRUE"),
        ("국수사리(네이버)", "변동매입", "선결제/수시", "기타매입", "수시", "국수사리,국수", 0, 350, "TRUE"),
        ("씨앗젓갈(네이버)", "변동매입", "선결제/수시", "기타매입", "수시", "씨앗젓갈,젓갈", 0, 360, "TRUE"),
        ("동치미(이정)", "변동매입", "선결제/수시", "기타매입", "수시", "이정,동치미", 0, 370, "TRUE"),
        ("맬젓(현풍자)", "변동매입", "선결제/수시", "기타매입", "수시", "현풍자,맬젓", 0, 380, "TRUE"),
        ("칼갈이(이융래)", "변동매입", "선결제/수시", "기타매입", "수시", "이융래,칼갈이", 0, 390, "TRUE"),
        ("카페트(이상현)", "변동매입", "선결제/수시", "기타매입", "수시", "이상현,카페트", 0, 400, "TRUE"),
        ("헛깨(아임드링크)", "변동매입", "선결제/수시", "기타매입", "수시", "아임드링크,헛깨,헛개", 0, 410, "TRUE"),
        ("불닭소스(박도준)", "변동매입", "선결제/수시", "기타매입", "수시", "박도준,불닭소스", 0, 420, "TRUE"),
        ("앞치마(쿠팡)", "변동매입", "선결제/수시", "기타매입", "수시", "앞치마", 0, 430, "TRUE"),
        ("미트페이퍼(쿠팡)", "변동매입", "선결제/수시", "기타매입", "수시", "미트페이퍼", 0, 440, "TRUE"),
        ("쿠킹호일(쿠팡)", "변동매입", "선결제/수시", "기타매입", "수시", "쿠킹호일,호일", 0, 450, "TRUE"),
        ("불판코팅", "변동매입", "선결제/수시", "기타매입", "수시", "불판코팅", 0, 460, "TRUE"),
        ("다이소(아성다)", "변동매입", "선결제/수시", "기타매입", "수시", "아성다,다이소", 0, 470, "TRUE"),
        ("CU(씨유)", "변동매입", "선결제/수시", "기타매입", "수시", "씨유,CU,BGF리테일", 0, 480, "TRUE"),
        ("모두의할인점", "변동매입", "선결제/수시", "기타매입", "수시", "모두의할인점", 0, 490, "TRUE"),
        ("도깨비식자재", "변동매입", "선결제/수시", "기타매입", "수시", "도깨비식자재,도깨비", 0, 500, "TRUE"),
        ("야채네 농업회사", "변동매입", "선결제/수시", "기타매입", "수시", "야채네", 0, 510, "TRUE"),
        ("판공비", "변동매입", "선결제/수시", "기타매입", "수시", "판공비", 300000, 520, "TRUE"),
        ("광고비(와이드어)", "변동매입", "선결제/수시", "기타매입", "수시", "와이드어", 0, 530, "TRUE"),
        ("광고비(네이버)", "변동매입", "선결제/수시", "기타매입", "수시", "네이버광고,네이버페이광고", 0, 540, "TRUE"),
        ("광고비(주선호)", "변동매입", "선결제/수시", "기타매입", "수시", "주선호", 0, 550, "TRUE"),
        ("고기파지(백남호)", "변동매입", "선결제/수시", "기타매입", "수시", "백남호,고기파지", 0, 560, "TRUE"),
    ]
    return pd.DataFrame(rows, columns=ITEMS_HEADERS)


# =========================================================================
# 2. 유틸리티 (숫자 / 정산월 변환 / 인건비 사이클 매칭)
# =========================================================================
def clean_int(val) -> int:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none"):
        return 0
    s = re.sub(r"[^0-9\-]", "", s.split(".")[0] if re.match(r"^-?\d+\.\d+$", s.replace(",", "")) else s)
    if not s or s == "-":
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def clean_float(val) -> float:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return 0.0
    s = re.sub(r"[^0-9.\-]", "", str(val).strip())
    if not s or s in ("-", "."):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_ym(val: str) -> str:
    s = str(val).strip()
    m = re.match(r"^(?:20)?(\d{2})[-./년\s]+(\d{1,2})월?$", s)
    if m:
        return f"{m.group(1)}.{int(m.group(2)):02d}"
    return s


def next_ym(ym: str) -> str:
    """정산월 YY.MM의 익월 YY.MM 반환 (예: '26.11' -> '26.12', '26.12' -> '27.01')."""
    norm = normalize_ym(ym)
    m = re.match(r"^(\d{2})\.(\d{2})$", norm)
    if not m:
        return norm
    yy, mm = int(m.group(1)), int(m.group(2))
    if mm == 12:
        return f"{yy + 1:02d}.01"
    return f"{yy:02d}.{mm + 1:02d}"


def prev_ym(ym: str) -> str:
    """정산월 YY.MM의 전월 YY.MM 반환 (예: '26.01' -> '25.12')."""
    norm = normalize_ym(ym)
    m = re.match(r"^(\d{2})\.(\d{2})$", norm)
    if not m:
        return norm
    yy, mm = int(m.group(1)), int(m.group(2))
    if mm == 1:
        return f"{yy - 1:02d}.12"
    return f"{yy:02d}.{mm - 1:02d}"


def ym_to_kor(ym: str) -> str:
    norm = normalize_ym(ym)
    m = re.match(r"^(\d{2})\.(\d{2})$", norm)
    if not m:
        return norm
    return f"20{m.group(1)}년 {int(m.group(2))}월"


def list_selectable_months(existing_months: list[str], today: datetime.date | None = None) -> list[str]:
    """최근 18개월 + 기존 저장된 정산월을 내림차순(최신순)으로 반환."""
    if today is None:
        today = datetime.date.today()
    s = set()
    for ym in existing_months:
        n = normalize_ym(ym)
        if re.match(r"^\d{2}\.\d{2}$", n):
            s.add(n)
    y, m = today.year, today.month
    for _ in range(18):
        s.add(f"{y % 100:02d}.{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return sorted(s, reverse=True)


# =========================================================================
# 3. 구글 스프레드시트 CRUD (월말정산 4개 탭 + 매출관리 + 급여히스토리)
# =========================================================================
def _rows_to_df(rows: list, headers: list[str]) -> pd.DataFrame:
    if not rows or len(rows) < 2:
        return pd.DataFrame(columns=headers)
    raw_h = [str(c).strip() for c in rows[0]]
    data = []
    for r in rows[1:]:
        if not any(str(x).strip() for x in r):
            continue
        rec = {}
        for idx, h in enumerate(headers):
            if h in raw_h:
                ci = raw_h.index(h)
                rec[h] = r[ci] if ci < len(r) else ""
            else:
                rec[h] = r[idx] if idx < len(r) else ""
        data.append(rec)
    return pd.DataFrame(data, columns=headers)


@st.cache_data(ttl=180, show_spinner=False)
def load_settlement_bundle(db_id: str) -> dict:
    """지점 DB에서 월말정산 4개 탭을 한 번의 batch_get으로 일괄 로드."""
    result = {
        "items": get_default_items_df(),
        "entries": pd.DataFrame(columns=ENTRIES_HEADERS),
        "misc": pd.DataFrame(columns=MISC_HEADERS),
        "meat": pd.DataFrame(columns=MEAT_HEADERS),
        "has_tabs": False,
    }
    if not db_id:
        return result

    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(db_id)
        existing_titles = {ws.title.strip(): ws.title for ws in ss.worksheets()}
        targets = [
            (TAB_ITEMS, "items", ITEMS_HEADERS),
            (TAB_ENTRIES, "entries", ENTRIES_HEADERS),
            (TAB_MISC, "misc", MISC_HEADERS),
            (TAB_MEAT, "meat", MEAT_HEADERS),
        ]
        ranges = []
        active_targets = []
        for tab, key, headers in targets:
            if tab in existing_titles:
                ranges.append(f"'{existing_titles[tab]}'!A:Z")
                active_targets.append((tab, key, headers))

        if not ranges:
            return result

        result["has_tabs"] = True
        res = ss.values_batch_get(ranges)
        vrs = res.get("valueRanges", [])
        for (_, key, headers), vr in zip(active_targets, vrs):
            df = _rows_to_df(vr.get("values", []), headers)
            if key == "items":
                if not df.empty:
                    df["기본금액"] = df["기본금액"].apply(clean_int)
                    df["정렬순서"] = df["정렬순서"].apply(clean_int)
                    df["사용여부"] = df["사용여부"].astype(str).str.upper().replace({"": "TRUE"})
                    result["items"] = df
            elif key == "entries":
                if not df.empty:
                    df["정산월"] = df["정산월"].apply(normalize_ym)
                    df["금액"] = df["금액"].apply(clean_int)
                    df["횟수"] = df["횟수"].apply(clean_int)
                    df["결제완료"] = df["결제완료"].astype(str).str.upper() == "TRUE"
                result["entries"] = df
            elif key == "misc":
                if not df.empty:
                    df["정산월"] = df["정산월"].apply(normalize_ym)
                    df["금액"] = df["금액"].apply(clean_int)
                result["misc"] = df
            elif key == "meat":
                if not df.empty:
                    df["정산월"] = df["정산월"].apply(normalize_ym)
                    df["kg단가"] = df["kg단가"].apply(clean_int)
                    df["총량(kg)"] = df["총량(kg)"].apply(clean_float)
                result["meat"] = df
    except Exception:
        pass

    return result


def _ensure_and_write_tab(ss, tab_name: str, headers: list[str], df: pd.DataFrame):
    titles = [ws.title.strip() for ws in ss.worksheets()]
    rows = [headers]
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            row_vals = []
            for h in headers:
                v = r.get(h, "")
                if isinstance(v, bool):
                    row_vals.append("TRUE" if v else "FALSE")
                elif pd.isna(v):
                    row_vals.append("")
                else:
                    row_vals.append(str(v))
            rows.append(row_vals)

    if tab_name in titles:
        ws = ss.worksheet(tab_name)
        ws.clear()
        if ws.row_count < len(rows) + 20:
            ws.resize(rows=len(rows) + 50, cols=max(len(headers), ws.col_count))
    else:
        ws = ss.add_worksheet(title=tab_name, rows=max(len(rows) + 50, 200), cols=len(headers))

    ws.update(range_name="A1", values=rows, value_input_option="RAW")


def save_settlement_items_master(db_id: str, df_items: pd.DataFrame):
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    out = df_items.copy()
    for h in ITEMS_HEADERS:
        if h not in out.columns:
            out[h] = ""
    out = out[out["항목명"].astype(str).str.strip() != ""].copy()
    out["기본금액"] = out["기본금액"].apply(clean_int)
    out["정렬순서"] = out["정렬순서"].apply(clean_int)
    out = out.sort_values(["정렬순서", "항목명"]).reset_index(drop=True)
    _ensure_and_write_tab(ss, TAB_ITEMS, ITEMS_HEADERS, out[ITEMS_HEADERS])


def save_month_settlement(
    db_id: str,
    ym: str,
    df_entries_month: pd.DataFrame,
    df_misc_month: pd.DataFrame,
    df_meat_month: pd.DataFrame,
):
    """특정 정산월(ym) 데이터만 교체 저장 (타 월 데이터 보존)."""
    ym = normalize_ym(ym)
    bundle = load_settlement_bundle(db_id)
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)

    # 1) 항목 마스터가 아직 시트에 없다면 기본 마스터도 함께 생성
    if not bundle["has_tabs"]:
        _ensure_and_write_tab(ss, TAB_ITEMS, ITEMS_HEADERS, bundle["items"])

    # 2) 월말정산_내역 병합
    old_e = bundle["entries"]
    old_e = old_e[old_e["정산월"] != ym].copy() if not old_e.empty else pd.DataFrame(columns=ENTRIES_HEADERS)
    new_e = df_entries_month.copy()
    new_e["정산월"] = ym
    for h in ENTRIES_HEADERS:
        if h not in new_e.columns:
            new_e[h] = ""
    new_e = new_e[new_e["항목명"].astype(str).str.strip() != ""].copy()
    new_e["금액"] = new_e["금액"].apply(clean_int)
    new_e["횟수"] = new_e["횟수"].apply(clean_int)
    new_e["결제완료"] = new_e["결제완료"].astype(bool)
    merged_e = pd.concat([old_e, new_e[ENTRIES_HEADERS]], ignore_index=True)
    merged_e = merged_e.sort_values(["정산월", "대분류", "항목명"]).reset_index(drop=True)
    _ensure_and_write_tab(ss, TAB_ENTRIES, ENTRIES_HEADERS, merged_e)

    # 3) 월말정산_기타 병합
    old_m = bundle["misc"]
    old_m = old_m[old_m["정산월"] != ym].copy() if not old_m.empty else pd.DataFrame(columns=MISC_HEADERS)
    new_m = df_misc_month.copy()
    new_m["정산월"] = ym
    for h in MISC_HEADERS:
        if h not in new_m.columns:
            new_m[h] = ""
    new_m = new_m[
        (new_m["내용"].astype(str).str.strip() != "") | (new_m["금액"].apply(clean_int) != 0)
    ].copy()
    new_m["금액"] = new_m["금액"].apply(clean_int)
    merged_m = pd.concat([old_m, new_m[MISC_HEADERS]], ignore_index=True)
    merged_m = merged_m.sort_values(["정산월", "일자"]).reset_index(drop=True)
    _ensure_and_write_tab(ss, TAB_MISC, MISC_HEADERS, merged_m)

    # 4) 월말정산_고기원가 병합
    old_k = bundle["meat"]
    old_k = old_k[old_k["정산월"] != ym].copy() if not old_k.empty else pd.DataFrame(columns=MEAT_HEADERS)
    new_k = df_meat_month.copy()
    new_k["정산월"] = ym
    for h in MEAT_HEADERS:
        if h not in new_k.columns:
            new_k[h] = ""
    new_k = new_k[new_k["부위명"].astype(str).str.strip() != ""].copy()
    new_k["kg단가"] = new_k["kg단가"].apply(clean_int)
    new_k["총량(kg)"] = new_k["총량(kg)"].apply(clean_float)
    merged_k = pd.concat([old_k, new_k[MEAT_HEADERS]], ignore_index=True)
    merged_k = merged_k.sort_values(["정산월", "부위명"]).reset_index(drop=True)
    _ensure_and_write_tab(ss, TAB_MEAT, MEAT_HEADERS, merged_k)


def save_bulk_imported_settlement(
    db_id: str,
    df_entries_all: pd.DataFrame,
    df_misc_all: pd.DataFrame,
    df_meat_all: pd.DataFrame,
    sales_id: str = "",
    sales_dict: dict | None = None,
    overwrite_existing: bool = True,
):
    """과거 엑셀 일괄 이관 저장 (기존 타 월 보존, 동일 월은 overwrite_existing 정책 적용)."""
    bundle = load_settlement_bundle(db_id)
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)

    if not bundle["has_tabs"]:
        _ensure_and_write_tab(ss, TAB_ITEMS, ITEMS_HEADERS, bundle["items"])

    imp_months = set(df_entries_all["정산월"].unique().tolist()) if not df_entries_all.empty else set()

    def _merge_df(old_df, new_df, headers):
        if old_df is None or old_df.empty:
            return new_df[headers].copy() if not new_df.empty else pd.DataFrame(columns=headers)
        if overwrite_existing:
            kept = old_df[~old_df["정산월"].isin(imp_months)].copy()
            return pd.concat([kept, new_df[headers]], ignore_index=True)
        existing_ms = set(old_df["정산월"].unique().tolist())
        add_new = new_df[~new_df["정산월"].isin(existing_ms)].copy()
        return pd.concat([old_df, add_new[headers]], ignore_index=True)

    m_e = _merge_df(bundle["entries"], df_entries_all, ENTRIES_HEADERS)
    m_m = _merge_df(bundle["misc"], df_misc_all, MISC_HEADERS)
    m_k = _merge_df(bundle["meat"], df_meat_all, MEAT_HEADERS)

    _ensure_and_write_tab(ss, TAB_ENTRIES, ENTRIES_HEADERS, m_e)
    _ensure_and_write_tab(ss, TAB_MISC, MISC_HEADERS, m_m)
    _ensure_and_write_tab(ss, TAB_MEAT, MEAT_HEADERS, m_k)

    # 매출관리 시트에도 일괄 반영 (비어있거나 덮어쓰기 옵션일 때)
    if sales_id and sales_dict:
        existing_sales = load_sales_map(sales_id)
        updated_sales = dict(existing_sales)
        for ym, amt in sales_dict.items():
            if amt > 0 and (overwrite_existing or ym not in updated_sales or updated_sales[ym] == 0):
                updated_sales[ym] = int(amt)
        _write_sales_map(sales_id, updated_sales)


@st.cache_data(ttl=180, show_spinner=False)
def load_sales_map(sales_id: str) -> dict:
    """매출관리 시트('월별매출')에서 {정산월: 총매출} 딕셔너리 로드."""
    if not sales_id:
        return {}
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(sales_id)
        try:
            rows = ss.values_get("'월별매출'!A:C").get("values", [])
        except Exception:
            rows = ss.worksheets()[0].get_all_values()
        if len(rows) < 2:
            return {}
        headers = [str(c).strip() for c in rows[0]]
        ym_idx = headers.index("정산월") if "정산월" in headers else 0
        val_idx = headers.index("총매출") if "총매출" in headers else 1
        out = {}
        for r in rows[1:]:
            if len(r) <= max(ym_idx, val_idx):
                continue
            ym = normalize_ym(r[ym_idx])
            v = clean_int(r[val_idx])
            if re.match(r"^\d{2}\.\d{2}$", ym):
                out[ym] = v
        return out
    except Exception:
        return {}


def _write_sales_map(sales_id: str, sales_map: dict):
    if not sales_id:
        return
    gc = get_gspread_client()
    ss = gc.open_by_key(sales_id)
    titles = [ws.title.strip() for ws in ss.worksheets()]
    if "월별매출" in titles:
        ws = ss.worksheet("월별매출")
        ws.clear()
    else:
        ws = ss.add_worksheet(title="월별매출", rows=100, cols=3)
    rows = [["정산월", "총매출"]]
    for ym in sorted(sales_map.keys()):
        rows.append([ym, str(int(sales_map[ym]))])
    ws.update(range_name="A1", values=rows, value_input_option="RAW")


def upsert_month_sales(sales_id: str, ym: str, amount: int):
    if not sales_id:
        return
    ym = normalize_ym(ym)
    cur = load_sales_map(sales_id)
    cur[ym] = int(amount)
    _write_sales_map(sales_id, cur)


def _parse_payroll_grid(rows: list) -> dict:
    """급여히스토리 YY.MM 탭 그리드에서 정규직/파트타임 총인건비 파싱."""
    reg_tot = 0
    part_tot = 0
    if not rows:
        return {"정규직": 0, "파트타임": 0, "총인건비": 0}

    mode = None
    col_map = {}
    for r in rows:
        vals = [str(x).strip() for x in r]
        if not any(vals):
            mode = None
            col_map = {}
            continue
        if "계약급여" in vals or "입금급여" in vals:
            mode = "정규직"
            col_map = {v: i for i, v in enumerate(vals) if v}
            continue
        if "시급" in vals and ("최종급여" in vals or "총급여" in vals):
            mode = "파트타임"
            col_map = {v: i for i, v in enumerate(vals) if v}
            continue
        if not mode:
            continue
        name = vals[col_map.get("이름", 0)] if col_map.get("이름", 0) < len(vals) else ""
        if not name or name in ("합계", "총계", "소계"):
            continue
        if mode == "정규직":
            idx = col_map.get("입금급여", col_map.get("계산급여", -1))
            if 0 <= idx < len(vals):
                reg_tot += clean_int(vals[idx])
        elif mode == "파트타임":
            idx = col_map.get("최종급여", col_map.get("총급여", -1))
            if 0 <= idx < len(vals):
                part_tot += clean_int(vals[idx])

    return {"정규직": reg_tot, "파트타임": part_tot, "총인건비": reg_tot + part_tot}


@st.cache_data(ttl=180, show_spinner=False)
def load_payroll_history_map(hist_id: str) -> dict:
    """급여히스토리 시트에서 {탭정산월(YY.MM): {정규직, 파트타임, 총인건비}} 로드."""
    if not hist_id:
        return {}
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(hist_id)
        worksheets = ss.worksheets()
    except Exception:
        return {}

    past_title = None
    month_tabs = []
    for ws in worksheets:
        st_title = ws.title.strip()
        if st_title == "과거요약":
            past_title = ws.title
            continue
        nm = normalize_ym(st_title)
        if re.match(r"^\d{2}\.\d{2}$", nm):
            month_tabs.append((ws.title, nm))

    batch_titles = ([past_title] if past_title else []) + [t for t, _ in month_tabs]
    if not batch_titles:
        return {}

    values_map = {}
    try:
        res = ss.values_batch_get([f"'{t}'!A:Z" for t in batch_titles])
        for t, vr in zip(batch_titles, res.get("valueRanges", [])):
            values_map[t] = vr.get("values", [])
    except Exception:
        return {}

    out = {}
    if past_title:
        for r in values_map.get(past_title, [])[1:]:
            if len(r) < 2:
                continue
            ym = normalize_ym(r[0])
            tot = clean_int(r[1])
            if re.match(r"^\d{2}\.\d{2}$", ym) and tot > 0:
                out[ym] = {"정규직": 0, "파트타임": 0, "총인건비": tot}

    for raw_t, nm in month_tabs:
        parsed = _parse_payroll_grid(values_map.get(raw_t, []))
        if parsed["총인건비"] > 0:
            out[nm] = parsed

    return out


# =========================================================================
# 4. 과거 엑셀(★월말정산내역_분당그릴★.xlsx) 일괄 파서
# =========================================================================
def _canonical_item_meta(raw_name: str, section_hint: str, master_df: pd.DataFrame) -> tuple[str, str, str, str]:
    """과거 엑셀 항목명을 표준 마스터 항목명 및 (대분류, 결제방식, 부분합계그룹)으로 정규화."""
    name = str(raw_name).strip()
    # 괄호/공백 제거 정규화 비교
    norm = re.sub(r"\s+", "", name)
    alias_table = {
        "4대보(10일)": "4대보험료",
        "4대보험료": "4대보험료",
        "전기(5일)": "전기",
        "수도(말일)": "수도",
        "가스(26일)": "가스",
        "원천세": "국세(원천세)",
        "국세": "국세(원천세)",
        "지방소득세": "지방세",
        "종합소득세": "지방세",
        "등록면허세": "주민세",
        "숯": "숯(비제이무역)",
        "동치미": "동치미(이정)",
        "김치류": "파김치(네이버)",
        "파김치": "파김치(네이버)",
        "묵은지": "묵은지(네이버)",
        "국수사리": "국수사리(네이버)",
        "씨앗젓갈": "씨앗젓갈(네이버)",
        "헛깨농축액": "헛깨(아임드링크)",
        "불닭소스": "불닭소스(박도준)",
        "앞치마": "앞치마(쿠팡)",
        "미트페이퍼": "미트페이퍼(쿠팡)",
        "쿠킹호일": "쿠킹호일(쿠팡)",
        "칼갈이": "칼갈이(이융래)",
        "카페트": "카페트(이상현)",
        "세탁비": "세탁비(이용실)",
        "다이소": "다이소(아성다)",
        "CU": "CU(씨유)",
        "야채네": "야채네 농업회사",
        "네이버광고비": "광고비(네이버)",
    }
    mapped_name = alias_table.get(name, alias_table.get(norm, name))

    match = master_df[master_df["항목명"] == mapped_name]
    if not match.empty:
        r = match.iloc[0]
        return mapped_name, str(r["대분류"]), str(r["결제방식"]), str(r["부분합계그룹"])

    # 마스터에 없는 항목은 섹션 힌트로 분류
    if section_hint == "공통":
        return mapped_name, "공통", "자동이체", "고정비"
    if section_hint == "관리비":
        return mapped_name, "관리비", "고지납부", "관리비"
    return mapped_name, "변동매입", "선결제/수시", "기타매입"


def parse_legacy_settlement_excel(file_bytes: bytes, master_df: pd.DataFrame | None = None):
    """★월말정산내역_분당그릴★.xlsx 형식의 과거 정산 엑셀을 전체 파싱."""
    if master_df is None or master_df.empty:
        master_df = get_default_items_df()

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    entry_rows = []
    misc_rows = []
    meat_rows = []
    sales_dict = {}
    logs = []

    for sname in wb.sheetnames:
        ym = normalize_ym(sname)
        if not re.match(r"^\d{2}\.\d{2}$", ym):
            continue
        ws = wb[sname]
        max_r = ws.max_row

        # 1) 매출 (A2, 단 26.05처럼 A4에 조정매출이 있으면 우선 확인하되 기본 A2 사용)
        sales_val = clean_int(ws["A2"].value)
        if sales_val > 0:
            sales_dict[ym] = sales_val

        # 2) B/C열: 공통 & 관리비 등
        in_mgmt = False
        for r in range(2, max_r + 1):
            label = ws.cell(r, 2).value  # B열
            val = ws.cell(r, 3).value    # C열
            if label is None:
                continue
            label_s = str(label).strip()
            if not label_s:
                continue
            if "관리비" in label_s:
                in_mgmt = True
                continue
            amt = clean_int(val)
            sec = "관리비" if in_mgmt else "공통"
            cname, cat, pay_type, grp = _canonical_item_meta(label_s, sec, master_df)
            entry_rows.append({
                "정산월": ym,
                "항목명": cname,
                "대분류": cat,
                "결제방식": pay_type,
                "부분합계그룹": grp,
                "금액": amt,
                "횟수": 1 if amt > 0 else 0,
                "결제완료": True,
                "메모": "",
            })

        # 3) E/F/G열: 변동매입 + 횟수
        for r in range(2, max_r + 1):
            label = ws.cell(r, 5).value  # E열
            val = ws.cell(r, 6).value    # F열
            cnt = ws.cell(r, 7).value    # G열
            if label is None:
                continue
            label_s = str(label).strip()
            if not label_s or label_s in ("총계", "합계"):
                continue
            amt = clean_int(val)
            cnt_i = clean_int(cnt)
            memo = ""
            if cnt is not None and not re.match(r"^\d+(\.0)?$", str(cnt).strip()) and str(cnt).strip():
                memo = str(cnt).strip()
            cname, cat, pay_type, grp = _canonical_item_meta(label_s, "변동매입", master_df)
            entry_rows.append({
                "정산월": ym,
                "항목명": cname,
                "대분류": cat,
                "결제방식": pay_type,
                "부분합계그룹": grp,
                "금액": amt,
                "횟수": cnt_i,
                "결제완료": (memo != "미수"),
                "메모": memo,
            })

        # 4) K/L/M열 상단 (R2~R9): 고기 단가 & 총량(kg)
        for r in range(2, 10):
            part_raw = ws.cell(r, 11).value  # K열
            if part_raw is None:
                continue
            part_s = str(part_raw).strip()
            if part_s in MEAT_ALIAS_MAP:
                std_part = MEAT_ALIAS_MAP[part_s]
                price = clean_int(ws.cell(r, 12).value)  # L열
                kg = clean_float(ws.cell(r, 13).value)   # M열
                meat_rows.append({
                    "정산월": ym,
                    "부위명": std_part,
                    "kg단가": price,
                    "총량(kg)": kg,
                })

        # 5) 기타지출 블록 탐지 (I/J열 또는 K/L/M열에 '기타' 헤더가 있는 위치)
        misc_header = None
        for r in range(8, 16):
            for c in (9, 11):  # I열 or K열
                v = ws.cell(r, c).value
                if v is not None and "기타" in str(v).strip():
                    misc_header = (r, c)
                    break
            if misc_header:
                break

        if misc_header:
            hr, hc = misc_header
            for r in range(hr + 1, max_r + 1):
                if hc == 9:
                    # I: 내용, J: 금액 (26.04, 26.05 패턴)
                    desc = ws.cell(r, 9).value
                    amt_v = ws.cell(r, 10).value
                    if desc is None:
                        if amt_v is not None:
                            break  # 소계 행
                        continue
                    desc_s = str(desc).strip()
                    if not desc_s or desc_s in ("총계", "합계"):
                        break
                    amt = clean_int(amt_v)
                    if amt != 0:
                        misc_rows.append({"정산월": ym, "일자": "", "내용": desc_s, "금액": amt, "메모": ""})
                else:
                    # K: 일자(또는 내용), L: 내용(또는 금액), M: 금액
                    v_k = ws.cell(r, 11).value
                    v_l = ws.cell(r, 12).value
                    v_m = ws.cell(r, 13).value
                    if v_k is None and v_l is None:
                        if v_m is not None:
                            break  # 소계 행
                        continue
                    if v_m is not None and v_l is not None:
                        # 26.07~26.10 패턴: K=일자, L=내용, M=금액
                        dt_s = ""
                        if v_k is not None:
                            if isinstance(v_k, (int, float)):
                                dt_s = f"{v_k:.2f}".rstrip("0").rstrip(".")
                            else:
                                dt_s = str(v_k).strip()
                        desc_s = str(v_l).strip()
                        amt = clean_int(v_m)
                        if desc_s and amt != 0:
                            misc_rows.append({"정산월": ym, "일자": dt_s, "내용": desc_s, "금액": amt, "메모": ""})
                    elif v_k is not None and v_l is not None and v_m is None:
                        # 26.06 패턴: K=내용, L=금액
                        desc_s = str(v_k).strip()
                        amt = clean_int(v_l)
                        if desc_s and amt != 0:
                            misc_rows.append({"정산월": ym, "일자": "", "내용": desc_s, "금액": amt, "메모": ""})

        logs.append(f"{ym}: 매출 {sales_val:,}원")

    # 동일 정산월·동일 항목명 중복 합산 처리 (예: 26.05 지방소득세+종합소득세 -> 지방세)
    df_e = pd.DataFrame(entry_rows, columns=ENTRIES_HEADERS)
    if not df_e.empty:
        df_e = (
            df_e.groupby(["정산월", "항목명", "대분류", "결제방식", "부분합계그룹"], as_index=False)
            .agg({"금액": "sum", "횟수": "sum", "결제완료": "all", "메모": lambda s: ",".join([x for x in s if x])})
        )
    df_m = pd.DataFrame(misc_rows, columns=MISC_HEADERS)
    df_k = pd.DataFrame(meat_rows, columns=MEAT_HEADERS)
    return df_e, df_m, df_k, sales_dict, logs


# =========================================================================
# 5. 은행 · 카드 · 네이버/쿠팡 거래내역 엑셀 자동 파서 & 분류 엔진
# =========================================================================
DATE_COL_HINTS = ["거래일", "이용일", "승인일", "결제일", "주문일", "일자", "날짜", "date"]
DESC_COL_HINTS = ["적요", "가맹점", "거래처", "내용", "상품명", "기재내용", "받는분", "입출금처", "이용가맹점", "상호", "메모"]
OUT_COL_HINTS = ["출금", "출금액", "출금금액", "이용금액", "승인금액", "결제금액", "지출", "찾으신금액", "매입금액", "거래금액", "금액"]
IN_COL_HINTS = ["입금", "입금액", "입금금액", "맡기신금액"]


def read_uploaded_table(file_name: str, file_bytes: bytes) -> pd.DataFrame:
    """은행/카드/쇼핑 CSV·XLSX 파일에서 상단 메타행을 자동 스킵하고 헤더 테이블 로드."""
    lower = file_name.lower()
    raw_df = None

    if lower.endswith(".csv"):
        for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
            try:
                raw_df = pd.read_csv(io.BytesIO(file_bytes), header=None, encoding=enc, dtype=str)
                break
            except Exception:
                continue
    else:
        try:
            raw_df = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str)
        except Exception:
            return pd.DataFrame()

    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    # 상위 15행 중 컬럼 키워드가 가장 많이 매칭되는 행을 헤더로 자동 감지
    all_hints = DATE_COL_HINTS + DESC_COL_HINTS + OUT_COL_HINTS
    best_idx = 0
    best_score = -1
    scan_limit = min(15, len(raw_df))
    for i in range(scan_limit):
        row_vals = [str(x).strip() for x in raw_df.iloc[i].tolist()]
        non_empty = [v for v in row_vals if v and v.lower() != "nan"]
        if len(non_empty) < 2:
            continue
        score = sum(
            1 for v in non_empty if any(h in v.lower().replace(" ", "") for h in all_hints)
        )
        if score > best_score:
            best_score = score
            best_idx = i

    headers = []
    seen = {}
    for idx, val in enumerate(raw_df.iloc[best_idx].tolist()):
        h = str(val).strip()
        if not h or h.lower() == "nan":
            h = f"컬럼{idx+1}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 1
        headers.append(h)

    df = raw_df.iloc[best_idx + 1:].copy()
    df.columns = headers
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def guess_tx_columns(df: pd.DataFrame) -> dict:
    cols = list(df.columns)

    def _pick(hints):
        for h in hints:
            for c in cols:
                if h in str(c).lower().replace(" ", ""):
                    return c
        return cols[0] if cols else ""

    desc_cols = [c for c in cols if any(h in str(c).lower().replace(" ", "") for h in DESC_COL_HINTS)]
    if not desc_cols and cols:
        desc_cols = [cols[min(1, len(cols) - 1)]]

    return {
        "date_col": _pick(DATE_COL_HINTS),
        "desc_cols": desc_cols,
        "amount_col": _pick(OUT_COL_HINTS),
    }


def classify_transactions(
    df_tx: pd.DataFrame,
    date_col: str,
    desc_cols: list[str],
    amount_col: str,
    master_df: pd.DataFrame,
    source_label: str = "",
) -> pd.DataFrame:
    """거래내역 DataFrame을 키워드 매핑 규칙으로 자동 분류."""
    rules = []
    for _, r in master_df.iterrows():
        if str(r.get("사용여부", "TRUE")).upper() == "FALSE":
            continue
        item_name = str(r["항목명"]).strip()
        kw_raw = str(r.get("키워드", "")).strip()
        kws = [k.strip().lower().replace(" ", "") for k in re.split(r"[,;/|]", kw_raw) if k.strip()]
        # 항목명 자체도 키워드로 보조 추가 (괄호 앞부분 포함)
        base_nm = re.sub(r"\(.*?\)|\[.*?\]", "", item_name).strip().lower().replace(" ", "")
        if len(base_nm) >= 2 and base_nm not in kws:
            kws.append(base_nm)
        # 긴 키워드 우선 매칭
        for kw in kws:
            if len(kw) >= 2:
                rules.append((len(kw), kw, item_name, str(r["대분류"]), str(r["결제방식"])))

    rules.sort(key=lambda x: -x[0])

    out_rows = []
    for _, row in df_tx.iterrows():
        amt = clean_int(row.get(amount_col, 0))
        if amt <= 0:
            continue
        dt_str = str(row.get(date_col, "")).strip()
        if dt_str.lower() == "nan":
            dt_str = ""
        # 날짜에서 일(day) 추출 (하람/도원 선결제 vs 말일결제 자동 판별용)
        day_num = 0
        m_dt = re.search(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", dt_str)
        if m_dt:
            day_num = int(m_dt.group(3))
            dt_str = f"{int(m_dt.group(2))}.{int(m_dt.group(3))}"

        desc_parts = []
        for dc in desc_cols:
            v = str(row.get(dc, "")).strip()
            if v and v.lower() != "nan":
                desc_parts.append(v)
        desc_full = " / ".join(desc_parts)
        desc_norm = desc_full.lower().replace(" ", "")

        matched_item = "미분류(기타지출)"
        matched_cat = "기타지출"
        matched_pay = "기타"

        for _, kw, item_name, cat, pay_type in rules:
            if kw in desc_norm:
                matched_item = item_name
                matched_cat = cat
                matched_pay = pay_type
                break

        # 하람/도원 특수 규칙: 월중(1~27일) 결제 건은 '선결제[하람]'/'선결제[도원]'으로 자동 제안
        if matched_item == "하람" and 1 <= day_num <= 27:
            matched_item = "선결제[하람]"
            matched_pay = "선결제/수시"
        elif matched_item == "도원에프엔비" and 1 <= day_num <= 27:
            matched_item = "선결제[도원]"
            matched_pay = "선결제/수시"

        out_rows.append({
            "포함": True,
            "출처": source_label,
            "일자": dt_str,
            "거래내용": desc_full,
            "금액": amt,
            "분류항목": matched_item,
            "구분": matched_pay,
        })

    return pd.DataFrame(out_rows)


# =========================================================================
# 6. 월별 종합 손익 · 원가변동 집계 & 엑셀 내보내기
# =========================================================================
def build_monthly_summary_df(
    df_entries: pd.DataFrame,
    df_misc: pd.DataFrame,
    df_meat: pd.DataFrame,
    sales_map: dict,
    payroll_map: dict,
    payroll_offset_next_month: bool = True,
) -> pd.DataFrame:
    """전체 정산월 기준 손익/원가/인건비 종합 테이블 생성."""
    months = set(sales_map.keys())
    if not df_entries.empty:
        months.update(df_entries["정산월"].unique().tolist())
    if not df_misc.empty:
        months.update(df_misc["정산월"].unique().tolist())
    if not df_meat.empty:
        months.update(df_meat["정산월"].unique().tolist())

    months = sorted([m for m in months if re.match(r"^\d{2}\.\d{2}$", str(m))])
    rows = []
    for ym in months:
        sales = int(sales_map.get(ym, 0))
        sub_e = df_entries[df_entries["정산월"] == ym] if not df_entries.empty else pd.DataFrame()
        sub_m = df_misc[df_misc["정산월"] == ym] if not df_misc.empty else pd.DataFrame()
        sub_k = df_meat[df_meat["정산월"] == ym] if not df_meat.empty else pd.DataFrame()

        fixed_cost = int(sub_e[sub_e["대분류"] == "공통"]["금액"].sum()) if not sub_e.empty else 0
        mgmt_cost = int(sub_e[sub_e["대분류"] == "관리비"]["금액"].sum()) if not sub_e.empty else 0
        var_cost = int(sub_e[sub_e["대분류"] == "변동매입"]["금액"].sum()) if not sub_e.empty else 0
        misc_cost = int(sub_m["금액"].sum()) if not sub_m.empty else 0

        meat_cost = int(sub_e[sub_e["부분합계그룹"] == "고기"]["금액"].sum()) if not sub_e.empty else 0
        food_cost = int(sub_e[sub_e["부분합계그룹"] == "식자재"]["금액"].sum()) if not sub_e.empty else 0
        meat_kg = round(float(sub_k["총량(kg)"].sum()), 2) if not sub_k.empty else 0.0

        total_expense = fixed_cost + mgmt_cost + var_cost + misc_cost
        pay_ym = next_ym(ym) if payroll_offset_next_month else ym
        labor_cost = int(payroll_map.get(pay_ym, {}).get("총인건비", 0))
        net_profit = sales - total_expense - labor_cost if sales > 0 else 0

        rows.append({
            "정산월": ym,
            "매출": sales,
            "공통고정비": fixed_cost,
            "관리비세금": mgmt_cost,
            "변동매입": var_cost,
            "기타지출": misc_cost,
            "총지출(인건비제외)": total_expense,
            "고기값": meat_cost,
            "식자재": food_cost,
            "고기량(kg)": meat_kg,
            "인건비탭": pay_ym,
            "인건비": labor_cost,
            "순이익": net_profit,
            "고기+식자재율(%)": round((meat_cost + food_cost) / sales * 100, 1) if sales > 0 else 0.0,
            "인건비율(%)": round(labor_cost / sales * 100, 1) if (sales > 0 and labor_cost > 0) else 0.0,
            "영업이익률(%)": round(net_profit / sales * 100, 1) if (sales > 0 and labor_cost > 0) else 0.0,
        })

    df_sum = pd.DataFrame(rows)
    if not df_sum.empty:
        df_sum["매출증감"] = df_sum["매출"].diff().fillna(0).astype(int)
        df_sum["고기값증감"] = df_sum["고기값"].diff().fillna(0).astype(int)
        df_sum["식자재증감"] = df_sum["식자재"].diff().fillna(0).astype(int)
        df_sum["고기량증감(kg)"] = df_sum["고기량(kg)"].diff().fillna(0.0).round(2)
    return df_sum


def build_meat_cost_trend_df(df_meat: pd.DataFrame) -> pd.DataFrame:
    """원가변동 시트용: 월별 부위별 kg단가 · 1인분 원가 · 원가율(%) 테이블."""
    if df_meat is None or df_meat.empty:
        return pd.DataFrame()
    months = sorted(df_meat["정산월"].unique().tolist())
    rows = []
    for ym in months:
        sub = df_meat[df_meat["정산월"] == ym]
        pmap = {str(r["부위명"]): clean_int(r["kg단가"]) for _, r in sub.iterrows()}
        rec = {"정산월": ym}
        for sp in MEAT_MENU_SPECS:
            part = sp["부위명"]
            if part == "돼지갈비" and part not in pmap:
                continue
            kg_p = pmap.get(part, 0)
            unit_cost = int(round(kg_p * sp["중량g"] / 1000.0)) if kg_p > 0 else 0
            ratio = round(unit_cost / sp["판매가"] * 100.0, 1) if (unit_cost > 0 and sp["판매가"] > 0) else 0.0
            rec[f"{part}_단가"] = kg_p
            rec[f"{part}_원가"] = unit_cost
            rec[f"{part}_원가율(%)"] = ratio
        rows.append(rec)
    return pd.DataFrame(rows)


def build_settlement_excel(
    store_name: str,
    ym: str,
    sales: int,
    labor_cost: int,
    labor_tab_ym: str,
    df_entries_m: pd.DataFrame,
    df_misc_m: pd.DataFrame,
    df_meat_m: pd.DataFrame,
    df_summary_all: pd.DataFrame,
    df_meat_trend: pd.DataFrame,
) -> bytes:
    """기존 엑셀 양식 느낌을 살린 월말정산 + 원가변동 + 종합 통합 엑셀(.xlsx) 생성."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = ym

    font_bold = Font(name="맑은 고딕", size=10, bold=True)
    font_norm = Font(name="맑은 고딕", size=10)
    fill_header = PatternFill("solid", fgColor="1E293B")
    font_header = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
    fill_green = PatternFill("solid", fgColor="E2EFDA")  # 말일결제 초록색 하이라이트
    fill_sub = PatternFill("solid", fgColor="F1F5F9")
    thin = Side(style="thin", color="CBD5E1")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # 상단 요약
    ws["A1"] = f"[{store_name}] {ym_to_kor(ym)} 월말정산 내역"
    ws["A1"].font = Font(name="맑은 고딕", size=13, bold=True)

    # 매출 / 총지출 / 인건비 / 순이익
    fixed_df = df_entries_m[df_entries_m["대분류"] == "공통"] if not df_entries_m.empty else pd.DataFrame()
    mgmt_df = df_entries_m[df_entries_m["대분류"] == "관리비"] if not df_entries_m.empty else pd.DataFrame()
    var_df = df_entries_m[df_entries_m["대분류"] == "변동매입"] if not df_entries_m.empty else pd.DataFrame()

    fixed_sum = int(fixed_df["금액"].sum()) if not fixed_df.empty else 0
    mgmt_sum = int(mgmt_df["금액"].sum()) if not mgmt_df.empty else 0
    var_sum = int(var_df["금액"].sum()) if not var_df.empty else 0
    misc_sum = int(df_misc_m["금액"].sum()) if not df_misc_m.empty else 0
    tot_exp = fixed_sum + mgmt_sum + var_sum + misc_sum
    net_profit = sales - tot_exp - labor_cost

    summary_pairs = [
        ("매출", sales),
        ("총지출(인건비제외)", tot_exp),
        (f"인건비({labor_tab_ym}탭)", labor_cost),
        ("월 순이익", net_profit),
    ]
    for i, (k, v) in enumerate(summary_pairs, start=1):
        c1 = ws.cell(3, (i - 1) * 2 + 1, k)
        c2 = ws.cell(3, (i - 1) * 2 + 2, v)
        c1.font = font_header
        c1.fill = fill_header
        c2.font = font_bold
        c2.number_format = "#,##0"
        c2.border = border

    # 상세 테이블: 대분류별
    row_cur = 5
    headers = ["대분류", "결제방식", "항목명", "금액", "횟수", "결제완료", "메모"]
    for ci, h in enumerate(headers, start=1):
        cell = ws.cell(row_cur, ci, h)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = Alignment(horizontal="center")
    row_cur += 1

    for _, r in df_entries_m.iterrows():
        is_eom = str(r.get("결제방식", "")) == "말일결제"
        vals = [
            r.get("대분류", ""),
            r.get("결제방식", ""),
            r.get("항목명", ""),
            int(r.get("금액", 0)),
            int(r.get("횟수", 0)),
            "완료" if r.get("결제완료", False) else "대기",
            r.get("메모", ""),
        ]
        for ci, v in enumerate(vals, start=1):
            c = ws.cell(row_cur, ci, v)
            c.font = font_norm
            c.border = border
            if is_eom:
                c.fill = fill_green
            if ci == 4:
                c.number_format = "#,##0"
        row_cur += 1

    # 기타지출
    row_cur += 1
    ws.cell(row_cur, 1, "기타지출").font = font_bold
    row_cur += 1
    for ci, h in enumerate(["일자", "내용", "금액", "메모"], start=1):
        c = ws.cell(row_cur, ci, h)
        c.font = font_header
        c.fill = fill_header
    row_cur += 1
    if not df_misc_m.empty:
        for _, r in df_misc_m.iterrows():
            for ci, v in enumerate([r.get("일자", ""), r.get("내용", ""), int(r.get("금액", 0)), r.get("메모", "")], start=1):
                c = ws.cell(row_cur, ci, v)
                c.font = font_norm
                c.border = border
                if ci == 3:
                    c.number_format = "#,##0"
            row_cur += 1

    # 고기단가/총량
    row_cur += 1
    ws.cell(row_cur, 1, "고기 단가 및 총량(kg)").font = font_bold
    row_cur += 1
    for ci, h in enumerate(["부위명", "kg단가", "총량(kg)"], start=1):
        c = ws.cell(row_cur, ci, h)
        c.font = font_header
        c.fill = fill_header
    row_cur += 1
    if not df_meat_m.empty:
        for _, r in df_meat_m.iterrows():
            for ci, v in enumerate([r.get("부위명", ""), int(r.get("kg단가", 0)), float(r.get("총량(kg)", 0))], start=1):
                c = ws.cell(row_cur, ci, v)
                c.font = font_norm
                c.border = border
                if ci == 2:
                    c.number_format = "#,##0"
            row_cur += 1

    # 종합 시트
    if df_summary_all is not None and not df_summary_all.empty:
        ws_sum = wb.create_sheet("종합")
        cols = list(df_summary_all.columns)
        for ci, h in enumerate(cols, start=1):
            c = ws_sum.cell(1, ci, h)
            c.font = font_header
            c.fill = fill_header
        for ri, (_, r) in enumerate(df_summary_all.iterrows(), start=2):
            for ci, h in enumerate(cols, start=1):
                c = ws_sum.cell(ri, ci, r[h])
                c.font = font_norm
                c.border = border
                if isinstance(r[h], int):
                    c.number_format = "#,##0"

    # 원가변동 시트
    if df_meat_trend is not None and not df_meat_trend.empty:
        ws_mt = wb.create_sheet("원가변동")
        cols = list(df_meat_trend.columns)
        for ci, h in enumerate(cols, start=1):
            c = ws_mt.cell(1, ci, h)
            c.font = font_header
            c.fill = fill_header
        for ri, (_, r) in enumerate(df_meat_trend.iterrows(), start=2):
            for ci, h in enumerate(cols, start=1):
                c = ws_mt.cell(ri, ci, r[h])
                c.font = font_norm
                c.border = border
                if isinstance(r[h], int):
                    c.number_format = "#,##0"

    # 열 너비 자동 조정
    for sheet in wb.worksheets:
        for col in sheet.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=8)
            sheet.column_dimensions[col[0].column_letter].width = min(max(max_len + 4, 11), 28)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
