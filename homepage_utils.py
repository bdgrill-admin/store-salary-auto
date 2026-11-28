"""
================================================================================
[파일명] homepage_utils.py
[역할] 분당그릴 공식 AEO/GEO 홈페이지 차림표(메뉴)·영업정보 관리,
       정적 HTML / JSON-LD / llms.txt / sitemap.xml 자동 생성 및 GitHub Pages 원클릭 배포 모듈
================================================================================
"""

import html
import json
import base64
import datetime
import requests
import pandas as pd
import streamlit as st

from store_registry import get_gspread_client, get_secret

TAB_HP_MENU = "홈페이지_메뉴"
HP_MENU_HEADERS = ["분류", "메뉴명", "중량", "가격", "설명", "추천", "표시", "정렬순서"]
KST = datetime.timezone(datetime.timedelta(hours=9))


def get_default_menu_df() -> pd.DataFrame:
    """현재 홈페이지 기본 차림표 (수정 시 구글 시트 '홈페이지_메뉴' 탭에 저장)."""
    rows = [
        ("구이", "특숙성삼겹세트", "500g", 49000, "국내산 한돈 특숙성 삼겹살과 목살을 한 번에 즐기는 시그니처 2~3인 세트", True, True, 10),
        ("구이", "특수모듬세트(가브리+갈매기+늑간살)", "500g", 51000, "가브리살·갈매기살·늑간살, 한돈 인기 특수부위 3종을 한 판에 담은 모듬", True, True, 15),
        ("구이", "특숙성목살", "180g", 18000, "두툼하게 썰어 참숯에 구울수록 육즙이 터지는 분당그릴 대표 부위", True, True, 20),
        ("구이", "특숙성삼겹살", "180g", 18000, "특숙성으로 감칠맛을 끌어올려 겉은 바삭하고 속은 고소한 한돈 삼겹살", False, True, 30),
        ("구이", "갈매기살", "180g", 19000, "탱글한 탄력과 진한 육향이 살아있어 씹을수록 담백한 한돈 특수부위", False, True, 40),
        ("구이", "가브리살", "180g", 20000, "마블링이 촘촘해 입안에서 부드럽고 고소하게 녹아내리는 프리미엄 등겹살", False, True, 50),
        ("구이", "꼬들살", "180g", 18000, "특유의 꼬들한 식감과 쫄깃한 고소함이 매력적인 별미 특수부위", False, True, 60),
        ("구이", "양념갈비", "300g내외", 20000, "과하지 않고 깊은 특제 양념에 재워 남녀노소 누구나 즐기는 넉넉한 갈비", False, True, 70),
        ("더하기", "제주젓갈볶음밥", "", 9000, "감칠맛 진한 제주 젓갈로 고슬고슬하게 볶아낸 분당그릴 주문 1순위 식사", False, True, 110),
        ("더하기", "등뼈김치찌개", "", 9000, "잘 익은 묵은지와 국내산 등뼈를 푹 끓여내어 고기와 곁들이기 좋은 진한 찌개", False, True, 120),
        ("더하기", "명태회비빔막국수", "", 6000, "쫄깃한 명태회와 매콤달콤한 특제 양념이 고기의 느끼함을 잡아주는 별미 국수", False, True, 130),
        ("더하기", "시골동치미막국수", "", 6000, "시원하고 깔끔한 동치미 육수로 고기 식사 뒤 개운하게 마무리하는 물막국수", False, True, 140),
        ("더하기", "계란찜", "", 4000, "뚝배기에 폭신하고 부드럽게 끓여내어 아이와 함께 즐기기 좋은 곁들임", False, True, 150),
    ]
    return pd.DataFrame(rows, columns=HP_MENU_HEADERS)


def _clean_int(val) -> int:
    try:
        s = str(val).replace(",", "").replace("원", "").strip()
        return int(float(s)) if s else 0
    except Exception:
        return 0


@st.cache_data(ttl=180, show_spinner=False)
def load_homepage_menu(db_id: str) -> pd.DataFrame:
    """지점 DB의 '홈페이지_메뉴' 탭에서 차림표 로드 (없으면 기본값 반환)."""
    if not db_id:
        return get_default_menu_df()
    try:
        gc = get_gspread_client()
        ss = gc.open_by_key(db_id)
        titles = [ws.title.strip() for ws in ss.worksheets()]
        if TAB_HP_MENU not in titles:
            return get_default_menu_df()
        rows = ss.values_get(f"'{TAB_HP_MENU}'!A:H").get("values", [])
        if len(rows) < 2:
            return get_default_menu_df()

        data = []
        for r in rows[1:]:
            if not any(str(x).strip() for x in r):
                continue
            r_pad = list(r) + [""] * (len(HP_MENU_HEADERS) - len(r))
            data.append({
                "분류": str(r_pad[0]).strip() or "구이",
                "메뉴명": str(r_pad[1]).strip(),
                "중량": str(r_pad[2]).strip(),
                "가격": _clean_int(r_pad[3]),
                "설명": str(r_pad[4]).strip(),
                "추천": str(r_pad[5]).strip().upper() == "TRUE",
                "표시": str(r_pad[6]).strip().upper() != "FALSE",
                "정렬순서": _clean_int(r_pad[7]),
            })
        df = pd.DataFrame(data, columns=HP_MENU_HEADERS)
        if df.empty:
            return get_default_menu_df()
        return df.sort_values(["정렬순서", "메뉴명"]).reset_index(drop=True)
    except Exception:
        return get_default_menu_df()


def save_homepage_menu(db_id: str, df_menu: pd.DataFrame):
    """'홈페이지_메뉴' 탭에 RAW 모드로 저장."""
    gc = get_gspread_client()
    ss = gc.open_by_key(db_id)
    titles = [ws.title.strip() for ws in ss.worksheets()]
    if TAB_HP_MENU in titles:
        ws = ss.worksheet(TAB_HP_MENU)
        ws.clear()
    else:
        ws = ss.add_worksheet(title=TAB_HP_MENU, rows=100, cols=len(HP_MENU_HEADERS))

    df = df_menu.copy()
    df = df[df["메뉴명"].astype(str).str.strip() != ""].copy()
    df["가격"] = df["가격"].apply(_clean_int)
    df["정렬순서"] = df["정렬순서"].apply(_clean_int)
    df = df.sort_values(["정렬순서", "메뉴명"]).reset_index(drop=True)

    rows = [HP_MENU_HEADERS]
    for _, r in df.iterrows():
        rows.append([
            str(r.get("분류", "구이")).strip(),
            str(r.get("메뉴명", "")).strip(),
            str(r.get("중량", "")).strip(),
            str(_clean_int(r.get("가격", 0))),
            str(r.get("설명", "")).strip(),
            "TRUE" if bool(r.get("추천", False)) else "FALSE",
            "TRUE" if bool(r.get("표시", True)) else "FALSE",
            str(_clean_int(r.get("정렬순서", 0))),
        ])
    ws.update(range_name="A1", values=rows, value_input_option="RAW")


def render_homepage_files(df_menu: pd.DataFrame, info: dict) -> dict:
    """편집된 메뉴와 매장 정보로 docs/index.html, docs/llms.txt, docs/sitemap.xml을 생성."""
    site_url = str(info.get("site_url", "https://bdgrill.kr/")).strip()
    if not site_url.endswith("/"):
        site_url += "/"
    store_name = str(info.get("store_name", "분당그릴")).strip()
    address = str(info.get("address", "경기도 성남시 분당구 미금일로 74번길 13-3, 1층")).strip()
    phone = str(info.get("phone", "031-713-0342")).strip()
    weekday_hours = str(info.get("weekday_hours", "16:00 – 22:00")).strip()
    weekend_hours = str(info.get("weekend_hours", "12:00 – 22:00")).strip()
    break_time = str(info.get("break_time", "15:00 – 17:00")).strip()
    notice = str(info.get("notice", "")).strip()

    visible_df = df_menu[
        (df_menu["표시"] == True) & (df_menu["메뉴명"].astype(str).str.strip() != "")
    ].sort_values(["정렬순서", "메뉴명"]).copy()

    grill_df = visible_df[visible_df["분류"] == "구이"]
    side_df = visible_df[visible_df["분류"] != "구이"]

    def _build_menu_li(sub_df: pd.DataFrame) -> str:
        items_html = []
        for _, r in sub_df.iterrows():
            nm = html.escape(str(r["메뉴명"]).strip())
            wt = html.escape(str(r.get("중량", "")).strip())
            desc = html.escape(str(r.get("설명", "")).strip())
            price = _clean_int(r.get("가격", 0))
            rec = bool(r.get("추천", False))

            wt_span = f'<span class="menu-item-wt">{wt}</span>' if wt else ""
            rec_span = '<span class="tag-rec">사장님 추천</span>' if rec else ""
            desc_div = f'<div class="menu-item-sub">{desc}</div>' if desc else ""
            items_html.append(
                f'              <li class="menu-row">\n'
                f'                <div class="menu-row-left">\n'
                f'                  <div class="menu-item-name">{nm}{wt_span}{rec_span}</div>\n'
                f'                  {desc_div}\n'
                f'                </div>\n'
                f'                <div class="menu-item-price">{price:,}원</div>\n'
                f'              </li>'
            )
        return "\n".join(items_html)

    def _build_jsonld_items(sub_df: pd.DataFrame) -> list:
        out = []
        for _, r in sub_df.iterrows():
            nm = str(r["메뉴명"]).strip()
            wt = str(r.get("중량", "")).strip()
            full_nm = f"{nm} ({wt})" if wt else nm
            desc = str(r.get("설명", "")).strip() or full_nm
            price = _clean_int(r.get("가격", 0))
            out.append({
                "@type": "MenuItem",
                "name": full_nm,
                "description": desc,
                "offers": {"@type": "Offer", "price": str(price), "priceCurrency": "KRW"},
            })
        return out

    grill_summary = ", ".join(
        f"{r['메뉴명']}({r['중량']}) {_clean_int(r['가격']):,}원" if str(r['중량']).strip()
        else f"{r['메뉴명']} {_clean_int(r['가격']):,}원"
        for _, r in grill_df.iterrows()
    )
    side_summary = ", ".join(
        f"{r['메뉴명']}({_clean_int(r['가격']):,}원)"
        for _, r in side_df.head(4).iterrows()
    )

    jsonld_obj = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Restaurant",
                "@id": f"{site_url}#restaurant",
                "name": store_name,
                "alternateName": ["Bundang Grill", "분당그릴 미금", "미금역 분당그릴"],
                "description": (
                    f"{address}에 위치한 공식 한돈인증점 · 프리미엄 숙성 돼지고기 참숯 구이 전문점입니다. "
                    "현재 정상 영업 중이며 네이버 예약 및 전화 문의가 가능합니다."
                ),
                "url": site_url,
                "sameAs": [
                    "https://m.place.naver.com/restaurant/1699124309/home",
                    "https://www.instagram.com/bdgrill0524/",
                    "https://place.map.kakao.com/865459727",
                    "https://www.google.co.kr/maps/place/%EB%B6%84%EB%8B%B9%EA%B7%B8%EB%A6%B4/data=!4m10!1m5!3m4!1s0x357b59b100565c6d:0x67c1a9bc2df02953!2z67aE64u56re466a0!16s%2Fg%2F11h6ql4_yk!20s8Q9984W6%2BPFG!3m3!1s0x357b59b100565c6d:0x67c1a9bc2df02953!16s%2Fg%2F11h6ql4_yk!20s8Q9984W6%2BPFG",
                ],
                "potentialAction": {
                    "@type": "ReserveAction",
                    "target": {
                        "@type": "EntryPoint",
                        "urlTemplate": "https://m.place.naver.com/restaurant/1699124309/booking?entry=pll&bk_query=%EB%B6%84%EB%8B%B9%EA%B7%B8%EB%A6%B4",
                        "actionPlatform": [
                            "http://schema.org/DesktopWebPlatform",
                            "http://schema.org/MobileWebPlatform",
                        ],
                    },
                    "result": {
                        "@type": "FoodEstablishmentReservation",
                        "name": f"{store_name} 네이버 예약",
                    },
                },
                "logo": f"{site_url}img/logo-full.png",
                "foundingDate": "2018",
                "award": "한돈자조금관리위원회 공식 한돈인증점",
                "image": [
                    f"{site_url}img/hero-exterior.jpg",
                    f"{site_url}img/meat-cuts.jpg",
                    f"{site_url}img/charcoal.jpg",
                    f"{site_url}img/fried-rice.jpg",
                    f"{site_url}img/interior.jpg",
                ],
                "telephone": f"+82-{phone.lstrip('0')}" if phone.startswith("0") else phone,
                "priceRange": "₩₩ (18,000원~20,000원 / 1인분)",
                "servesCuisine": ["한국식 바비큐", "숙성 돼지고기", "삼겹살", "목살", "특수부위", "Korean BBQ"],
                "acceptsReservations": True,
                "currenciesAccepted": "KRW",
                "paymentAccepted": "신용카드, 체크카드, 현금, 계좌이체, 성남사랑상품권(chak), 성남시 아동수당 카드",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "미금일로 74번길 13-3, 1층",
                    "addressLocality": "성남시 분당구",
                    "addressRegion": "경기도",
                    "postalCode": "13626",
                    "addressCountry": "KR",
                },
                "openingHoursSpecification": [
                    {
                        "@type": "OpeningHoursSpecification",
                        "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
                        "opens": "16:00",
                        "closes": "22:00",
                    },
                    {
                        "@type": "OpeningHoursSpecification",
                        "dayOfWeek": ["Saturday", "Sunday"],
                        "opens": "12:00",
                        "closes": "15:00",
                    },
                    {
                        "@type": "OpeningHoursSpecification",
                        "dayOfWeek": ["Saturday", "Sunday"],
                        "opens": "17:00",
                        "closes": "22:00",
                    },
                ],
                "hasMenu": {"@id": f"{site_url}#menu"},
            },
            {
                "@type": "Menu",
                "@id": f"{site_url}#menu",
                "name": f"{store_name} 차림표",
                "inLanguage": "ko",
                "hasMenuSection": [
                    {
                        "@type": "MenuSection",
                        "name": "프리미엄 숙성돼지 구이",
                        "hasMenuItem": _build_jsonld_items(grill_df),
                    },
                    {
                        "@type": "MenuSection",
                        "name": "더하기 (식사 · 사이드)",
                        "hasMenuItem": _build_jsonld_items(side_df),
                    },
                ],
            },
            {
                "@type": "FAQPage",
                "@id": f"{site_url}#faq",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": f"{store_name}은 현재 정상 영업 중인가요? 라스트오더는 몇 시인가요?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": (
                                f"네, {store_name}은 {address}에서 현재 정상 영업 중입니다. "
                                f"평일 {weekday_hours}, 주말 {weekend_hours}(브레이크타임 {break_time})에 운영하며 라스트오더는 21:30입니다. "
                                f"네이버 예약 또는 매장 전화({phone})로 문의하실 수 있습니다."
                            ),
                        },
                    },
                    {
                        "@type": "Question",
                        "name": f"{store_name}은 한돈인증점인가요? 어떤 원육을 사용하나요?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": f"네, {store_name}은 한돈자조금관리위원회의 엄격한 심사를 통과한 공식 한돈인증점입니다. 100% 국내산 최상급 한돈만을 선별해 특숙성 과정을 거쳐 제공합니다.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": f"{store_name} 주차는 가능한가요?",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "매장 앞에 3대 주차 공간이 마련되어 있으나 피크 시간대에는 만석인 경우가 많아, 인근 주변 도로 주차 공간을 이용해 주셔야 합니다.",
                        },
                    },
                    {
                        "@type": "Question",
                        "name": "단체 회식 최대 인원과 아기의자 여부, 결제 수단이 궁금합니다.",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": f"단체 회식은 최대 50명까지 수용 가능하며, 가족 외식을 위한 아기의자도 구비되어 있습니다. 네이버 예약 또는 매장 전화({phone})로 사전 문의해 주세요. 신용카드·현금·계좌이체 외에 성남사랑상품권(chak) 및 성남시 아동수당 카드 결제도 가능합니다.",
                        },
                    },
                ],
            },
        ],
    }

    jsonld_str = json.dumps(jsonld_obj, ensure_ascii=False, indent=2)
    notice_banner = (
        f'<div class="notice-strip">{html.escape(notice)}</div>' if notice else ""
    )

    esc_name = html.escape(store_name)
    esc_addr = html.escape(address)
    esc_phone = html.escape(phone)
    esc_wk = html.escape(weekday_hours)
    esc_wknd = html.escape(weekend_hours)
    esc_bt = html.escape(break_time)

    index_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{esc_name} — 프리미엄 숙성돼지 · 미금역</title>
  <meta name="description" content="{esc_addr} 공식 한돈인증점 · 프리미엄 숙성 돼지고기 참숯 구이 전문점 {esc_name}. 현재 정상 영업 중이며 네이버 예약이 가능합니다. ({esc_phone})" />
  <meta name="keywords" content="{esc_name}, 미금역 맛집, 미금역 삼겹살, 미금역 목살, 미금역 고기집, 한돈인증점, 분당 회식, 특숙성목살, 제주젓갈볶음밥" />
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large" />
  <meta name="naver-site-verification" content="cca6d53f417e416768a481f304aa32b3e8eac501" />
  <link rel="canonical" href="{site_url}" />
  <link rel="icon" type="image/png" href="./img/favicon.png" />
  <link rel="apple-touch-icon" href="./img/favicon.png" />

  <meta property="og:type" content="restaurant.restaurant" />
  <meta property="og:locale" content="ko_KR" />
  <meta property="og:site_name" content="{esc_name}" />
  <meta property="og:title" content="{esc_name} — 프리미엄 숙성돼지 · 미금역" />
  <meta property="og:description" content="{esc_addr} · 한돈인증점 · 참숯 특숙성 돼지고기 · 네이버 예약 가능" />
  <meta property="og:url" content="{site_url}" />
  <meta property="og:image" content="{site_url}img/hero-exterior.jpg" />

  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css" />

  <script type="application/ld+json">
{jsonld_str}
  </script>

  <style>
    :root {{
      --bg: #FAF8F4;
      --bg-warm: #F2EEE6;
      --surface: #FFFFFF;
      --ink: #1C1A17;
      --ink-soft: #4A453E;
      --muted: #7A7369;
      --line: #E4DDD2;
      --line-dark: #CFC5B6;
      --seal: #A32920;
      --serif: 'Noto Serif KR', Georgia, serif;
      --sans: 'Pretendard Variable', 'Pretendard', -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      line-height: 1.7;
      word-break: keep-all;
      -webkit-font-smoothing: antialiased;
    }}
    img {{ display: block; max-width: 100%; height: auto; }}
    a {{ color: inherit; text-decoration: none; }}
    .container {{ max-width: 1080px; margin: 0 auto; padding: 0 24px; }}
    .notice-strip {{
      background: var(--ink);
      color: var(--bg);
      text-align: center;
      font-size: 0.84rem;
      padding: 8px 16px;
      letter-spacing: 0.01em;
    }}
    .topbar {{
      position: sticky;
      top: 0;
      z-index: 40;
      background: rgba(250, 248, 244, 0.92);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--line);
    }}
    .topbar-inner {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 66px;
      gap: 16px;
    }}
    .brand {{ display: flex; align-items: center; gap: 10px; }}
    .brand-seal-img {{ width: 34px; height: 34px; object-fit: contain; flex-shrink: 0; }}
    .handon-strip {{
      display: flex; align-items: center; gap: 14px;
      margin-top: 14px; padding: 12px 14px;
      background: var(--bg-warm); border: 1px solid var(--line);
    }}
    .handon-strip img {{ width: 52px; height: 52px; object-fit: contain; flex-shrink: 0; }}
    .handon-strip-title {{ font-family: var(--serif); font-size: 0.92rem; font-weight: 700; color: var(--ink); }}
    .handon-strip-sub {{ font-size: 0.8rem; color: var(--ink-soft); margin-top: 2px; }}
    .foot-brand-wrap {{ display: flex; align-items: center; gap: 12px; }}
    .foot-seal {{ width: 32px; height: 32px; object-fit: contain; }}
    .foot-handon {{ width: 34px; height: 34px; object-fit: contain; opacity: 0.92; }}
    .brand-name {{ font-family: var(--serif); font-size: 1.15rem; font-weight: 700; letter-spacing: 0.04em; }}
    .brand-en {{ font-size: 0.72rem; color: var(--muted); letter-spacing: 0.14em; text-transform: uppercase; margin-left: 2px; }}
    .nav-links {{ display: flex; align-items: center; gap: 26px; font-size: 0.9rem; color: var(--ink-soft); font-weight: 500; }}
    .nav-links a:hover {{ color: var(--ink); }}
    .nav-tel {{ font-size: 0.86rem; font-weight: 600; color: var(--ink); padding: 7px 14px; border: 1px solid var(--ink); transition: background 0.15s ease, color 0.15s ease; }}
    .nav-tel:hover {{ background: var(--ink); color: var(--bg); }}
    .hero {{ padding: 44px 0 64px; border-bottom: 1px solid var(--line); }}
    .hero-head {{ display: grid; grid-template-columns: 1.35fr 1fr; gap: 32px; align-items: end; margin-bottom: 30px; }}
    .eyebrow {{ font-size: 0.78rem; letter-spacing: 0.16em; text-transform: uppercase; color: var(--seal); font-weight: 700; margin-bottom: 12px; }}
    h1.hero-title {{ font-family: var(--serif); font-size: clamp(2rem, 4.2vw, 3.1rem); font-weight: 600; line-height: 1.28; letter-spacing: -0.02em; margin: 0; }}
    .hero-copy {{ font-size: 0.98rem; color: var(--ink-soft); margin: 0 0 20px; }}
    .hero-actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .btn-solid {{ display: inline-block; padding: 12px 22px; background: var(--ink); color: var(--bg); font-size: 0.9rem; font-weight: 600; letter-spacing: 0.02em; }}
    .btn-solid:hover {{ opacity: 0.86; }}
    .btn-outline {{ display: inline-block; padding: 12px 20px; border: 1px solid var(--line-dark); color: var(--ink); font-size: 0.9rem; font-weight: 500; }}
    .btn-outline:hover {{ border-color: var(--ink); background: var(--bg-warm); }}
    .hero-photo-wrap {{ position: relative; overflow: hidden; background: #1a1816; aspect-ratio: 16 / 9; }}
    .hero-photo-wrap img {{ width: 100%; height: 100%; object-fit: cover; object-position: center 62%; }}
    .hero-meta-bar {{ display: grid; grid-template-columns: repeat(3, 1fr); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); margin-top: 22px; }}
    .hero-meta-item {{ padding: 16px 18px; border-right: 1px solid var(--line); }}
    .hero-meta-item:last-child {{ border-right: none; }}
    .meta-k {{ font-size: 0.74rem; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 4px; font-weight: 600; }}
    .meta-v {{ font-size: 0.93rem; font-weight: 600; color: var(--ink); }}
    section.block {{ padding: 76px 0; border-bottom: 1px solid var(--line); }}
    .sec-head {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; margin-bottom: 40px; }}
    .sec-k {{ font-size: 0.75rem; letter-spacing: 0.16em; text-transform: uppercase; color: var(--seal); font-weight: 700; margin-bottom: 8px; }}
    .sec-h {{ font-family: var(--serif); font-size: clamp(1.55rem, 3vw, 2.1rem); font-weight: 600; letter-spacing: -0.02em; margin: 0; line-height: 1.3; }}
    .sec-note {{ font-size: 0.9rem; color: var(--muted); max-width: 380px; margin: 0; }}
    .craft-grid {{ display: grid; grid-template-columns: 1.05fr 0.95fr; gap: 36px; align-items: start; }}
    .craft-photo-tall {{ aspect-ratio: 4 / 5; overflow: hidden; background: var(--bg-warm); }}
    .craft-photo-tall img, .craft-photo-sq img {{ width: 100%; height: 100%; object-fit: cover; }}
    .craft-right {{ display: flex; flex-direction: column; gap: 28px; }}
    .craft-photo-sq {{ aspect-ratio: 4 / 3; overflow: hidden; background: var(--bg-warm); }}
    .craft-points {{ display: flex; flex-direction: column; gap: 20px; padding-top: 6px; }}
    .craft-point {{ padding-top: 16px; border-top: 1px solid var(--line); }}
    .craft-num {{ font-family: var(--serif); font-size: 0.85rem; color: var(--seal); font-weight: 700; margin-bottom: 4px; }}
    .craft-point h3 {{ font-family: var(--serif); font-size: 1.12rem; font-weight: 600; margin: 0 0 6px; }}
    .craft-point p {{ margin: 0; font-size: 0.92rem; color: var(--ink-soft); }}
    .menu-layout {{ display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 48px; align-items: start; }}
    .menu-group-title {{ font-family: var(--serif); font-size: 1.15rem; font-weight: 600; padding-bottom: 12px; border-bottom: 1.5px solid var(--ink); margin: 0 0 8px; display: flex; justify-content: space-between; align-items: baseline; }}
    .menu-group-title span {{ font-family: var(--sans); font-size: 0.78rem; color: var(--muted); font-weight: 500; }}
    .menu-list {{ list-style: none; margin: 0; padding: 0; }}
    .menu-row {{ display: flex; justify-content: space-between; align-items: baseline; gap: 16px; padding: 15px 0; border-bottom: 1px solid var(--line); }}
    .menu-row-left {{ flex: 1; }}
    .menu-item-name {{ font-size: 1.02rem; font-weight: 700; color: var(--ink); }}
    .menu-item-wt {{ font-size: 0.82rem; color: var(--muted); font-weight: 500; margin-left: 6px; }}
    .tag-rec {{ display: inline-block; margin-left: 8px; padding: 1px 7px; font-size: 0.72rem; font-weight: 700; color: var(--seal); border: 1px solid var(--seal); vertical-align: 1px; }}
    .menu-item-sub {{ font-size: 0.84rem; color: var(--muted); margin-top: 3px; }}
    .menu-item-price {{ font-family: var(--serif); font-size: 1.02rem; font-weight: 600; color: var(--ink); white-space: nowrap; }}
    .menu-side-photo {{ margin-top: 24px; background: var(--bg-warm); overflow: hidden; }}
    .menu-side-photo img {{ width: 100%; aspect-ratio: 4 / 3; object-fit: cover; }}
    .photo-cap {{ font-size: 0.8rem; color: var(--muted); padding: 10px 2px 0; background: var(--bg); }}
    .space-grid {{ display: grid; grid-template-columns: 1.35fr 0.85fr; gap: 20px; }}
    .space-box {{ overflow: hidden; background: var(--bg-warm); }}
    .space-box img {{ width: 100%; height: 100%; min-height: 320px; max-height: 440px; object-fit: cover; }}
    .visit-grid {{ display: grid; grid-template-columns: 1fr 1.05fr; gap: 48px; align-items: start; }}
    .info-dl {{ margin: 0; border-top: 1.5px solid var(--ink); }}
    .info-row {{ display: grid; grid-template-columns: 110px 1fr; gap: 14px; padding: 16px 0; border-bottom: 1px solid var(--line); font-size: 0.94rem; }}
    .info-row dt {{ color: var(--muted); font-weight: 600; }}
    .info-row dd {{ margin: 0; color: var(--ink); font-weight: 500; }}
    .map-links {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 22px; }}
    .faq-wrap {{ border-top: 1.5px solid var(--ink); }}
    details.faq {{ border-bottom: 1px solid var(--line); padding: 16px 0; }}
    details.faq summary {{ cursor: pointer; list-style: none; font-weight: 600; font-size: 0.96rem; display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
    details.faq summary::-webkit-details-marker {{ display: none; }}
    details.faq summary::after {{ content: "+"; font-family: var(--serif); font-size: 1.2rem; color: var(--muted); }}
    details.faq[open] summary::after {{ content: "−"; color: var(--seal); }}
    .faq-body {{ margin: 10px 0 0; font-size: 0.9rem; color: var(--ink-soft); line-height: 1.72; }}
    footer {{ padding: 36px 0 54px; background: var(--bg-warm); color: var(--muted); font-size: 0.84rem; }}
    .foot-inner {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 14px; }}
    .foot-brand {{ font-family: var(--serif); font-size: 0.98rem; font-weight: 700; color: var(--ink); }}
    @media (max-width: 860px) {{
      .nav-links {{ display: none; }}
      .hero-head, .craft-grid, .menu-layout, .space-grid, .visit-grid {{ grid-template-columns: 1fr; gap: 28px; }}
      .hero-meta-bar {{ grid-template-columns: 1fr; }}
      .hero-meta-item {{ border-right: none; border-bottom: 1px solid var(--line); }}
      .hero-meta-item:last-child {{ border-bottom: none; }}
      .sec-head {{ flex-direction: column; align-items: flex-start; gap: 8px; }}
      .craft-photo-tall {{ aspect-ratio: 4 / 3; }}
      section.block {{ padding: 54px 0; }}
    }}
  </style>
</head>
<body>
  {notice_banner}
  <nav class="topbar" aria-label="주요 메뉴">
    <div class="container topbar-inner">
      <a class="brand" href="#">
        <img class="brand-seal-img" src="./img/logo-seal.png" alt="{esc_name} 공식 로고" width="34" height="34" />
        <span class="brand-name">{esc_name}</span>
        <span class="brand-en">Bundang Grill</span>
      </a>
      <div class="nav-links">
        <a href="#story">이야기</a>
        <a href="#menu">차림표</a>
        <a href="#space">공간</a>
        <a href="#visit">오시는 길</a>
      </div>
      <a class="nav-tel" href="tel:{esc_phone}">{esc_phone}</a>
    </div>
  </nav>

  <header class="hero">
    <div class="container">
      <div class="hero-head">
        <div>
          <div class="eyebrow">ESTD 2018 · 한돈인증점 · MIGEUM BUNDANG</div>
          <h1 class="hero-title">프리미엄 숙성돼지,<br />참숯의 온도로 굽다.</h1>
        </div>
        <div>
          <p class="hero-copy">
            미금역 먹자골목에 자리한 공식 한돈인증점 <strong>{esc_name}</strong>은
            엄선한 100% 국내산 특숙성 한돈을 참숯의 깊은 화력으로 선보이는 구이 전문점입니다.
          </p>
          <div class="hero-actions">
            <a class="btn-solid" href="https://m.place.naver.com/restaurant/1699124309/booking?entry=pll&bk_query=%EB%B6%84%EB%8B%B9%EA%B7%B8%EB%A6%B4" target="_blank" rel="noopener">네이버 예약하기</a>
            <a class="btn-outline" href="tel:{esc_phone}">전화 문의</a>
            <a class="btn-outline" href="https://place.map.kakao.com/865459727" target="_blank" rel="noopener">카카오맵</a>
            <a class="btn-outline" href="https://www.instagram.com/bdgrill0524/" target="_blank" rel="noopener">인스타그램</a>
          </div>
        </div>
      </div>

      <figure class="hero-photo-wrap" style="margin:0;">
        <img src="./img/hero-exterior.jpg" alt="{esc_name} 저녁 매장 전경" width="1600" height="1194" fetchpriority="high" />
      </figure>

      <div class="hero-meta-bar">
        <div class="hero-meta-item">
          <div class="meta-k">위치</div>
          <div class="meta-v">{esc_addr}</div>
        </div>
        <div class="hero-meta-item">
          <div class="meta-k">영업시간 (라스트오더 21:30)</div>
          <div class="meta-v">평일 {esc_wk} · 주말 {esc_wknd} (B.T {esc_bt})</div>
        </div>
        <div class="hero-meta-item">
          <div class="meta-k">문의 및 결제</div>
          <div class="meta-v">{esc_phone} · 성남사랑상품권(chak) · 성남시 아동수당 카드</div>
        </div>
      </div>
    </div>
  </header>

  <main>
    <section id="story" class="block">
      <div class="container">
        <div class="sec-head">
          <div>
            <div class="sec-k">Craft &amp; Philosophy</div>
            <h2 class="sec-h">좋은 원육, 깊은 숯불, 편안한 식사</h2>
          </div>
          <p class="sec-note">엄선한 국내산 한돈과 깊은 참숯으로, 가족 외식부터 모임까지 만족스러운 한 끼를 완성합니다.</p>
        </div>

        <div class="craft-grid">
          <div>
            <div class="craft-photo-tall">
              <img src="./img/meat-cuts.jpg" alt="{esc_name} 특숙성목살과 특숙성삼겹살 원육 단면" width="1400" height="1866" loading="lazy" />
            </div>
            <div class="photo-cap">두툼하게 손질한 {esc_name} 시그니처 특숙성 원육</div>
          </div>

          <div class="craft-right">
            <div>
              <div class="craft-photo-sq">
                <img src="./img/charcoal.jpg" alt="{esc_name} 테이블 화로에 담긴 참숯" width="1200" height="1214" loading="lazy" />
              </div>
              <div class="photo-cap">화력과 은은한 향이 살아있는 참숯 화로</div>
            </div>

            <div class="craft-points">
              <div class="craft-point">
                <div class="craft-num">01</div>
                <h3>한돈인증점 · 최상급 특숙성 원육</h3>
                <p>육즙이 풍부한 특숙성목살과 특숙성삼겹살부터 갈매기살·가브리살·꼬들살까지, 매일 선별한 최상의 국내산 한돈만을 상에 올립니다.</p>
                <div class="handon-strip">
                  <img src="./img/handon.png" alt="우리돼지 한돈 공식 인증점 마크" width="52" height="52" loading="lazy" />
                  <div>
                    <div class="handon-strip-title">한돈자조금관리위원회 공식 한돈인증점</div>
                    <div class="handon-strip-sub">엄격한 심사를 통과한 100% 국내산 한돈 전문 매장입니다.</div>
                  </div>
                </div>
              </div>
              <div class="craft-point">
                <div class="craft-num">02</div>
                <h3>참숯의 깊은 화력</h3>
                <p>화력이 균일하고 은은한 향이 살아있는 참숯을 사용해, 두툼한 특숙성 한돈의 겉은 바삭하고 속은 육즙이 가득하게 구워냅니다.</p>
              </div>
              <div class="craft-point">
                <div class="craft-num">03</div>
                <h3>고기 맛을 완성하는 찬과 식사</h3>
                <p>파김치, 묵은지, 동치미, 젓갈류 등 깔끔한 밑반찬과 시그니처 제주젓갈볶음밥·등뼈김치찌개로 식사의 마무리를 채웁니다.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section id="menu" class="block">
      <div class="container">
        <div class="sec-head">
          <div>
            <div class="sec-k">Menu</div>
            <h2 class="sec-h">{esc_name} 차림표</h2>
          </div>
          <p class="sec-note">모든 구이 메뉴는 1인분 기준이며, 원육 수급 상황에 따라 일부 특수부위는 조기 품절될 수 있습니다.</p>
        </div>

        <div class="menu-layout">
          <div>
            <h3 class="menu-group-title">구이 <span>숙성 돼지고기</span></h3>
            <ul class="menu-list">
{_build_menu_li(grill_df)}
            </ul>
          </div>

          <div>
            <h3 class="menu-group-title">더하기 <span>식사 · 사이드</span></h3>
            <ul class="menu-list">
{_build_menu_li(side_df)}
            </ul>

            <figure class="menu-side-photo" style="margin:24px 0 0;">
              <img src="./img/fried-rice.jpg" alt="{esc_name} 시그니처 식사 메뉴 제주젓갈볶음밥" width="800" height="600" loading="lazy" />
              <figcaption class="photo-cap">식사 주문 1순위, 제주젓갈볶음밥</figcaption>
            </figure>
          </div>
        </div>
      </div>
    </section>

    <section id="space" class="block">
      <div class="container">
        <div class="sec-head">
          <div>
            <div class="sec-k">Space</div>
            <h2 class="sec-h">미금역 먹자골목, 편안한 모임의 공간</h2>
          </div>
          <p class="sec-note">따뜻한 원목 테이블과 쾌적한 환기 시설로 직장 회식부터 가족 외식까지 편안하게 머무실 수 있습니다.</p>
        </div>

        <div class="space-grid">
          <figure style="margin:0;">
            <div class="space-box">
              <img src="./img/interior.jpg" alt="{esc_name} 매장 내부 원목 테이블과 깔끔한 홀 전경" width="993" height="712" loading="lazy" />
            </div>
            <figcaption class="photo-cap">여유로운 테이블 간격의 {esc_name} 홀 내부</figcaption>
          </figure>
          <figure style="margin:0;">
            <div class="space-box">
              <img src="./img/exterior-sign.jpg" alt="{esc_name} 미금역 매장 외관 및 세로 간판" width="1000" height="1105" loading="lazy" />
            </div>
            <figcaption class="photo-cap">미금일로 74번길 13-3, {esc_name} 매장 입구</figcaption>
          </figure>
        </div>
      </div>
    </section>

    <section id="visit" class="block" style="border-bottom:none;">
      <div class="container">
        <div class="sec-head">
          <div>
            <div class="sec-k">Information</div>
            <h2 class="sec-h">오시는 길 및 이용 안내</h2>
          </div>
          <p class="sec-note">단체 방문이나 웨이팅 현황은 매장 전화로 문의해 주시면 빠르게 안내해 드립니다.</p>
        </div>

        <div class="visit-grid">
          <div>
            <dl class="info-dl">
              <div class="info-row">
                <dt>매장 주소</dt>
                <dd>{esc_addr}</dd>
              </div>
              <div class="info-row">
                <dt>영업시간</dt>
                <dd>
                  평일 (월–금) {esc_wk}<br />
                  주말 (토–일) {esc_wknd}<br />
                  <span style="color:var(--muted); font-size:0.86rem;">주말 브레이크타임 {esc_bt} · 라스트오더 21:30</span>
                </dd>
              </div>
              <div class="info-row">
                <dt>좌석 · 편의</dt>
                <dd>단체 회식 최대 50명 가능 · 아기의자 보유</dd>
              </div>
              <div class="info-row">
                <dt>주차 안내</dt>
                <dd>매장 앞 3대 가능 (피크 시간대 만석 시 인근 주변 도로 주차 이용)</dd>
              </div>
              <div class="info-row">
                <dt>전화번호</dt>
                <dd><a href="tel:{esc_phone}" style="text-decoration:underline; text-underline-offset:3px;">{esc_phone}</a></dd>
              </div>
              <div class="info-row">
                <dt>결제 수단</dt>
                <dd>신용카드 · 체크카드 · 현금 · 계좌이체 · 성남사랑상품권(chak) · 성남시 아동수당 카드 가맹점</dd>
              </div>
            </dl>

            <div class="map-links">
              <a class="btn-solid" href="https://m.place.naver.com/restaurant/1699124309/booking?entry=pll&bk_query=%EB%B6%84%EB%8B%B9%EA%B7%B8%EB%A6%B4" target="_blank" rel="noopener">네이버 예약하기</a>
              <a class="btn-outline" href="https://m.place.naver.com/restaurant/1699124309/home" target="_blank" rel="noopener">네이버 플레이스</a>
              <a class="btn-outline" href="https://place.map.kakao.com/865459727" target="_blank" rel="noopener">카카오맵</a>
              <a class="btn-outline" href="https://www.google.co.kr/maps/place/%EB%B6%84%EB%8B%B9%EA%B7%B8%EB%A6%B4/data=!4m10!1m5!3m4!1s0x357b59b100565c6d:0x67c1a9bc2df02953!2z67aE64u56re466a0!16s%2Fg%2F11h6ql4_yk!20s8Q9984W6%2BPFG!3m3!1s0x357b59b100565c6d:0x67c1a9bc2df02953!16s%2Fg%2F11h6ql4_yk!20s8Q9984W6%2BPFG" target="_blank" rel="noopener">구글 지도</a>
              <a class="btn-outline" href="https://www.instagram.com/bdgrill0524/" target="_blank" rel="noopener">인스타그램</a>
            </div>
          </div>

          <div class="faq-wrap">
            <details class="faq" open>
              <summary>{esc_name}은 현재 정상 영업 중인가요? 라스트오더는 몇 시인가요?</summary>
              <p class="faq-body">
                네, {esc_addr}에서 변함없이 정상 영업 중입니다.
                평일 {esc_wk}, 주말 {esc_wknd}(브레이크타임 {esc_bt}) 운영하며 <strong>라스트오더는 21:30</strong>입니다.
              </p>
            </details>
            <details class="faq">
              <summary>{esc_name}은 한돈인증점인가요? 어떤 원육을 사용하나요?</summary>
              <p class="faq-body">
                네, {esc_name}은 한돈자조금관리위원회의 엄격한 심사를 통과한 공식 한돈인증점입니다.
                100% 국내산 최상급 한돈만을 선별해 특숙성 과정을 거쳐 제공합니다.
              </p>
            </details>
            <details class="faq">
              <summary>주차는 어떻게 이용하나요?</summary>
              <p class="faq-body">
                매장 앞에 3대 주차가 가능하나 피크 시간대에는 만석인 경우가 많아, 인근 주변 도로 주차 공간을 이용해 주셔야 합니다.
              </p>
            </details>
            <details class="faq">
              <summary>단체 회식(최대 인원) · 아기의자 · 결제 수단이 궁금합니다.</summary>
              <p class="faq-body">
                단체 회식은 <strong>최대 50명까지</strong> 수용 가능하며, <strong>아기의자</strong>도 구비되어 있습니다.
                네이버 예약 또는 매장 전화({esc_phone})로 사전 문의해 주세요.
                성남사랑상품권(chak)과 성남시 아동수당 카드 가맹점으로 모두 정상 결제 가능합니다.
              </p>
            </details>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="container foot-inner">
      <div class="foot-brand-wrap">
        <img class="foot-seal" src="./img/logo-seal.png" alt="{esc_name} 로고" width="32" height="32" />
        <div class="foot-brand">{esc_name} · BUNDANG GRILL <span style="font-weight:500; color:var(--muted); font-size:0.8rem;">ESTD 2018</span></div>
        <img class="foot-handon" src="./img/handon.png" alt="한돈인증점" width="34" height="34" />
      </div>
      <div>{esc_addr} · Tel. {esc_phone}</div>
    </div>
  </footer>
</body>
</html>
"""

    # llms.txt 생성
    grill_md = "\n".join(
        f"- {r['메뉴명']}" + (f" ({r['중량']})" if str(r['중량']).strip() else "") + f": {_clean_int(r['가격']):,}원"
        for _, r in grill_df.iterrows()
    )
    side_md = "\n".join(
        f"- {r['메뉴명']}: {_clean_int(r['가격']):,}원"
        for _, r in side_df.iterrows()
    )
    today_iso = datetime.datetime.now(KST).strftime("%Y-%m-%d")

    llms_txt = f"""# {store_name} (Bundang Grill) — 공식 매장 정보

> {address}에 위치한 공식 한돈인증점 · 프리미엄 숙성 돼지고기 참숯 구이 전문점 **{store_name}**의 공식 안내 문서입니다.
> **영업 상태: 현재 정상 영업 중 (폐업 아님, 최신 업데이트 {today_iso})**

## 기본 정보 (NAP)
- 상호명: {store_name} (Bundang Grill, ESTD 2018)
- 인증: 한돈자조금관리위원회 공식 한돈인증점 (100% 국내산 한돈 전문)
- 영업 상태: **정상 영업 중 (Open)**
- 주소: {address}
- 전화번호: {phone}
- 평일 영업시간 (월~금): {weekday_hours} (라스트오더 21:30)
- 주말 영업시간 (토~일): {weekend_hours} (브레이크타임 {break_time}, 라스트오더 21:30)
- 좌석 및 편의: 단체 회식 최대 50명 가능, 아기의자 보유
- 주차 안내: 매장 앞 3대 가능 (만석 시 인근 주변 도로 주차 이용)
- 결제수단: 신용카드, 체크카드, 현금, 계좌이체, 성남사랑상품권(chak), 성남시 아동수당 카드 가맹점
- 공식 웹페이지: {site_url}
- 네이버 예약: https://m.place.naver.com/restaurant/1699124309/booking?entry=pll&bk_query=%EB%B6%84%EB%8B%B9%EA%B7%B8%EB%A6%B4
- 네이버 플레이스: https://m.place.naver.com/restaurant/1699124309/home
- 인스타그램: https://www.instagram.com/bdgrill0524/
- 카카오맵: https://place.map.kakao.com/865459727
- 구글맵: https://www.google.co.kr/maps/place/%EB%B6%84%EB%8B%B9%EA%B7%B8%EB%A6%B4/data=!4m10!1m5!3m4!1s0x357b59b100565c6d:0x67c1a9bc2df02953!2z67aE64u56re466a0!16s%2Fg%2F11h6ql4_yk!20s8Q9984W6%2BPFG!3m3!1s0x357b59b100565c6d:0x67c1a9bc2df02953!16s%2Fg%2F11h6ql4_yk!20s8Q9984W6%2BPFG

## 공식 차림표 및 가격
### 구이 (숙성 돼지고기)
{grill_md}

### 더하기 (식사 · 사이드)
{side_md}

## 자주 묻는 질문 (FAQ)
- **Q. {store_name}은 폐업했나요? 현재 영업 중인가요?**
  - A. 폐업하지 않았으며, {address}에서 현재 정상 영업 중입니다.
- **Q. {store_name}은 한돈인증점인가요?**
  - A. 네, 한돈자조금관리위원회 공식 한돈인증점으로 100% 국내산 최상급 한돈만을 선별해 특숙성하여 제공합니다.
- **Q. 예약 및 단체 회식이 가능한가요?**
  - A. 매장 전화({phone})로 사전 문의 시 좌석 및 단체 회식 안내를 도와드립니다.
"""

    sitemap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{site_url}</loc>
    <lastmod>{today_iso}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{site_url}llms.txt</loc>
    <lastmod>{today_iso}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
"""

    return {
        "index.html": index_html,
        "llms.txt": llms_txt,
        "sitemap.xml": sitemap_xml,
    }


def push_files_to_github(
    token: str,
    repo: str,
    branch: str,
    files_map: dict[str, str],
    commit_message: str = "chore: 통합관리시스템에서 홈페이지 차림표·정보 업데이트",
) -> tuple[bool, str]:
    """GitHub Contents API로 docs/index.html, docs/llms.txt, docs/sitemap.xml을 순차 커밋."""
    token = str(token or "").strip() or get_secret("GITHUB_TOKEN", "")
    if not token:
        return False, "GitHub 토큰(PAT)이 설정되어 있지 않습니다."

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    updated = []
    for rel_path, content_str in files_map.items():
        api_url = f"https://api.github.com/repos/{repo}/contents/{rel_path}"
        # 기존 파일 sha 조회
        sha = None
        r_get = requests.get(api_url, headers=headers, params={"ref": branch}, timeout=12)
        if r_get.status_code == 200:
            sha = r_get.json().get("sha")
        elif r_get.status_code not in (404,):
            return False, f"{rel_path} 조회 실패 (HTTP {r_get.status_code}): {r_get.text[:200]}"

        payload = {
            "message": commit_message,
            "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        r_put = requests.put(api_url, headers=headers, json=payload, timeout=15)
        if r_put.status_code not in (200, 201):
            return False, f"{rel_path} 반영 실패 (HTTP {r_put.status_code}): {r_put.text[:200]}"
        updated.append(rel_path)

    return True, f"GitHub 반영 완료 ({', '.join(updated)}) — 1~2분 후 홈페이지에 자동 적용됩니다."
