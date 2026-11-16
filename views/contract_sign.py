import json
import urllib.parse
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


# HTML 폼 제출로 넘어온 데이터 처리
if st.query_params.get("submit_sign") == "1":
    try:
        rrn = st.query_params.get("rrn", "").strip()
        bank = st.query_params.get("bank", "").strip()
        account = st.query_params.get("account", "").strip()
        health_date = st.query_params.get("health_date", "").strip()
        phone = st.query_params.get("phone", "").strip()
        email = st.query_params.get("email", "").strip()
        addr = st.query_params.get("addr", "").strip()
        cctv_agree = st.query_params.get("cctv", "동의함").strip()
        sig_raw = st.query_params.get("sig", "").strip()

        if not (rrn and account and phone and email and addr and sig_raw):
            st.error("입력값이 누락되었습니다. 다시 작성해 주세요.")
        else:
            with st.spinner("근로계약서 PDF 생성 및 교부 처리 중입니다. 잠시만 기다려 주세요..."):
                sign_img = _strokes_to_image(sig_raw)
                emp_inputs = {
                    "주민번호": rrn,
                    "은행명": bank,
                    "계좌번호": account,
                    "주소": addr,
                    "연락처": phone,
                    "이메일": email,
                    "CCTV동의": cctv_agree,
                    "보건증제출일": health_date,
                }
                pdf_bytes, filename, drive_link, email_ok, email_msg = complete_employee_signature(
                    st.secrets, contract, emp_inputs, sign_img
                )
                st.query_params.clear()
                st.query_params["contract_id"] = cid
                st.success("🎉 전자 근로계약서 체결이 완료되었습니다!")
                if email_ok:
                    st.info(f"입력하신 이메일({email})로 계약서 PDF 사본이 자동 발송되었습니다.")
                st.download_button(
                    label="📄 내 근로계약서 PDF 바로 다운로드",
                    data=pdf_bytes,
                    file_name=filename,
                    mime="application/pdf",
                    use_container_width=True,
                )
                st.stop()
    except Exception as e:
        st.error(f"계약서 처리 중 오류가 발생했습니다: {e}")

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

today_str = datetime.date.today().strftime("%Y-%m-%d")
APP_URL = "https://store-salary-auto-5xqyisbltbombukh3zltva.streamlit.app/"

html_form = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Malgun Gothic", sans-serif; margin: 0; padding: 4px; color: #111827; }}
  .card {{ background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; padding: 18px; }}
  h3 {{ margin-top: 0; font-size: 18px; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  @media (max-width: 640px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  label {{ display: block; font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #374151; }}
  input[type="text"], input[type="email"], input[type="date"], select {{
    width: 100%; box-sizing: border-box; padding: 9px 10px; border: 1px solid #cbd5e1;
    border-radius: 6px; font-size: 14px; background: #fff;
  }}
  .radio-row {{ display: flex; gap: 16px; align-items: center; padding-top: 6px; font-size: 14px; }}
  .sign-box {{ margin-top: 14px; border: 2px dashed #64748b; border-radius: 8px; background: #fff; padding: 10px; max-width: 344px; }}
  canvas {{ border: 1px solid #e2e8f0; border-radius: 4px; touch-action: none; display: block; background: #fff; }}
  .sign-bar {{ display: flex; justify-content: space-between; align-items: center; margin-top: 6px; }}
  .btn-clear {{ padding: 4px 10px; font-size: 12px; border: 1px solid #cbd5e1; border-radius: 4px; background: #f1f5f9; cursor: pointer; }}
  .agree-row {{ margin-top: 14px; font-size: 14px; font-weight: 600; display: flex; align-items: flex-start; gap: 8px; }}
  .btn-submit {{
    margin-top: 16px; width: 100%; padding: 13px; font-size: 16px; font-weight: 700;
    color: #fff; background: #dc2626; border: none; border-radius: 8px; cursor: pointer;
  }}
  .btn-submit:hover {{ background: #b91c1c; }}
</style>
</head>
<body>
<div class="card">
  <h3>✍️ 근로자 인적사항 및 전자서명</h3>
  <form id="signForm" action="{APP_URL}" method="GET" target="_top" onsubmit="return validateAndSubmit();">
    <input type="hidden" name="contract_id" value="{cid}">
    <input type="hidden" name="submit_sign" value="1">
    <input type="hidden" name="sig" id="sigInput" value="">

    <div class="grid">
      <div>
        <label>주민등록번호 (급여·세무신고용)</label>
        <input type="text" name="rrn" id="rrn" placeholder="예: 000101-3123456" required>
      </div>
      <div>
        <label>연락처 (휴대폰)</label>
        <input type="text" name="phone" id="phone" placeholder="예: 010-1234-5678" required>
      </div>
      <div>
        <label>입금 은행명</label>
        <select name="bank">
          <option>국민은행</option><option>신한은행</option><option>우리은행</option>
          <option>하나은행</option><option>농협은행</option><option>기업은행</option>
          <option>카카오뱅크</option><option>토스뱅크</option><option>케이뱅크</option>
          <option>새마을금고</option><option>우체국</option><option>수협은행</option><option>기타</option>
        </select>
      </div>
      <div>
        <label>이메일 주소 (계약서 PDF 사본 수신용)</label>
        <input type="email" name="email" id="email" placeholder="예: hong@naver.com" required>
      </div>
      <div>
        <label>계좌번호 (숫자만 또는 하이픈 포함)</label>
        <input type="text" name="account" id="account" placeholder="예: 123456-01-123456" required>
      </div>
      <div>
        <label>거주지 주소</label>
        <input type="text" name="addr" id="addr" placeholder="예: 경기도 성남시 분당구 ..." required>
      </div>
      <div>
        <label>보건증 제출(예정)일</label>
        <input type="date" name="health_date" value="{today_str}" required>
      </div>
      <div>
        <label>제16조 개인영상정보(CCTV) 수집·이용 동의</label>
        <div class="radio-row">
          <label style="font-weight:normal;"><input type="radio" name="cctv" value="동의함" checked> 동의함</label>
          <label style="font-weight:normal;"><input type="radio" name="cctv" value="동의하지 않음"> 동의하지 않음</label>
        </div>
      </div>
    </div>

    <div class="sign-box">
      <label>자필 서명 (아래 흰 칸에 손가락 또는 마우스로 사인해 주세요)</label>
      <canvas id="pad" width="320" height="140"></canvas>
      <div class="sign-bar">
        <span id="status" style="font-size:12px; color:#475569;">서명 대기 중</span>
        <button type="button" class="btn-clear" onclick="clearPad()">다시 쓰기</button>
      </div>
    </div>

    <div class="agree-row">
      <input type="checkbox" id="agreeChk" style="width:18px; height:18px; margin-top:2px;">
      <label for="agreeChk" style="margin:0; cursor:pointer;">본인({emp_name})은 위 표준근로계약서 1조~17조의 내용을 충분히 확인하고 이에 동의하여 전자서명합니다.</label>
    </div>

    <button type="submit" class="btn-submit">✅ 계약 내용 확인 및 전자서명 최종 제출</button>
  </form>
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

function getPos(e) {{
  const rect = canvas.getBoundingClientRect();
  const clientX = e.touches ? e.touches[0].clientX : e.clientX;
  const clientY = e.touches ? e.touches[0].clientY : e.clientY;
  return [Math.round(clientX - rect.left), Math.round(clientY - rect.top)];
}}

function startDraw(e) {{
  e.preventDefault();
  drawing = true;
  curStroke = [getPos(e)];
  ctx.beginPath();
  ctx.moveTo(curStroke[0][0], curStroke[0][1]);
}}

function moveDraw(e) {{
  if (!drawing) return;
  e.preventDefault();
  const pt = getPos(e);
  curStroke.push(pt);
  ctx.lineTo(pt[0], pt[1]);
  ctx.stroke();
}}

function endDraw(e) {{
  if (!drawing) return;
  drawing = false;
  if (curStroke.length > 0) strokes.push(curStroke);
  document.getElementById('status').innerText = '서명 입력됨 (' + strokes.length + '획)';
}}

function clearPad() {{
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  strokes = [];
  document.getElementById('status').innerText = '서명 대기 중';
}}

function validateAndSubmit() {{
  if (strokes.length === 0) {{
    alert('서명란에 자필 서명을 그려주세요.');
    return false;
  }}
  if (!document.getElementById('agreeChk').checked) {{
    alert('계약 내용 확인 및 전자서명 동의 체크박스를 선택해 주세요.');
    return false;
  }}
  document.getElementById('sigInput').value = JSON.stringify(strokes);
  return true;
}}

canvas.addEventListener('mousedown', startDraw);
canvas.addEventListener('mousemove', moveDraw);
canvas.addEventListener('mouseup', endDraw);
canvas.addEventListener('mouseleave', endDraw);
canvas.addEventListener('touchstart', startDraw, {{ passive: false }});
canvas.addEventListener('touchmove', moveDraw, {{ passive: false }});
canvas.addEventListener('touchend', endDraw);
</script>
</body>
</html>
"""

components.html(html_form, height=690, scrolling=True)
