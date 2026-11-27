"""
================================================================================
[파일명] views/homepage.py
[역할] 공식 AEO/GEO 홈페이지 차림표(메뉴) · 영업정보 편집 및 GitHub Pages 원클릭 배포 페이지
[주요 기능]
  1. 차림표(구이/더하기) 메뉴명·중량·가격·설명·사장님추천·표시여부 편집 및 구글 시트('홈페이지_메뉴') 저장
  2. 영업시간·브레이크타임·상단 공지 배너 관리
  3. 정적 HTML(JSON-LD 포함) · llms.txt · sitemap.xml 자동 생성 및 GitHub Pages 원클릭 즉시 배포
================================================================================
"""

import streamlit as st
import streamlit.components.v1 as components

from store_registry import (
    load_all_stores,
    load_store_settings,
    save_store_settings,
    get_secret,
)
from ui_styles import apply_base_theme, render_section_banner
from homepage_utils import (
    load_homepage_menu,
    save_homepage_menu,
    render_homepage_files,
    push_files_to_github,
)

STORES = load_all_stores()
apply_base_theme(max_width=1360)

# =========================================================================
# 1. 상단 헤더 & 관리자 인증
# =========================================================================
h1, h2 = st.columns([3.2, 1.0], vertical_alignment="center")
with h1:
    st.markdown(
        """
        <div style="padding:0.1rem 0 0.4rem 0;">
            <div class="app-title">▪&nbsp;&nbsp;홈페이지 · 차림표 관리</div>
            <div class="app-subtitle">메뉴·가격 변경 시 통합관리시스템에서 수정하고 공식 홈페이지(AEO/GEO)에 즉시 반영</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with h2:
    selected_store = st.selectbox("관리 매장", list(STORES.keys()), index=0, key="hp_store_sel")

store_cfg = STORES[selected_store]
app_cfg = load_store_settings(store_cfg["db_id"], selected_store)
admin_pw = str(app_cfg.get("admin_password", "0524")).strip()

auth_key = f"hp_auth_{selected_store}"
if not (st.session_state.get(auth_key, False) or st.session_state.get("authenticated", False)):
    with st.container(border=True):
        st.markdown(f"#### 🔒 [{selected_store}] 홈페이지 관리자 인증")
        st.caption("공식 홈페이지 차림표 및 매장 정보 수정을 위해 관리자 비밀번호를 입력하세요.")
        with st.form("hp_login_form", clear_on_submit=True):
            pw_in = st.text_input("관리자 비밀번호", type="password")
            if st.form_submit_button("인증하기", type="primary", use_container_width=True):
                if pw_in.strip() == admin_pw:
                    st.session_state[auth_key] = True
                    st.rerun()
                else:
                    st.error("비밀번호가 일치하지 않습니다.")
    st.stop()


# =========================================================================
# 2. 데이터 로드
# =========================================================================
df_menu = load_homepage_menu(store_cfg["db_id"])

site_url_def = app_cfg.get("hp_site_url", "https://bdgrill-admin.github.io/store-salary-auto/")
repo_def = app_cfg.get("hp_github_repo", "bdgrill-admin/store-salary-auto")
branch_def = app_cfg.get("hp_github_branch", "main")
wk_def = app_cfg.get("hp_weekday_hours", "16:00 – 22:00")
wknd_def = app_cfg.get("hp_weekend_hours", "12:00 – 22:00")
bt_def = app_cfg.get("hp_break_time", "15:00 – 17:00")
notice_def = app_cfg.get("hp_notice", "")
saved_token = app_cfg.get("hp_github_token", "") or get_secret("GITHUB_TOKEN", "")

tab_edit, tab_deploy = st.tabs([
    "1. 차림표 · 매장정보 편집",
    "2. 홈페이지 미리보기 · 배포 설정",
])

with tab_edit:
    render_section_banner(
        "A. 공식 홈페이지 차림표 편집",
        badge=f"표시 중 {int(df_menu['표시'].sum())}개 / 전체 {len(df_menu)}개",
        subtitle="네이버 플레이스 최신 메뉴판에 맞춰 메뉴명·중량·가격을 수정하거나, 품절 메뉴는 [표시] 체크를 해제하세요.",
        accent="amber",
    )
    ed_menu = st.data_editor(
        df_menu,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "분류": st.column_config.SelectboxColumn("분류", options=["구이", "더하기"], width="small"),
            "메뉴명": st.column_config.TextColumn("메뉴명", width="medium"),
            "중량": st.column_config.TextColumn("중량 (예: 180g)", width="small"),
            "가격": st.column_config.NumberColumn("가격", format="%,d원", step=500, min_value=0),
            "설명": st.column_config.TextColumn("한 줄 설명", width="large"),
            "추천": st.column_config.CheckboxColumn("사장님추천", width="small"),
            "표시": st.column_config.CheckboxColumn("표시", width="small"),
            "정렬순서": st.column_config.NumberColumn("순서", format="%d", step=10, width="small"),
        },
        key=f"hp_menu_editor_{selected_store}",
    )

    render_section_banner(
        "B. 매장 기본 정보 & 상단 공지 배너",
        badge="영업시간 · 휴무 공지",
        subtitle="명절 휴무·임시 영업시간 변경 등 알릴 내용이 있을 때 [상단 공지]에 입력하면 홈페이지 맨 위에 표시됩니다.",
        accent="slate",
    )
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        in_wk = c1.text_input("평일 영업시간", value=wk_def, key="hp_in_wk")
        in_wknd = c2.text_input("주말 영업시간", value=wknd_def, key="hp_in_wknd")
        in_bt = c3.text_input("주말 브레이크타임", value=bt_def, key="hp_in_bt")

        c4, c5 = st.columns([1.4, 1.0])
        in_addr = c4.text_input(
            "매장 주소",
            value=app_cfg.get("store_address", "경기도 성남시 분당구 미금일로 74번길 13-3, 1층"),
            key="hp_in_addr",
        )
        in_phone = c5.text_input(
            "전화번호",
            value=app_cfg.get("store_phone", "031-713-0342"),
            key="hp_in_phone",
        )
        in_notice = st.text_input(
            "상단 한 줄 공지 (비워두면 표시되지 않음)",
            value=notice_def,
            placeholder="예: 12월 연말 단체 회식 예약 접수 중입니다 (031-713-0342)",
            key="hp_in_notice",
        )

    info_payload = {
        "site_url": site_url_def,
        "store_name": app_cfg.get("store_title", selected_store),
        "address": in_addr,
        "phone": in_phone,
        "weekday_hours": in_wk,
        "weekend_hours": in_wknd,
        "break_time": in_bt,
        "notice": in_notice,
    }

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        if st.button("💾 구글 시트에만 저장 (임시 저장)", use_container_width=True, key="hp_btn_save_sheet"):
            with st.spinner("구글 시트에 차림표 및 매장 정보를 저장 중..."):
                save_homepage_menu(store_cfg["db_id"], ed_menu)
                new_cfg = dict(app_cfg)
                new_cfg.update({
                    "hp_weekday_hours": in_wk.strip(),
                    "hp_weekend_hours": in_wknd.strip(),
                    "hp_break_time": in_bt.strip(),
                    "hp_notice": in_notice.strip(),
                    "store_address": in_addr.strip(),
                    "store_phone": in_phone.strip(),
                })
                save_store_settings(store_cfg["db_id"], new_cfg)
            st.cache_data.clear()
            st.success("구글 시트에 저장 완료! 홈페이지에 반영하려면 오른쪽 [즉시 반영] 버튼을 누르세요.")

    with b2:
        if st.button("🚀 저장 및 공식 홈페이지 즉시 반영 (GitHub 자동 배포)", type="primary", use_container_width=True, key="hp_btn_deploy"):
            with st.spinner("구글 시트 저장 및 공식 홈페이지(HTML·JSON-LD·llms.txt) 자동 배포 중..."):
                save_homepage_menu(store_cfg["db_id"], ed_menu)
                new_cfg = dict(app_cfg)
                new_cfg.update({
                    "hp_weekday_hours": in_wk.strip(),
                    "hp_weekend_hours": in_wknd.strip(),
                    "hp_break_time": in_bt.strip(),
                    "hp_notice": in_notice.strip(),
                    "store_address": in_addr.strip(),
                    "store_phone": in_phone.strip(),
                })
                save_store_settings(store_cfg["db_id"], new_cfg)

                gen = render_homepage_files(ed_menu, info_payload)
                ok, msg = push_files_to_github(
                    token=saved_token,
                    repo=repo_def,
                    branch=branch_def,
                    files_map={
                        "docs/index.html": gen["index.html"],
                        "docs/llms.txt": gen["llms.txt"],
                        "docs/sitemap.xml": gen["sitemap.xml"],
                    },
                )
            st.cache_data.clear()
            if ok:
                st.success(f"✅ {msg}")
                st.markdown(f"👉 [공식 홈페이지 열기 ({site_url_def})]({site_url_def})")
            else:
                st.warning(f"구글 시트 저장은 완료되었으나 GitHub 자동 배포를 실행하지 못했습니다: {msg}")
                st.info("2번 탭 [홈페이지 미리보기 · 배포 설정]에서 GitHub 토큰을 한 번만 등록하면 앞으로 버튼 한 번으로 자동 배포됩니다.")


with tab_deploy:
    render_section_banner(
        "1. GitHub Pages 원클릭 배포 설정 (최초 1회)",
        badge="연결됨" if saved_token else "토큰 미등록",
        subtitle="GitHub Fine-grained Personal Access Token (권한: 해당 저장소 Contents Read & Write)을 1회 등록해 두면 자동 배포됩니다.",
        accent="indigo",
    )
    with st.container(border=True):
        g1, g2, g3 = st.columns([1.4, 0.8, 1.4])
        in_repo = g1.text_input("GitHub 저장소 (owner/repo)", value=repo_def, key="hp_gh_repo")
        in_branch = g2.text_input("브랜치", value=branch_def, key="hp_gh_branch")
        in_url = g3.text_input("공식 홈페이지 URL", value=site_url_def, key="hp_gh_url")
        in_token = st.text_input(
            "GitHub 토큰 (PAT)",
            value=saved_token,
            type="password",
            placeholder="github_pat_... 또는 ghp_...",
            help="GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens에서 store-salary-auto 저장소의 Contents(Read and write) 권한만 체크해 발급하세요.",
            key="hp_gh_token",
        )
        if st.button("배포 설정 저장", type="primary", key="hp_save_gh_cfg"):
            new_cfg = dict(app_cfg)
            new_cfg.update({
                "hp_github_repo": in_repo.strip(),
                "hp_github_branch": in_branch.strip(),
                "hp_site_url": in_url.strip(),
                "hp_github_token": in_token.strip(),
            })
            save_store_settings(store_cfg["db_id"], new_cfg)
            st.cache_data.clear()
            st.success("GitHub 배포 설정이 저장되었습니다. 이제 1번 탭에서 원클릭 배포를 사용하실 수 있습니다!")
            st.rerun()

    st.divider()
    render_section_banner(
        "2. 생성된 파일 다운로드 및 미리보기",
        badge="HTML · JSON-LD · llms.txt",
        subtitle="현재 편집된 차림표로 생성된 실제 홈페이지 파일입니다.",
        accent="emerald",
    )
    gen_preview = render_homepage_files(ed_menu, info_payload)
    d1, d2 = st.columns(2)
    d1.download_button(
        "📥 index.html 다운로드",
        data=gen_preview["index.html"].encode("utf-8"),
        file_name="index.html",
        mime="text/html",
        use_container_width=True,
    )
    d2.download_button(
        "📥 llms.txt 다운로드",
        data=gen_preview["llms.txt"].encode("utf-8"),
        file_name="llms.txt",
        mime="text/plain",
        use_container_width=True,
    )
    with st.expander("차림표 미리보기 (HTML 렌더링)", expanded=False):
        components.html(gen_preview["index.html"], height=760, scrolling=True)
