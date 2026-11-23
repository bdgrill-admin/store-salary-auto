"""
================================================================================
[파일명] ui_styles.py
[역할] 전 페이지 공용 반응형 CSS 및 기능별 컬러 구분 UI 컴포넌트 모듈
[주요 기능]
  1. 모바일·태블릿·반화면·와이드 PC 대응 반응형 레이아웃 (컬럼 찌그러짐·세로 줄바꿈 방지)
  2. 기능별 컬러 코딩 섹션 헤더 (emerald / blue / amber / indigo / rose / slate)
  3. 시인성 높은 알약형(Pill) 탭, 카드형 컨테이너, 한글 단어 단위 줄바꿈(keep-all) 적용
================================================================================
"""

import streamlit as st

ACCENT_PALETTE = {
    "emerald": {
        "bar": "#059669",
        "bg": "#ECFDF5",
        "border": "#A7F3D0",
        "text": "#065F46",
        "badge_bg": "#D1FAE5",
    },
    "blue": {
        "bar": "#2563EB",
        "bg": "#EFF6FF",
        "border": "#BFDBFE",
        "text": "#1E3A8A",
        "badge_bg": "#DBEAFE",
    },
    "amber": {
        "bar": "#D97706",
        "bg": "#FFFBEB",
        "border": "#FDE68A",
        "text": "#92400E",
        "badge_bg": "#FEF3C7",
    },
    "indigo": {
        "bar": "#4F46E5",
        "bg": "#EEF2FF",
        "border": "#C7D2FE",
        "text": "#3730A3",
        "badge_bg": "#E0E7FF",
    },
    "rose": {
        "bar": "#E11D48",
        "bg": "#FFF1F2",
        "border": "#FECDD3",
        "text": "#9F1239",
        "badge_bg": "#FFE4E6",
    },
    "slate": {
        "bar": "#334155",
        "bg": "#F8FAFC",
        "border": "#CBD5E1",
        "text": "#0F172A",
        "badge_bg": "#E2E8F0",
    },
}


def apply_base_theme(max_width: int = 1360):
    """전 페이지 공통 반응형 스타일 및 시인성 강화 테마를 주입합니다."""
    st.markdown(
        f"""
        <style>
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

        html, body, [class*="css"] {{
            font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
            word-break: keep-all;
            overflow-wrap: break-word;
        }}

        /* 메인 컨테이너 반응형 여백 */
        .block-container {{
            padding-top: 2.3rem !important;
            padding-bottom: 3rem !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            max-width: {max_width}px !important;
        }}

        /* 페이지 상단 헤더 바 */
        .page-hero {{
            background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
            color: #FFFFFF;
            border-radius: 14px;
            padding: 1rem 1.35rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08);
        }}
        .page-hero-title {{
            font-size: 1.42rem;
            font-weight: 800;
            color: #FFFFFF;
            margin: 0;
            line-height: 1.25;
            letter-spacing: -0.02em;
        }}
        .page-hero-sub {{
            font-size: 0.86rem;
            color: #CBD5E1;
            margin-top: 0.25rem;
            line-height: 1.4;
        }}

        .app-title {{
            font-size: 1.5rem;
            font-weight: 800;
            color: #0F172A;
            margin: 0;
            line-height: 1.25;
            letter-spacing: -0.02em;
        }}
        .app-subtitle {{
            font-size: 0.88rem;
            font-weight: 600;
            color: #475569;
            margin: 0.35rem 0 0.25rem 0;
        }}

        /* 기능별 뚜렷한 섹션 헤더 배너 */
        .sec-banner {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 0.45rem;
            padding: 0.62rem 0.9rem;
            margin: 1.05rem 0 0.55rem 0;
            border-radius: 10px;
            border: 1px solid #CBD5E1;
            border-left-width: 5px;
            background-color: #F8FAFC;
        }}
        .sec-banner-left {{
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}
        .sec-banner-title {{
            font-size: 1.02rem;
            font-weight: 800;
            letter-spacing: -0.015em;
            line-height: 1.3;
        }}
        .sec-banner-badge {{
            font-size: 0.74rem;
            font-weight: 700;
            padding: 0.16rem 0.55rem;
            border-radius: 999px;
            white-space: nowrap;
        }}
        .sec-banner-sub {{
            font-size: 0.8rem;
            color: #475569;
            line-height: 1.35;
        }}

        /* 기존 section-title 클래스 호환 (깔끔하게 업그레이드) */
        .section-title {{
            font-size: 1.03rem;
            font-weight: 800;
            color: #0F172A;
            background-color: #F1F5F9;
            border: 1px solid #E2E8F0;
            border-left: 5px solid #2563EB;
            border-radius: 9px;
            padding: 0.52rem 0.85rem;
            margin: 0.95rem 0 0.55rem 0;
            line-height: 1.3;
        }}
        .mgr-section-title {{
            font-size: 1.03rem;
            font-weight: 800;
            color: #92400E;
            background-color: #FFFBEB;
            border: 1px solid #FDE68A;
            border-left: 5px solid #D97706;
            border-radius: 9px;
            padding: 0.52rem 0.85rem;
            margin: 0.95rem 0 0.55rem 0;
            line-height: 1.3;
        }}

        /* 카드형 bordered container 시인성 강화 */
        div[data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius: 12px !important;
            border-color: #CBD5E1 !important;
            background-color: #FFFFFF;
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
        }}

        /* 매니저 전용 박스 강조 */
        div[data-testid="stVerticalBlock"]:has(> div.element-container > div.stMarkdown > div.mgr-box-marker) {{
            background-color: #FFFDF5;
            border: 1.5px solid #F59E0B;
            border-radius: 12px;
            padding: 0.9rem 1rem;
        }}

        /* 입금 확인 패널 강조 (에메랄드 톤) */
        div[data-testid="stExpander"] {{
            border-radius: 12px !important;
            border: 1.5px solid #CBD5E1 !important;
            background-color: #FFFFFF !important;
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
            margin-bottom: 0.75rem;
        }}
        div[data-testid="stExpander"] summary {{
            font-weight: 700 !important;
            font-size: 0.96rem !important;
            padding: 0.65rem 0.9rem !important;
        }}
        .pay-panel-wrap div[data-testid="stExpander"] {{
            border: 1.5px solid #10B981 !important;
            background-color: #F0FDF4 !important;
        }}

        /* 탭(st.tabs) 알약형 시인성 개선 + 가로 스크롤 지원 */
        div[data-baseweb="tab-list"] {{
            gap: 0.45rem !important;
            background-color: #F1F5F9;
            padding: 0.35rem;
            border-radius: 11px;
            overflow-x: auto !important;
            flex-wrap: nowrap !important;
            scrollbar-width: thin;
        }}
        button[data-baseweb="tab"] {{
            border-radius: 8px !important;
            padding: 0.48rem 0.95rem !important;
            font-size: 0.9rem !important;
            font-weight: 700 !important;
            color: #475569 !important;
            background-color: transparent !important;
            white-space: nowrap !important;
            flex-shrink: 0 !important;
            border: none !important;
        }}
        button[data-baseweb="tab"][aria-selected="true"] {{
            background-color: #0F172A !important;
            color: #FFFFFF !important;
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.18);
        }}
        div[data-baseweb="tab-highlight"] {{
            display: none !important;
        }}

        /* Metric 카드 시인성 강화 */
        div[data-testid="stMetric"] {{
            background-color: #FFFFFF;
            border: 1px solid #CBD5E1;
            border-top: 4px solid #2563EB;
            border-radius: 11px;
            padding: 0.8rem 1rem;
            box-shadow: 0 1px 4px rgba(15, 23, 42, 0.04);
        }}
        div[data-testid="stMetric"] label {{
            font-size: 0.82rem !important;
            font-weight: 700 !important;
            color: #475569 !important;
        }}
        div[data-testid="stMetricValue"] {{
            font-size: 1.28rem !important;
            font-weight: 800 !important;
            color: #0F172A !important;
        }}

        /* 버튼 텍스트 깨짐(세로 줄바꿈) 방지 */
        .stButton > button,
        .stFormSubmitButton > button,
        .stDownloadButton > button,
        .stLinkButton > a {{
            border-radius: 9px !important;
            font-weight: 700 !important;
            min-height: 2.55rem !important;
            word-break: keep-all !important;
            white-space: normal !important;
            line-height: 1.3 !important;
        }}

        /* 컬럼 기본 간격 정리 */
        div[data-testid="stHorizontalBlock"] {{
            gap: 0.75rem !important;
        }}

        /* ===== 반응형 브레이크포인트 1: 반화면 / 태블릿 (1100px 이하) ===== */
        @media (max-width: 1100px) {{
            .block-container {{
                padding-left: 1rem !important;
                padding-right: 1rem !important;
                padding-top: 2rem !important;
            }}
            div[data-testid="stHorizontalBlock"] {{
                flex-wrap: wrap !important;
            }}
            div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"],
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{
                min-width: min(100%, 240px) !important;
                flex: 1 1 240px !important;
            }}
            .page-hero-title, .app-title {{
                font-size: 1.32rem !important;
            }}
            div[data-testid="stMetricValue"] {{
                font-size: 1.15rem !important;
            }}
        }}

        /* ===== 반응형 브레이크포인트 2: 모바일 (640px 이하) ===== */
        @media (max-width: 640px) {{
            .block-container {{
                padding-left: 0.65rem !important;
                padding-right: 0.65rem !important;
                padding-top: 1.6rem !important;
            }}
            div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"],
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{
                min-width: 100% !important;
                flex: 1 1 100% !important;
                width: 100% !important;
            }}
            .page-hero {{
                padding: 0.85rem 1rem !important;
            }}
            .page-hero-title, .app-title {{
                font-size: 1.2rem !important;
            }}
            .sec-banner {{
                padding: 0.55rem 0.75rem !important;
            }}
            .sec-banner-title {{
                font-size: 0.95rem !important;
            }}
            button[data-baseweb="tab"] {{
                padding: 0.42rem 0.72rem !important;
                font-size: 0.84rem !important;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_section_banner(title: str, badge: str = "", subtitle: str = "", accent: str = "blue"):
    """기능별 색상이 뚜렷하게 구분되는 섹션 헤더 배너를 출력합니다."""
    p = ACCENT_PALETTE.get(accent, ACCENT_PALETTE["blue"])
    badge_html = (
        f'<span class="sec-banner-badge" style="background:{p["badge_bg"]}; color:{p["text"]};">{badge}</span>'
        if badge
        else ""
    )
    sub_html = f'<div class="sec-banner-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f"""
        <div class="sec-banner" style="background:{p['bg']}; border-color:{p['border']}; border-left-color:{p['bar']};">
            <div class="sec-banner-left">
                <span class="sec-banner-title" style="color:{p['text']};">{title}</span>
                {badge_html}
            </div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
