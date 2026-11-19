"""
================================================================================
[파일명] views/contract_sign.py
[역할] 직원이 전용 링크(?contract_id=...)로 접속했을 때 열리는 모바일/웹 전자서명 페이지
[주요 기능]
  1. 관리자 메뉴(사이드바)를 완전히 숨기고 계약서 전용 화면만 단독 표시
  2. 제1조 ~ 제17조 근로계약서 전문을 가독성 높은 박스 형태로 출력
  3. 직원 명부에서 연동된 기본정보(주민번호, 은행명, 계좌번호, 이메일)를 입력란에 자동 채움(Pre-fill)
  4. 정자 성명 타이핑(자동 사인 이미지 변환) 또는 자필 서명 사진 업로드 지원
  5. [중복 제출 방지] 제출 버튼 클릭 즉시 버튼 잠금 처리 및 완료 화면 고정으로 연타 원천 차단
================================================================================
"""

import os
import datetime
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from contract_utils import get_contract_by_id, complete_employee_signature

# ------------------------------------------------------------------------------
# 급여 대량이체용 표준 은행명 리스트 및 약칭 변환 매핑 (staff.py와 100% 동일하게 통일)
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# 직원이 다른 관리자 메뉴를 볼 수 없도록 좌측 사이드바 강제 숨김 & 계약서 박스 디자인
# ------------------------------------------------------------------------------
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
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# URL 파라미터(?contract_id=...) 확인
# ------------------------------------------------------------------------------
cid = st.query_params.get("contract_id", "")
if not cid:
    st.error("잘못된 접근입니다. 매니저에게 전달받은 전용 계약서 링크로 접속해 주세요.")
    st.stop()

# ------------------------------------------------------------------------------
# [중복 제출 방지 1단계] 방금 서명을 완료한 직후라면 시트 재조회 전에 완료/다운로드 화면 즉시 출력
# ------------------------------------------------------------------------------
if "sign_done_data" in st.session_state and st.session_state["sign_done_data"] is not None:
    done = st.session_state["sign_done_data"]
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

# ------------------------------------------------------------------------------
# 시트에서 계약서 정보 조회 및 이미 서명 완료된 계약서 재접속 차단
# ------------------------------------------------------------------------------
contract = get_contract_by_id(st.secrets, cid)
if not contract:
    st.error("존재하지 않거나 만료된 계약서 링크입니다. 매니저에게 문의해 주세요.")
    st.stop()

if contract.get("상태") == "서명완료":
    st.success(f"✅ **{contract.get('직원명')}** 님의 근로계약서 서명이 이미 완료되었습니다. ({contract.get('서명일시')})")
    if contract.get("드라이브PDF링크"):
        st.info("계약서 사본은 입력하신 이메일로 발송되었습니다.")
    st.stop()


# ------------------------------------------------------------------------------
# [보조 함수] 직원이 타이핑한 성명을 손글씨/서명 스타일의 투명 배경 PNG로 변환
# ------------------------------------------------------------------------------
def _create_text_signature_image(sign_text: str) -> Image.Image:
    """입력한 서명 성명을 도장/서명 형태의 PNG 이미지로 생성"""
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
    # 하단 서명 밑줄
    draw.line([(x, y + th + 8), (x + tw, y + th + 8)], fill=(17, 24, 39, 200), width=2)
    return img


# ------------------------------------------------------------------------------
# 제1조 ~ 제17조 표준근로계약서 본문 렌더링
# ------------------------------------------------------------------------------
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
    <p><b>분 당 그 릴</b> (이하 "사업주"라 함)과(와) <b>{emp_name}</b> (이하 "근로자"라 함)은 다음과 같이 근로계약을 체결한다.</p>
    <p>{period_text}<br>
    <b>2. 근 무 장 소 :</b> 경기도 성남시 분당구 미금일로 74번길 13-3 1층<br>
    <b>3. 업무의 내용 :</b> {contract.get('업무내용')}<br>
    <b>4. 소정근로시간(변동있음) :</b> {contract.get('근무시작')} 부터 {contract.get('근무종료')} 까지 (휴게시간 : {contract.get('휴게시간(분)')}분)<br>
    <b>5. 근무일/휴일 :</b> 매주 {contract.get('주근무일수')}일(또는 매일단위)근무, 주휴일 매주 {contract.get('주휴요일')}요일<br>
    <b>6. 임 금 :</b> {contract.get('임금구분')} <b>{pay_amt}원</b> / 상여금: {contract.get('상여금')} / 기타급여: {contract.get('기타급여')}<br>
    &nbsp;&nbsp;- 임금지급일 : 매월 5일 (휴일의 경우는 휴일 지급) / 근로자 명의 예금통장에 입금<br>
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

# ------------------------------------------------------------------------------
# 근로자 인적사항 입력란 (직원 명부에 등록된 정보가 있으면 자동으로 미리 채움)
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# 전자서명 방식 선택 및 미리보기
# ------------------------------------------------------------------------------
st.divider()
sign_method = st.radio(
    "전자서명 방식 선택",
    ["✍️ 정자 성명 입력 (자동 전자서명 이미지 생성)", "📷 자필 서명 사진/이미지 업로드"],
    horizontal=True,
)

sign_text_input = ""
uploaded_sign_file = None

if sign_method.startswith("✍️"):
    sign_text_input = st.text_input(
        f"전자서명란 — 아래 칸에 본인 성명('{emp_name}')을 정자로 직접 입력해 주세요",
        placeholder=emp_name,
    )
    if sign_text_input.strip():
        preview = _create_text_signature_image(sign_text_input.strip())
        st.image(preview, caption="계약서에 날인될 전자서명 미리보기", width=220)
else:
    uploaded_sign_file = st.file_uploader(
        "흰 종이에 서명 후 촬영한 사진 또는 서명 이미지(PNG/JPG)를 올려주세요",
        type=["png", "jpg", "jpeg"],
    )
    if uploaded_sign_file:
        st.image(uploaded_sign_file, caption="업로드된 서명 미리보기", width=220)

agree_confirm = st.checkbox(f"본인({emp_name})은 위 표준근로계약서 1조~17조의 내용을 충분히 확인하고 이에 동의하여 전자서명합니다.")

# ------------------------------------------------------------------------------
# [중복 제출 방지 2단계] 버튼 클릭 즉시 잠금 콜백 실행 및 최종 제출 처리
# ------------------------------------------------------------------------------
if "submitting_lock" not in st.session_state:
    st.session_state["submitting_lock"] = False

def _lock_submit_btn():
    st.session_state["submitting_lock"] = True

if st.button(
    "✅ 계약 내용 확인 및 전자서명 최종 제출",
    type="primary",
    use_container_width=True,
    disabled=st.session_state["submitting_lock"],
    on_click=_lock_submit_btn,
):
    if not rrn.strip() or not account.strip() or not phone.strip() or not addr.strip() or not email.strip():
        st.session_state["submitting_lock"] = False
        st.error("주민등록번호, 계좌번호, 연락처, 이메일, 주소를 모두 입력해 주세요.")
    elif not agree_confirm:
        st.session_state["submitting_lock"] = False
        st.error("계약 내용 확인 및 전자서명 동의 체크박스를 선택해 주세요.")
    elif sign_method.startswith("✍️") and not sign_text_input.strip():
        st.session_state["submitting_lock"] = False
        st.error("전자서명란에 본인 성명을 입력해 주세요.")
    elif not sign_method.startswith("✍️") and uploaded_sign_file is None:
        st.session_state["submitting_lock"] = False
        st.error("서명 이미지 파일을 업로드해 주세요.")
    else:
        with st.spinner("근로계약서 PDF 생성 및 교부 처리 중입니다. 잠시만 기다려 주세요 (연타하지 마세요)..."):
            # 시트에서 최신 상태를 한 번 더 확인하여 이미 '서명완료'면 중복 실행 중단
            latest_check = get_contract_by_id(st.secrets, cid)
            if latest_check and latest_check.get("상태") == "서명완료":
                st.session_state["submitting_lock"] = False
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
                "pdf_bytes": pdf_bytes,
                "filename": filename,
                "email": email.strip(),
                "email_ok": email_ok,
                "email_msg": email_msg,
            }
            st.rerun()
