"""
================================================================================
[파일명] views/contract_sign.py
[역할] 직원이 전용 링크(?contract_id=...)로 접속했을 때 열리는 모바일/웹 전자서명 페이지
[주요 기능]
  1. '환경설정' 탭과 실시간 연동 (사업체명, 대표자명, 사업장 소재지, 임금지급일 반영)
  2. 관리자 메뉴(사이드바)를 완전히 숨기고 계약서 전용 화면만 단독 표시
  3. 제1조 ~ 제17조 표준근로계약서 + 선택 시 '비밀유지 및 경업금지 서약서' 본문 출력
  4. 직원 명부에서 연동된 기본정보(주민번호, 은행명, 계좌번호, 이메일)를 입력란에 자동 채움
  5. 정자 성명 타이핑(자동 사인 이미지 변환) 또는 자필 서명 사진 업로드 지원
  6. st.form 기반 제출 및 시트 상태 중복 체크로 무반응 버그 및 중복 제출 완벽 방지
================================================================================
"""

import os
import datetime
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from contract_utils import (
    get_contract_by_id,
    complete_employee_signature,
    load_runtime_settings,
)

BANK_OPTIONS = [
    "KB국민",
    "신한은행",
    "우리은행",
    "하나은행",
    "NH농협",
    "IBK기업은행",
    "카카오뱅크",
    "토스뱅크",
    "케이뱅크",
    "새마을금고",
    "신협",
    "우체국",
    "SC제일은행",
    "부산은행",
    "대구은행(iM뱅크)",
    "광주은행",
    "전북은행",
    "경남은행",
    "수협은행",
    "기타",
]

BANK_ALIAS_MAP = {
    "국민": "KB국민",
    "국민은행": "KB국민",
    "신한": "신한은행",
    "우리": "우리은행",
    "하나": "하나은행",
    "농협": "NH농협",
    "농협은행": "NH농협",
    "기업": "IBK기업은행",
    "기업은행": "IBK기업은행",
    "카카오": "카카오뱅크",
    "토스": "토스뱅크",
    "케이": "케이뱅크",
}

st.markdown("""
<style>
    [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none !important; }
    .contract-box {
        background-color: #ffffff;
        border: 1px solid #d1d5db;
        border-radius: 10px;
        padding: 20px;
        line-height: 1.75;
        font-size: 14.5px;
        color: #111827;
        margin-bottom: 16px;
    }
    .contract-title {
        text-align: center;
        font-size: 20px;
        font-weight: 800;
        border: 2px solid #111827;
        padding: 8px;
        margin-bottom: 16px;
    }
    .nda-title {
        text-align: center;
        font-size: 20px;
        font-weight: 800;
        border-bottom: 2px solid #111827;
        padding-bottom: 8px;
        margin-bottom: 14px;
    }
</style>
""", unsafe_allow_html=True)

cid = st.query_params.get("contract_id", "")
if not cid:
    st.error("잘못된 접근입니다. 매니저에게 전달받은 전용 계약서 링크로 접속해 주세요.")
    st.stop()

# 방금 서명을 완료한 직후라면 완료 및 PDF 다운로드 화면 즉시 출력
if "sign_done_data" in st.session_state and st.session_state["sign_done_data"] is not None:
    done = st.session_state["sign_done_data"]
    if done.get("cid") == cid:
        st.success("🎉 전자 근로계약서 체결이 완료되었습니다!")
        if done["email_ok"]:
            st.info(f"📧 입력하신 이메일({done['email']})로 계약서 PDF 사본이 자동 발송되었습니다.")
        else:
            st.warning(f"⚠️ 계약서는 정상 저장되었으나 이메일 발송에 실패했습니다 ({done['email_msg']}). 아래 버튼으로 직접 다운로드해 보관해 주세요.")
        st.download_button(
            label="📄 내 근로계약서 PDF 바로 다운로드",
            data=done["pdf_bytes"],
            file_name=done["filename"],
            mime="application/pdf",
            use_container_width=True,
        )
        st.stop()

contract = get_contract_by_id(st.secrets, cid)
if not contract:
    st.error("존재하지 않거나 만료된 계약서 링크입니다. 매니저에게 문의해 주세요.")
    st.stop()

if contract.get("상태") == "서명완료":
    st.success(f"✅ **{contract.get('직원명')}** 님의 근로계약서 서명이 이미 완료되었습니다. ({contract.get('서명일시')})")
    if contract.get("드라이브PDF링크"):
        st.info("계약서 사본은 입력하신 이메일로 발송되었습니다.")
    st.stop()

runtime_cfg = load_runtime_settings(st.secrets)
store_title = runtime_cfg.get("store_title", "분당그릴").strip() or "분당그릴"
spaced_store = " ".join(list(store_title)) if len(store_title) <= 5 else store_title
owner_name = runtime_cfg.get("owner_name", "이용석").strip() or "이용석"
spaced_owner = " ".join(list(owner_name)) if len(owner_name) <= 4 else owner_name
store_address = runtime_cfg.get("store_address", "경기도 성남시 분당구 미금일로 74번길 13-3 1층").strip()
pay_day = runtime_cfg.get("payroll_start_day", "5").strip() or "5"

include_nda = str(contract.get("비밀유지서약", "N")).strip().upper() in ("Y", "TRUE", "1")


def _create_text_signature_image(sign_text: str) -> Image.Image:
    img = Image.new("RGBA", (320, 140), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    font_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumPen.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBrush.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
    ]
    font = None
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 54)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), sign_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = max(10, (320 - tw) // 2)
    y = max(10, (140 - th) // 2 - 6)

    draw.text((x, y), sign_text, fill=(17, 24, 39, 255), font=font)
    draw.line([(x, y + th + 8), (x + tw, y + th + 8)], fill=(17, 24, 39, 200), width=2)
    return img


ctype = contract.get("계약유형", "기간의 정함이 없는 경우")
emp_name = contract.get("직원명", "")
s_date = contract.get("근로개시일", "")
e_date = contract.get("근로종료일", "")
pay_amt = f"{int(float(str(contract.get('금액', '0')).replace(',', '') or 0)):,}"

period_text = (
    f"<b>1. 근로계약기간 :</b> {s_date} 부터 ~ {e_date} 까지"
    if ctype == "기간의 정함이 있는 경우"
    else f"<b>1. 근로개시일 :</b> {s_date} 부터"
)

st.markdown(f"""
<div class="contract-box">
    <div class="contract-title">표준근로계약서({ctype})</div>
    <p><b>{spaced_store}</b> (이하 "사업주"라 함)과(와) <b>{emp_name}</b> (이하 "근로자"라 함)은 다음과 같이 근로계약을 체결한다.</p>
    <p>{period_text}<br>
    <b>2. 근 무 장 소 :</b> {store_address}<br>
    <b>3. 업무의 내용 :</b> {contract.get('업무내용')}<br>
    <b>4. 소정근로시간(변동있음) :</b> {contract.get('근무시작')} 부터 {contract.get('근무종료')} 까지 (휴게시간 : {contract.get('휴게시간(분)')}분)<br>
    <b>5. 근무일/휴일 :</b> 매주 {contract.get('주근무일수')}일(또는 매일단위)근무, 주휴일 매주 {contract.get('주휴요일')}요일<br>
    <b>6. 임 금 :</b> {contract.get('임금구분')} <b>{pay_amt}원</b> / 상여금: {contract.get('상여금')} / 기타급여: {contract.get('기타급여')}<br>
    &nbsp;&nbsp;- 임금지급일 : 매월 {pay_day}일 (휴일의 경우는 휴일 지급) / 근로자 명의 예금통장에 입금<br>
    <b>7. 연차유급휴가 :</b> 근로기준법에서 정하는 바에 따라 부여함<br>
    <b>8. 사회보험 적용여부 :</b> {contract.get('사회보험')}<br>
    <b>9. 근로계약서 교부 :</b> 사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의 교부 요구와 관계없이 근로자에게 교부함(근로기준법 제17조 이행)<br>
    <b>10. 근로계약, 취업규칙 등의 성실한 이행의무 :</b> 사업주와 근로자는 각자가 근로계약, 취업규칙, 단체협약을 지키고 성실하게 이행하여야 함<br>
    <b>11. 위생 관리 및 보건증 제출 :</b> 근로자는 식품위생법에 따라 입사 시 유효한 보건증(건강진단결과서)을 제출해야 하며, 근무 기간 중 유효기간 만료 전 갱신하여 제출할 의무가 있다. 보건증 미제출 또는 위생 관련 법령 위반으로 발생한 불이익에 대해 근로자는 필요한 조치에 적극 협조한다.<br>
    <b>12. 복무 규율 및 사직 통보 :</b> 근로자는 부득이한 사정으로 결근·지각·조퇴할 경우 최소 근무 시작 24시간 전에 당사자(업주)에게 사전 승인을 받아야 한다. 근로자가 사직하고자 할 경우에는 인수인계 및 대체 인력 채용을 위해 최소 30일 전에 사업주에게 서면 또는 메시지로 사직 의사를 통보해야 한다.<br>
    <b>13. 수습기간 :</b> 입사 후 3개월(최대 3개월)간은 수습기간으로 정한다. 수습기간 중 근로 태도, 업무 적응도, 위생 수칙 준수 여부 등이 현저히 미달할 경우 근로기준법 제26조, 제27조 및 제35조에 따라 본 계약을 즉시 해지할 수 있다. (단, 근로계약기간이 1년 미만인 경우 수습기간 중이라도 임금을 감액하지 아니하고 100% 지급한다)<br>
    <b>14. 비밀유지 의무 :</b> 근로자는 재직 중은 물론 퇴직 후에도 업무상 알게 된 매장의 영업 비밀, 조리 노하우, 고객 정보 등을 제3자에게 누설하거나 부당하게 활용해서는 안 된다.<br>
    <b>15. 비품 반납 및 손해배상 :</b> 근로자는 퇴사 시 지급받은 유니폼, 명찰, 매장 비품 및 장비를 즉시 반납하여야 한다. 고의 또는 중대한 과실로 매장 시설물이나 기물을 손괴하거나 손실을 입힌 경우 관련 법령에 따라 배상 책임을 질 수 있다.<br>
    <b>16. 영상정보(CCTV) 수집 및 이용 동의 :</b><br>
    &nbsp;&nbsp;- 수집 목적: 매장 내 시설 안전, 화재 및 도난 범죄 예방, 고객 결제 분쟁 처리<br>
    &nbsp;&nbsp;- 수집 항목: 매장 내 CCTV에 촬영되는 영상정보 (홀, 카운터, 주방 등)<br>
    &nbsp;&nbsp;- 보유 및 이용 기간: 촬영일로부터 30일 (보존기간 경과 시 자동 파기)<br>
    &nbsp;&nbsp;- 동의 거부 안내: 귀하는 영상 수집에 대한 동의를 거부할 권리가 있으나, 매장 보안 및 안전 관리 목적상 채용 또는 근무 수행에 제한이 있을 수 있습니다.<br>
    <b>17. 기 타 :</b> 이 계약에 정함이 없는 사항은 근로기준법령에 의함</p>
</div>
""", unsafe_allow_html=True)

if include_nda:
    st.markdown(f"""
    <div class="contract-box" style="border: 1.5px solid #334155; background-color: #F8FAFC;">
        <div class="nda-title">서 약 서 (비밀유지 및 경업금지)</div>
        <p style="text-align:right; font-size:13.5px; color:#334155;">
            <b>서약자(근로자):</b> {emp_name} &nbsp;|&nbsp; <b>귀중:</b> {store_title} (대표자: {spaced_owner})
        </p>
        <p>본인은 <b>{store_title}</b>(이하 '당사'라 함)에 채용되어 근무함에 있어, 당사의 영업비밀 및 업무상 알게 된 제반 지식과 정보를 보호하기 위해 아래의 사항을 준수할 것을 엄숙히 서약합니다.</p>
        <p><b>제1조 (비밀유지의 의무)</b><br>
        1. 본인은 직무 수행 여부를 막론하고 재직 중은 물론 퇴직 후 2년 동안 당사의 사전 서면 승인 없이 다음 각 호에 해당하는 정보를 외부에 유출, 공개, 누설하거나 개인적인 목적으로 사용하지 않는다.<br>
        2. 당사 고유의 <u>고기 숙성법, 소스 및 양념(갈비 등) 배합 비율, 조리 레시피 및 주방 운영 매뉴얼 및 당사의 원부재료 매입 원가, 거래처 정보(육류 및 식자재 공급업체 목록) 및 거래 조건, 당사의 매출 정보, 마진율, 주방 내부 설비 및 기기 배치 도면, 기타</u> 당사가 보안을 요청하거나 객관적으로 비밀로 유지되어야 할 영업 및 기술상의 정보</p>
        <p><b>제2조 (정보 및 자료의 반환)</b><br>
        본인은 퇴직 시 또는 당사의 요청이 있을 때에는 당사의 영업비밀이 포함된 <u>서류, 메모, 데이터(주방 매뉴얼, 조리법 기록 등) 및 관련 물품 일체를 즉시 당사에 반환</u>하며, 어떠한 형태로도 복사본이나 사본을 보유하지 않는다.</p>
        <p><b>제3조 (경업금지 의무)</b><br>
        본인은 당사의 핵심 기술 및 레시피 보호를 위하여, 퇴직 후 2년 동안 당사의 주요 상권(분당구 및 인근 지역) 내에서 경쟁 관계에 있는 동일 업종(육류 구이 전문점)을 창업하거나, 해당 업체에 취업(동업 포함)하여 당사의 영업비밀을 부당하게 활용하지 않는다.</p>
        <p><b>제4조 (서약 위반 시의 책임)</b><br>
        본인이 본 서약서의 의무를 위반하여 당사에 손해를 입힌 경우, 본인은 관련 법령(부정경쟁방지 및 영업비밀보호에 관한 법률 등)에 따른 민·형사상의 책임을 전적으로 지며, 당사가 입은 실질적 손해액 전액을 배상할 것을 서약합니다.</p>
    </div>
    """, unsafe_allow_html=True)

st.subheader("✍️ 근로자 인적사항 및 전자서명")
st.caption("매장에 등록된 기본정보가 미리 채워져 있습니다. 내용이 맞는지 확인하시고 빈칸을 마저 입력해 주세요.")

pre_rrn = contract.get("주민번호", "").strip()
raw_bank = contract.get("은행명", "").strip()
pre_bank = BANK_ALIAS_MAP.get(raw_bank, raw_bank)
bank_idx = BANK_OPTIONS.index(pre_bank) if pre_bank in BANK_OPTIONS else 0
pre_account = contract.get("계좌번호", "").strip()
pre_phone = contract.get("연락처", "").strip()
pre_email = contract.get("이메일", "").strip()
pre_addr = contract.get("주소", "").strip()

sign_method = st.radio(
    "전자서명 방식 선택",
    ["✍️ 정자 성명 입력 (자동 전자서명 이미지 생성)", "📷 자필 서명 사진/이미지 업로드"],
    horizontal=True,
)

with st.form("contract_sign_submit_form"):
    col1, col2 = st.columns(2)
    with col1:
        rrn = st.text_input("주민등록번호 (급여·세무신고용)", value=pre_rrn, placeholder="앞 6자리 - 뒤 7자리 입력")
        bank = st.selectbox("입금 은행명", BANK_OPTIONS, index=bank_idx)
        account = st.text_input("계좌번호 (숫자만 또는 하이픈 포함)", value=pre_account, placeholder="예: 123456-01-123456")
        health_date = st.date_input("보건증 제출(예정)일", value=datetime.date.today())

    with col2:
        phone = st.text_input("연락처 (휴대폰)", value=pre_phone, placeholder="예: 010-1234-5678")
        email = st.text_input("이메일 주소 (계약서 PDF 사본 수신용)", value=pre_email, placeholder="예: hong@naver.com")
        addr = st.text_input("거주지 주소", value=pre_addr, placeholder="예: 경기도 성남시 분당구 ...")
        cctv_agree = st.radio("위 16조 개인영상정보(CCTV) 수집 및 이용에 동의하십니까?", ["동의함", "동의하지 않음"], horizontal=True)

    st.divider()
    sign_text_input = ""
    uploaded_sign_file = None

    if sign_method.startswith("✍️"):
        sign_text_input = st.text_input(
            f"전자서명란 — 아래 칸에 본인 성명('{emp_name}')을 정자로 직접 입력해 주세요",
            placeholder=emp_name,
        )
    else:
        uploaded_sign_file = st.file_uploader(
            "흰 종이에 서명 후 촬영한 사진 또는 서명 이미지(PNG/JPG)를 올려주세요",
            type=["png", "jpg", "jpeg"],
        )

    agree_label = (
        f"본인({emp_name})은 위 표준근로계약서(제1조부터 제17조까지) 및 비밀유지·경업금지 서약서(제1조부터 제4조까지)의 내용을 충분히 확인하고 이에 동의하여 전자서명합니다."
        if include_nda
        else f"본인({emp_name})은 위 표준근로계약서(제1조부터 제17조까지)의 내용을 충분히 확인하고 이에 동의하여 전자서명합니다."
    )
    agree_confirm = st.checkbox(agree_label)

    submitted = st.form_submit_button(
        "✅ 계약 내용 확인 및 전자서명 최종 제출",
        type="primary",
        use_container_width=True,
    )

if submitted:
    if not rrn.strip() or not account.strip() or not phone.strip() or not addr.strip() or not email.strip():
        st.error("주민등록번호, 계좌번호, 연락처, 이메일, 주소를 모두 입력해 주세요.")
    elif not agree_confirm:
        st.error("계약 내용 확인 및 전자서명 동의 체크박스를 선택해 주세요.")
    elif sign_method.startswith("✍️") and not sign_text_input.strip():
        st.error("전자서명란에 본인 성명을 입력해 주세요.")
    elif not sign_method.startswith("✍️") and uploaded_sign_file is None:
        st.error("서명 이미지 파일을 업로드해 주세요.")
    else:
        with st.spinner("근로계약서 PDF 생성 및 교부 처리 중입니다. 잠시만 기다려 주세요..."):
            latest_check = get_contract_by_id(st.secrets, cid)
            if latest_check and latest_check.get("상태") == "서명완료":
                st.rerun()

            if sign_method.startswith("✍️"):
                sign_img = _create_text_signature_image(sign_text_input.strip())
            else:
                sign_img = Image.open(uploaded_sign_file).convert("RGBA")

            emp_inputs = {
                "주민번호": rrn.strip(),
                "은행명": bank,
                "계좌번호": account.strip(),
                "주소": addr.strip(),
                "연락처": phone.strip(),
                "이메일": email.strip(),
                "CCTV동의": cctv_agree,
                "보건증제출일": health_date.strftime("%Y-%m-%d"),
            }
            pdf_bytes, filename, drive_link, email_ok, email_msg = complete_employee_signature(
                st.secrets, contract, emp_inputs, sign_img
            )
            st.session_state["sign_done_data"] = {
                "cid": cid,
                "pdf_bytes": pdf_bytes,
                "filename": filename,
                "email": email.strip(),
                "email_ok": email_ok,
                "email_msg": email_msg,
            }
            st.rerun()
