import json
import datetime
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw
from contract_utils import get_contract_by_id, complete_employee_signature

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

st.subheader("✍️ 근로자 인적사항 및 전자서명")

col1, col2 = st.columns(2)
with col1:
    rrn = st.text_input("주민등록번호 (급여·세무신고용)", placeholder="예: 000101-3123456")
    bank = st.selectbox("입금 은행명", ["국민은행", "신한은행", "우리은행", "하나은행", "농협은행", "기업은행", "카카오뱅크", "토스뱅크", "케이뱅크", "새마을금고", "우체국", "수협은행", "기타"])
    account = st.text_input("계좌번호 (숫자만 또는 하이픈 포함)", placeholder="예: 123456-01-123456")
    health_date = st.date_input("보건증 제출(예정)일", value=datetime.date.today())

with col2:
    phone = st.text_input("연락처 (휴대폰)", placeholder="예: 010-1234-5678")
    email = st.text_input("이메일 주소 (계약서 PDF 사본 수신용)", placeholder="예: hong@naver.com")
    addr = st.text_input("거주지 주소", placeholder="예: 경기도 성남시 분당구 ...")
    cctv_agree = st.radio("위 16조 개인영상정보(CCTV) 수집 및 이용에 동의하십니까?", ["동의함", "동의하지 않음"], horizontal=True)

agree_confirm = st.checkbox(f"본인({emp_name})은 위 표준근로계약서 1조~17조의 내용을 충분히 확인하고 이에 동의하여 전자서명합니다.")

st.markdown("**1단계: 아래 흰 칸에 손가락 또는 마우스로 자필 서명을 그린 뒤 `[서명 확정]` 버튼을 눌러주세요.**")

components.html("""
<div style="border: 2px dashed #6b7280; border-radius: 8px; background: #f9fafb; padding: 10px; max-width: 360px;">
  <canvas id="pad" width="320" height="140" style="background: #ffffff; border: 1px solid #e5e7eb; border-radius: 4px; touch-action: none; display: block;"></canvas>
  <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; gap: 8px;">
    <span id="status" style="font-size: 12px; color: #4b5563;">위 칸에 서명 후 확정 클릭</span>
    <div>
      <button type="button" onclick="clearPad()" style="padding: 5px 10px; font-size: 12px; border: 1px solid #d1d5db; border-radius: 4px; background: #fff; cursor: pointer;">다시 쓰기</button>
      <button type="button" onclick="confirmSign()" style="padding: 5px 12px; font-size: 12px; font-weight: bold; border: none; border-radius: 4px; background: #2563eb; color: #fff; cursor: pointer;">서명 확정</button>
    </div>
  </div>
</div>
<script>
const canvas = document.getElementById('pad');
const ctx = canvas.getContext('2d');
ctx.lineWidth = 3;
ctx.lineCap = 'round';
ctx.strokeStyle = '#111827';
let drawing = false;
let strokes = [];
let curStroke = [];

function getPos(e) {
  const rect = canvas.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const clientY = e.touches ? e.touches[0].clientY : e.clientY;
  return [Math.round(clientX - rect.left), Math.round(clientY - rect.top)];
}

function startDraw(e) {
  e.preventDefault();
  drawing = true;
  curStroke = [getPos(e)];
  ctx.beginPath();
  ctx.moveTo(curStroke[0][0], curStroke[0][1]);
}

function moveDraw(e) {
  if (!drawing) return;
  e.preventDefault();
  const pt = getPos(e);
  curStroke.push(pt);
  ctx.lineTo(pt[0], pt[1]);
  ctx.stroke();
}

function endDraw(e) {
  if (!drawing) return;
  drawing = false;
  if (curStroke.length > 0) strokes.push(curStroke);
  document.getElementById('status').innerText = '서명 입력됨 (' + strokes.length + '획)';
}

function clearPad() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  strokes = [];
  document.getElementById('status').innerText = '위 칸에 서명 후 확정 클릭';
}

function confirmSign() {
  if (strokes.length === 0) {
    alert('먼저 위 흰 칸에 서명을 그려주세요.');
    return;
  }
  const encoded = encodeURIComponent(JSON.stringify(strokes));
  const url = new URL(window.parent.location.href);
  url.searchParams.set('sig', encoded);
  window.parent.location.href = url.toString();
}

canvas.addEventListener('mousedown', startDraw);
canvas.addEventListener('mousemove', moveDraw);
canvas.addEventListener('mouseup', endDraw);
canvas.addEventListener('mouseleave', endDraw);
canvas.addEventListener('touchstart', startDraw, { passive: false });
canvas.addEventListener('touchmove', moveDraw, { passive: false });
canvas.addEventListener('touchend', endDraw);
</script>
""", height=210)


def _strokes_to_image(raw_json: str) -> Image.Image:
    img = Image.new("RGBA", (320, 140), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    strokes = json.loads(raw_json)
    for stroke in strokes:
        if len(stroke) == 1:
            x, y = stroke[0]
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(17, 24, 39, 255))
        elif len(stroke) > 1:
            pts = [(p[0], p[1]) for p in stroke]
            draw.line(pts, fill=(17, 24, 39, 255), width=3)
    return img


sig_param = st.query_params.get("sig", "")
if sig_param:
    try:
        preview_img = _strokes_to_image(sig_param)
        st.success("✅ 자필 서명이 정상 등록되었습니다. 아래 제출 버튼을 눌러 완료해 주세요.")
        st.image(preview_img, caption="등록된 서명 미리보기", width=220)
    except Exception:
        sig_param = ""

if st.button("✅ 2단계: 계약 내용 확인 및 전자서명 최종 제출", type="primary", use_container_width=True):
    if not rrn.strip() or not account.strip() or not phone.strip() or not addr.strip() or not email.strip():
        st.error("주민등록번호, 계좌번호, 연락처, 이메일, 주소를 모두 입력해 주세요.")
    elif not agree_confirm:
        st.error("계약 내용 확인 및 전자서명 동의 체크박스를 선택해 주세요.")
    elif not sig_param:
        st.error("서명란에 서명을 그린 뒤 파란색 [서명 확정] 버튼을 먼저 눌러주세요.")
    else:
        with st.spinner("근로계약서 PDF 생성 및 교부 처리 중입니다. 잠시만 기다려 주세요..."):
            sign_img = _strokes_to_image(sig_param)
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
            st.query_params.clear()
            st.query_params["contract_id"] = cid
            st.success("🎉 전자 근로계약서 체결이 완료되었습니다!")
            if email_ok:
                st.info(f"입력하신 이메일({email.strip()})로 계약서 PDF 사본이 자동 발송되었습니다.")
            st.download_button(
                label="📄 내 근로계약서 PDF 바로 다운로드",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                use_container_width=True,
            )
