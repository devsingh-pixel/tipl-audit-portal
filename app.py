import streamlit as st

st.set_page_config(page_title="TIPL AI Audit Portal")

st.title("TIPL AI Travel Expense Auditor")
st.write("App Under Development")
import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="TIPL AI Audit Portal", layout="wide")

# Read API from Streamlit Secrets
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Load Gemini Model
model = genai.GenerativeModel("gemini-2.5-flash")

st.title("🤖 TIPL AI Travel Expense Auditor")

if st.button("Test Gemini API"):

    response = model.generate_content("Reply with only: Gemini Connected Successfully")

    st.success(response.text)
