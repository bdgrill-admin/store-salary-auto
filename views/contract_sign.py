import os
import datetime
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from contract_utils import get_contract_by_id, complete_employee_signature

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
</style>
""", unsafe_allow_html=True)

cid = st.query_params.get("contract_id", "")
if not cid:
    st.error("잘못된 접근입니다. 매니저에게 전달받은 전용 계약서 링크로 접속해 주세요.")
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
    <p><b>분 당 그 릴</b> (이하 "사업주"라 함)과(와) <b>{emp_name}</b> (이하 "근로자"라 함)은 다음과 같이 근로계약을 체결한다.</p>
    <p>{period_text}<br>
    <b>2. 근 무 장 소 :</b> 경기도 성남시 분당구 미금일로 74번길 13-3 1층<br>
    <b>3. 업무의 내용 :</b> {contract.get('업무내용')}<br>
    <b>4. 소정근로시간(변동있음) :</b> {contract.get('근무시작')} 부터 {contract.get('근무종료')} 까지 (휴게시간 : {contract.get('휴게시간(분)')}분)<br>
    <b>5. 근무일/휴일 :</b> 매주 {contract.get('주근무일수')}일(또는 매일단위)근무, 주휴일 매주 {contract.get('주휴요일')}요일<br>
    <b>6. 임 금 :</b> {contract.get('임금구분')} <b>{pay_amt}원</b> / 상여금: {contract.get('상여금')} / 기타급여: {contract.get('기타급여')}<br>
    &nbsp;&nbsp;- 임금지급일
