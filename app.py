import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader

# Page Configuration
st.set_page_config(page_title="TIPL TE Rules Audit Portal", layout="wide")

st.title("🛄 TIPL Travel Expense Audit Portal")
st.write("Upload your tour bill or voucher PDF to audit based on TIPL TE Rules (w.e.f. 1 April 2025).")

# Sidebar for API Key & Employee Details
st.sidebar.header("📋 Setup & Employee Details")
api_key = st.sidebar.text_input("Enter Google AI Studio API Key:", type="password")

designation = st.sidebar.selectbox("Employee Designation:", ["Executive", "Manager", "Senior Manager", "VP/Director"])
gender = st.sidebar.selectbox("Gender:", ["Male", "Female"])
city_category = st.sidebar.selectbox("City Category:", ["Metro (Delhi, Mumbai, etc.)", "Major Cities", "Other Cities"])

uploaded_file = st.file_uploader("Upload Tour Bill / Expense Voucher (PDF)", type=["pdf"])

if st.button("Run Instant Audit") and uploaded_file and api_key:
    genai.configure(api_key=api_key)
    
    # Extract text from PDF
    reader = PdfReader(uploaded_file)
    pdf_text = ""
    for page in reader.pages:
        pdf_text += page.extract_text()
        
    # AI Prompt for TIPL Rules
    prompt = f"""
    You are an expert internal auditor for TIPL. Audit the following expense text based on TIPL TE Rules w.e.f. 1 April 2025.
    Employee Details: Designation: {designation}, Gender: {gender}, City: {city_category}.
    
    Extract and calculate:
    1. Total Boarding Days claimed and allowed.
    2. Total Hotel Nights spent and allowed.
    3. Any violations or non-compliant amounts.
    
    Expense Text:
    {pdf_text}
    """
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    with st.spinner("Auditing bill text..."):
        response = model.generate_content(prompt)
        st.subheader("📊 Audit Report")
        st.write(response.text)
