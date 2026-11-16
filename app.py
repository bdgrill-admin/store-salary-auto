import streamlit as st

st.set_page_config(page_title="분당그릴 근태 · 급여 시스템", page_icon="🥩", layout="wide")

pg = st.navigation([
    st.Page("views/attendance.py", title="출퇴근 기록부", icon="⏱️", default=True),
    st.Page("views/payroll.py", title="급여 정산", icon="💰"),
    st.Page("views/staff.py", title="직원 관리", icon="👥"),
])

pg.run()
