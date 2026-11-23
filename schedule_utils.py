"""
================================================================================
[파일명] schedule_utils.py
[역할] 다매장 파트타임 주간 스케줄 관리 백엔드 · 카톡 텍스트 · 시간표 PNG 생성 모듈
[시트 스키마 (지점별 통합근태DB 내)]
  1. 주간스케줄_고정 : 이름 | 구분(고정/유동) | 월 | 화 | 수 | 목 | 금 | 토 | 일 | 메모
  2. 주간스케줄      : 주차 | 구분(확정/직원요청) | 이름 | 월 | 화 | 수 | 목 | 금 | 토 | 일 | 메모 | 수정일시
================================================================================
"""

import io
import os
import re
import datetime
import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

from store_registry import get_gspread_client

KST = datetime.timezone(datetime.timedelta(hours=9))
DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]

FIXED_HEADERS = ["이름", "구분", "월", "화", "수", "목", "금", "토", "일", "메모"]
WEEKLY_HEADERS = ["주차", "구분", "이름", "월", "화", "수", "목", "금", "토", "일", "메모", "수정일시"]

WEEKDAY_TIME_PRESETS = ["휴무", "16:00", "17:00", "17:30", "18:00", "직접입력"]
WEEKEND_TIME_PRESETS = ["휴무", "11:30", "12:00", "17:00", "17:30", "18:00", "12:00/17:00", "직접입력"]
OFF_REQUEST_TOKEN = "❌휴무요청"


def kst_now() -> datetime.datetime:
    return datetime.datetime.now(KST)


def kst_today() -> datetime.date:
    return kst_now().date()


def get_week_monday(ref_date: datetime.date) -> datetime.date:
    """해당 날짜가 속한 주의 월요일을 반환합니다."""
    return ref_date - datetime.timedelta(days=ref_date.weekday())


def get_week_dates(monday: datetime.date) -> list:
    """월요일 기준 월~일 7일의 datetime.date 리스트를 반환합니다."""
    return [monday + datetime.timedelta(days=i) for i in range(7)]


def get_selectable_weeks(ref_date: datetime.date = None) -> tuple:
    """선택 가능한 주차 옵션 딕셔너리({라벨: 월요일_date})와 기본 선택 인덱스를 반환합니다."""
    today = ref_date or kst_today()
    this_mon = get_week_monday(today)
    weeks = [
        ("이번 주", this_mon),
        ("다음 주", this_mon + datetime.timedelta(days=7)),
        ("다다음 주", this_mon + datetime.timedelta(days=14)),
    ]
    options = {}
    for tag, mon in weeks:
        sun = mon + datetime.timedelta(days=6)
        label = f"{tag} ({mon.strftime('%m/%d')} 월 ~ {sun.strftime('%m/%d')} 일)"
        options[label] = mon
    # 목~일에는 기본적으로 '다음 주'(인덱스 1), 월~수에도 스케줄 작성은 '다음 주'가 기본 편리
    default_idx = 1
    return options, default_idx


def _extract_active_part_names(rows: list) -> list:
    """'파트타임' 탭 원본 행에서 재직 중 실근무자명 목록을 추출합니다."""
    if len(rows) < 2:
        return []
    headers = [c.strip() for c in rows[0]]
    names = []
    for r in rows[1:]:
        d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
        reg_nm = d.get("이름", "").strip()
        memo_nm = d.get("메모", "").strip()
        st_val = d.get("상태", "재직").strip()
        if not reg_nm or st_val == "퇴사":
            continue
        real_nm = memo_nm if (memo_nm and "퇴사" not in memo_nm and len(memo_nm) <= 5) else reg_nm
        if real_nm not in names:
            names.append(real_nm)
    return names


@st.cache_data(ttl=20, show_spinner="주간 스케줄 데이터를 불러오는 중...")
def load_schedule_bundle(db_id: str):
    """
    1회의 values_batch_get으로 파트타임 명부, 주간스케줄_고정, 주간스케줄을 한 번에 로드합니다.
    반환: (active_part_names: list, df_fixed: DataFrame, df_weekly: DataFrame)
    """
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    titles = [ws.title.strip() for ws in ss.worksheets()]

    target_tabs = [t for t in ["파트타임", "주간스케줄_고정", "주간스케줄"] if t in titles]
    values_map = {}
    if target_tabs:
        res = ss.values_batch_get([f"'{t}'!A:P" for t in target_tabs])
        for tab_name, vr in zip(target_tabs, res.get("valueRanges", [])):
            values_map[tab_name] = vr.get("values", [])

    active_part_names = _extract_active_part_names(values_map.get("파트타임", []))

    def _to_df(rows: list, expected_cols: list):
        out = []
        if len(rows) >= 2:
            headers = [c.strip() for c in rows[0]]
            for r in rows[1:]:
                d = {headers[j]: (r[j].strip() if j < len(r) else "") for j in range(len(headers)) if headers[j]}
                if any(d.values()):
                    out.append(d)
        df = pd.DataFrame(out)
        for col in expected_cols:
            if col not in df.columns:
                df[col] = ""
        return df[expected_cols].copy()

    df_fixed = _to_df(values_map.get("주간스케줄_고정", []), FIXED_HEADERS)
    if not df_fixed.empty:
        df_fixed = df_fixed[df_fixed["이름"].str.strip() != ""].copy()
        df_fixed["구분"] = df_fixed["구분"].apply(lambda x: "고정" if str(x).strip() == "고정" else "유동")

    df_weekly = _to_df(values_map.get("주간스케줄", []), WEEKLY_HEADERS)
    if not df_weekly.empty:
        df_weekly = df_weekly[
            (df_weekly["주차"].str.strip() != "") & (df_weekly["이름"].str.strip() != "")
        ].copy()

    return active_part_names, df_fixed, df_weekly


def _get_or_create_ws(ss, title: str, headers: list):
    titles = [ws.title.strip() for ws in ss.worksheets()]
    if title in titles:
        ws = ss.worksheet(title)
        first = ws.row_values(1)
        if not first:
            ws.append_row(headers, value_input_option="RAW")
        return ws
    ws = ss.add_worksheet(title=title, rows=500, cols=len(headers) + 2)
    ws.append_row(headers, value_input_option="RAW")
    return ws


def save_fixed_templates(db_id: str, df_fixed_edited: pd.DataFrame):
    """'주간스케줄_고정' 탭 전체를 RAW 모드로 저장합니다."""
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    ws = _get_or_create_ws(ss, "주간스케줄_고정", FIXED_HEADERS)

    clean = df_fixed_edited.copy()
    for c in FIXED_HEADERS:
        if c not in clean.columns:
            clean[c] = ""
    clean = clean[FIXED_HEADERS].fillna("").astype(str)
    for c in FIXED_HEADERS:
        clean[c] = clean[c].str.strip()
    clean = clean[clean["이름"] != ""]
    clean["구분"] = clean["구분"].apply(lambda x: "고정" if x == "고정" else "유동")
    for d in DAY_NAMES:
        clean[d] = clean[d].apply(lambda x: "" if x in ("-", "휴무", "없음") else x)

    ws.clear()
    ws.update(range_name="A1", values=[FIXED_HEADERS] + clean.values.tolist(), value_input_option="RAW")


def upsert_employee_request(db_id: str, week_str: str, emp_name: str, day_values: dict, memo: str = ""):
    """직원이 제출한 특정 주차의 희망/예외 스케줄('직원요청')을 저장(덮어쓰기)합니다."""
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    ws = _get_or_create_ws(ss, "주간스케줄", WEEKLY_HEADERS)

    rows = ws.get_all_values()
    now_str = kst_now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = [
        week_str,
        "직원요청",
        emp_name.strip(),
        *[str(day_values.get(d, "")).strip() for d in DAY_NAMES],
        memo.strip(),
        now_str,
    ]

    found_row_idx = None
    for idx, r in enumerate(rows[1:], start=2):
        if (
            len(r) >= 3
            and r[0].strip() == week_str
            and r[1].strip() == "직원요청"
            and r[2].strip() == emp_name.strip()
        ):
            found_row_idx = idx
            break

    if found_row_idx:
        end_col = chr(ord("A") + len(WEEKLY_HEADERS) - 1)
        ws.update(
            range_name=f"A{found_row_idx}:{end_col}{found_row_idx}",
            values=[new_row],
            value_input_option="RAW",
        )
    else:
        ws.append_row(new_row, value_input_option="RAW")


def save_confirmed_week_schedule(db_id: str, week_str: str, df_confirmed: pd.DataFrame):
    """특정 주차의 '확정' 스케줄을 저장합니다 (다른 주차 및 '직원요청' 행은 그대로 보존)."""
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    ws = _get_or_create_ws(ss, "주간스케줄", WEEKLY_HEADERS)

    existing_rows = ws.get_all_values()
    kept_rows = []
    if len(existing_rows) >= 2:
        for r in existing_rows[1:]:
            padded = r + [""] * max(0, len(WEEKLY_HEADERS) - len(r))
            padded = padded[: len(WEEKLY_HEADERS)]
            if padded[0].strip() == week_str and padded[1].strip() == "확정":
                continue
            if any(x.strip() for x in padded):
                kept_rows.append(padded)

    now_str = kst_now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows = []
    for _, row in df_confirmed.iterrows():
        nm = str(row.get("이름", "")).strip()
        if not nm:
            continue
        day_vals = []
        for d in DAY_NAMES:
            v = str(row.get(d, "")).strip()
            if v in ("-", "휴무", "없음", OFF_REQUEST_TOKEN):
                v = ""
            day_vals.append(v)
        memo_v = str(row.get("메모", "")).strip()
        new_rows.append([week_str, "확정", nm, *day_vals, memo_v, now_str])

    ws.clear()
    ws.update(
        range_name="A1",
        values=[WEEKLY_HEADERS] + kept_rows + new_rows,
        value_input_option="RAW",
    )


def _is_lunch_shift(time_str: str) -> bool:
    """출근시간 문자열에서 첫 시작 시각이 15시 미만이면 점심 시프트로 판별합니다."""
    m = re.search(r"(\d{1,2})\s*:", str(time_str))
    if not m:
        return False
    return int(m.group(1)) < 15


def normalize_time_cell(val: str) -> str:
    s = str(val or "").strip()
    if s in ("", "-", "휴무", "없음", "nan", "None", OFF_REQUEST_TOKEN):
        return ""
    return s


def summarize_daily_staff(df_week: pd.DataFrame) -> dict:
    """
    요일별 배치 직원 목록과 인원 수를 계산합니다.
    반환: {day_name: {"count": int, "lunch": [(name, time)], "dinner": [(name, time)], "all": [(name, time)]}}
    """
    summary = {}
    for idx, d in enumerate(DAY_NAMES):
        entries = []
        lunch_list = []
        dinner_list = []
        if df_week is not None and not df_week.empty and d in df_week.columns:
            for _, r in df_week.iterrows():
                nm = str(r.get("이름", "")).strip()
                t_val = normalize_time_cell(r.get(d, ""))
                if not nm or not t_val:
                    continue
                entries.append((nm, t_val))
                if idx >= 5:
                    # 주말: "12:00/17:00" 같이 더블 시프트면 점심·저녁 양쪽 카운트
                    tokens = [tok.strip() for tok in re.split(r"[/,]+", t_val) if tok.strip()]
                    if len(tokens) >= 2:
                        lunch_list.append((nm, tokens[0]))
                        dinner_list.append((nm, tokens[1]))
                    elif _is_lunch_shift(t_val):
                        lunch_list.append((nm, t_val))
                    else:
                        dinner_list.append((nm, t_val))
                else:
                    dinner_list.append((nm, t_val))

        entries.sort(key=lambda x: (x[1], x[0]))
        lunch_list.sort(key=lambda x: (x[1], x[0]))
        dinner_list.sort(key=lambda x: (x[1], x[0]))
        summary[d] = {
            "count": len(entries),
            "lunch": lunch_list,
            "dinner": dinner_list,
            "all": entries,
        }
    return summary


def build_kakao_schedule_text(store_title: str, monday: datetime.date, df_confirmed: pd.DataFrame) -> str:
    """카카오톡 단톡방에 바로 복사·붙여넣기 가능한 깔끔한 주간 스케줄 텍스트를 생성합니다."""
    dates = get_week_dates(monday)
    sun = dates[-1]
    summary = summarize_daily_staff(df_confirmed)

    lines = [
        f"📅 [{store_title} 주간 파트타임 스케줄]",
        f"기간: {monday.strftime('%m/%d')}(월) ~ {sun.strftime('%m/%d')}(일)",
        "━━━━━━━━━━━━━━━━━━",
    ]
    for idx, d in enumerate(DAY_NAMES):
        dt = dates[idx]
        info = summary[d]
        date_tag = f"{d}({dt.strftime('%m/%d')})"
        if info["count"] == 0:
            lines.append(f"• {date_tag}: 배정 없음")
            continue

        if idx >= 5 and (info["lunch"] and info["dinner"]):
            l_str = ", ".join([f"{n}({t})" for n, t in info["lunch"]])
            d_str = ", ".join([f"{n}({t})" for n, t in info["dinner"]])
            lines.append(f"• {date_tag} [{info['count']}명]")
            lines.append(f"   - 점심: {l_str}")
            lines.append(f"   - 저녁: {d_str}")
        else:
            all_str = ", ".join([f"{n}({t})" for n, t in info["all"]])
            lines.append(f"• {date_tag} [{info['count']}명]: {all_str}")

    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("※ 출근시간 변동이나 불가 사유 발생 시 매니저에게 미리 연락해 주세요!")
    return "\n".join(lines)


def _load_pil_fonts():
    reg_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
    ]
    reg_path = next((p for p in reg_candidates if os.path.exists(p)), None)
    bold_path = next((p for p in bold_candidates if os.path.exists(p)), reg_path)

    def _mk(path, size):
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    return {
        "title": _mk(bold_path, 34),
        "sub": _mk(reg_path, 21),
        "th": _mk(bold_path, 22),
        "th_sub": _mk(reg_path, 17),
        "name": _mk(bold_path, 22),
        "cell": _mk(bold_path, 20),
        "muted": _mk(reg_path, 20),
        "foot": _mk(bold_path, 20),
        "note": _mk(reg_path, 17),
    }


def generate_schedule_png(store_title: str, monday: datetime.date, df_confirmed: pd.DataFrame) -> bytes:
    """모바일/카톡 단톡방 공유에 최적화된 고해상도 주간 시간표 PNG 이미지를 생성합니다."""
    fonts = _load_pil_fonts()
    dates = get_week_dates(monday)
    sun = dates[-1]
    summary = summarize_daily_staff(df_confirmed)

    # 유효한 행만 추출
    rows_data = []
    if df_confirmed is not None and not df_confirmed.empty:
        for _, r in df_confirmed.iterrows():
            nm = str(r.get("이름", "")).strip()
            if not nm:
                continue
            vals = [normalize_time_cell(r.get(d, "")) for d in DAY_NAMES]
            if any(vals):
                rows_data.append((nm, vals))

    width = 1240
    margin = 36
    header_h = 112
    th_h = 70
    row_h = 62
    foot_h = 64
    bottom_pad = 54
    num_rows = max(len(rows_data), 1)
    height = margin + header_h + 18 + th_h + (num_rows * row_h) + foot_h + bottom_pad + margin

    img = Image.new("RGB", (width, height), (248, 250, 252))
    draw = ImageDraw.Draw(img)

    # 1) 상단 다크 네이비 배너
    banner_box = (margin, margin, width - margin, margin + header_h)
    draw.rounded_rectangle(banner_box, radius=18, fill=(15, 23, 42))
    draw.text(
        (margin + 28, margin + 20),
        f"[{store_title}] 주간 파트타임 출근 스케줄",
        fill=(255, 255, 255),
        font=fonts["title"],
    )
    draw.text(
        (margin + 28, margin + 68),
        f"기간: {monday.strftime('%Y.%m.%d')} (월) ~ {sun.strftime('%m.%d')} (일)   |   표시된 시각은 출근시간 기준",
        fill=(203, 213, 225),
        font=fonts["sub"],
    )

    # 2) 표 영역 좌표
    table_top = margin + header_h + 18
    table_left = margin
    table_right = width - margin
    table_w = table_right - table_left
    name_col_w = 176
    day_col_w = (table_w - name_col_w) / 7.0

    table_bottom = table_top + th_h + (num_rows * row_h) + foot_h
    draw.rounded_rectangle(
        (table_left, table_top, table_right, table_bottom),
        radius=14,
        fill=(255, 255, 255),
        outline=(203, 213, 225),
        width=2,
    )

    # 헤더 행 배경
    draw.rectangle((table_left + 1, table_top + 1, table_right - 1, table_top + th_h), fill=(241, 245, 249))

    def _draw_centered(cx, cy, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2, cy - th / 2 - 2), text, fill=fill, font=font)

    _draw_centered(table_left + name_col_w / 2, table_top + th_h / 2, "이름", fonts["th"], (30, 41, 59))

    for i, d in enumerate(DAY_NAMES):
        x0 = table_left + name_col_w + i * day_col_w
        cx = x0 + day_col_w / 2
        if i == 5:
            day_color = (29, 78, 216)
            hdr_bg = (239, 246, 255)
        elif i == 6:
            day_color = (220, 38, 38)
            hdr_bg = (254, 242, 242)
        else:
            day_color = (30, 41, 59)
            hdr_bg = (241, 245, 249)
        draw.rectangle((x0, table_top + 1, x0 + day_col_w - 1, table_top + th_h), fill=hdr_bg)
        _draw_centered(cx, table_top + 24, f"{d}요일", fonts["th"], day_color)
        _draw_centered(cx, table_top + 51, dates[i].strftime("%m/%d"), fonts["th_sub"], (100, 116, 139))

    # 본문 행
    if not rows_data:
        _draw_centered(
            table_left + table_w / 2,
            table_top + th_h + row_h / 2,
            "확정된 출근 스케줄이 없습니다.",
            fonts["muted"],
            (100, 116, 139),
        )
    else:
        for r_idx, (emp_name, vals) in enumerate(rows_data):
            y0 = table_top + th_h + r_idx * row_h
            y1 = y0 + row_h
            cy = (y0 + y1) / 2
            row_bg = (255, 255, 255) if r_idx % 2 == 0 else (248, 250, 252)
            draw.rectangle((table_left + 1, y0, table_right - 1, y1), fill=row_bg)
            draw.line([(table_left, y0), (table_right, y0)], fill=(226, 232, 240), width=1)

            _draw_centered(table_left + name_col_w / 2, cy, emp_name, fonts["name"], (15, 23, 42))

            for i, val in enumerate(vals):
                x0 = table_left + name_col_w + i * day_col_w
                cx = x0 + day_col_w / 2
                if not val:
                    _draw_centered(cx, cy, "-", fonts["muted"], (203, 213, 225))
                else:
                    if i >= 5 and _is_lunch_shift(val):
                        pill_bg = (254, 243, 199)
                        pill_bd = (245, 158, 11)
                        pill_tx = (146, 64, 14)
                    else:
                        pill_bg = (219, 234, 254)
                        pill_bd = (59, 130, 246)
                        pill_tx = (30, 58, 138)
                    pad_x = 10
                    pill_box = (x0 + pad_x, y0 + 11, x0 + day_col_w - pad_x, y1 - 11)
                    draw.rounded_rectangle(pill_box, radius=10, fill=pill_bg, outline=pill_bd, width=1)
                    _draw_centered(cx, cy, val, fonts["cell"], pill_tx)

    # 하단 합계 행 (요일별 인원수)
    fy0 = table_top + th_h + num_rows * row_h
    fy1 = fy0 + foot_h
    fcy = (fy0 + fy1) / 2
    draw.rectangle((table_left + 1, fy0, table_right - 1, fy1 - 1), fill=(241, 245, 249))
    draw.line([(table_left, fy0), (table_right, fy0)], fill=(148, 163, 184), width=2)
    _draw_centered(table_left + name_col_w / 2, fcy, "출근 인원", fonts["foot"], (15, 23, 42))

    for i, d in enumerate(DAY_NAMES):
        x0 = table_left + name_col_w + i * day_col_w
        cx = x0 + day_col_w / 2
        cnt = summary[d]["count"]
        cnt_color = (5, 150, 105) if cnt >= 2 else ((220, 38, 38) if cnt == 0 else (217, 119, 6))
        _draw_centered(cx, fcy, f"{cnt}명", fonts["foot"], cnt_color)

    # 세로 구분선
    draw.line([(table_left + name_col_w, table_top), (table_left + name_col_w, table_bottom)], fill=(203, 213, 225), width=2)
    for i in range(1, 7):
        vx = table_left + name_col_w + i * day_col_w
        draw.line([(vx, table_top), (vx, table_bottom)], fill=(226, 232, 240), width=1)

    # 하단 안내 문구
    draw.text(
        (margin + 6, table_bottom + 16),
        "※ 출근시간 변동 또는 불가 사유 발생 시 매니저에게 미리 연락해 주세요.",
        fill=(100, 116, 139),
        font=fonts["note"],
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
