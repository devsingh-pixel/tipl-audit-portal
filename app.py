import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader

# Page Configuration
st.set_page_config(page_title="TIPL TE Rules Fully-Auto Audit Portal", layout="wide")

st.title("🛄 TIPL Travel Expense Fully-Automatic Audit Portal")
st.write("Upload tour bills or expense logs. The AI will automatically fetch Designation, City Category, and audit Conveyance based on [TIPL TE Rules (w.e.f. 1 April 2025)](http://live.tipl.com/pdf/TIPL_TE%20Rules_w.e.f.%201%20April.2025.pdf).")

# Sidebar - ONLY Gender and API Key required!
st.sidebar.header("📋 Setup & Manual Inputs")
api_key = st.sidebar.text_input("Enter Google AI Studio API Key:", type="password")
gender = st.sidebar.selectbox("Gender of Employee:", ["Male", "Female"])

uploaded_file = st.file_uploader("Upload Tour Bill / Expense Text / PDF", type=["pdf", "txt"])

if st.button("Run Fully-Automatic Audit") and uploaded_file and api_key:
    # Proper SDK Initialization
    genai.configure(api_key=api_key)
    
    # Extract text from PDF
    pdf_text = ""
    if uploaded_file.type == "application/pdf":
        reader = PdfReader(uploaded_file)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pdf_text += text
    else:
        pdf_text = uploaded_file.read().decode("utf-8")
        
    # Super Prompt that tracks city category and conveyance entries automatically
    prompt = f"""
    You are an expert internal auditor for TIPL. Analyze the uploaded text completely. 
    Track all entries including Lodging, Boarding, and individual Conveyance (e.g., Home to Site, Station to Hotel, etc.).
    
    Input given by user:
    - Employee Gender: {gender}
    
    TASK 1: AUTOMATIC CONTEXT EXTRACTION FROM TEXT
    1. Identify the Employee's Designation from the text.
    2. Identify the visited places/cities from the text and automatically categorize the City Category for each day/expense based on these rules:
       - 'Metro (Mumbai)' if Mumbai is mentioned.
       - 'Metros' if Delhi, Kolkata, Chennai, NCR, Bangalore, Hyderabad are mentioned.
       - 'State Capitals' if any state capital (e.g., Jaipur, Lucknow) is mentioned.
       - 'Other Cities' for places like Anpra, Singrauli, Rihand, etc.
    
    TASK 2: STRICT AUDIT VALIDATION (TIPL TE Rules w.e.f. 1 April 2025)
    1. Lodging/Hotel Limits Per Day Matrix (Apply based on auto-fetched Designation and calculated City Category):
       - Workmen: Metro=550, State Capital=500, Other=450
       - Trainees/Junior Executive/Executive/Jr. Tech. Assistant/Tech. Asst./Jr Engineer: Metro=900, State Capital=800, Other=700
       - Sr. Executive/Asst. Team Lead/Asst. Engineer: Metro=950, State Capital=850, Other=750
       - Team Lead/Sr. Team Lead/Engineer/Sr. Engineer: Metro=1050, State Capital=950, Other=850
       - Asst. Managers/Deputy Managers: Metro=1200, State Capital=1100, Other=1000
       - Managers/Sr. Managers: Metro=1350, State Capital=1250, Other=1150
       - AGM: Metro=1500, State Capital=1400, Other=1300
       - DGM: Metro=1600, State Capital=1500, Other=1400
       - GM: Metro=1700, State Capital=1600, Other=1500
       - Sr. GM & above: Metro=1800, State Capital=1700, Other=1600
       
    2. Special Lodging Adjustments:
       - If Mumbai or Female employee: Add Rs. 200 extra to the daily lodging limit.
       - Own Arrangement/No Hotel bill: Pay 40% of max lodging (Max Rs. 400).
       
    3. Conveyance & Journey Audit:
       - Look at every individual conveyance line (e.g., 'Roza chowk to Railway station', 'Saktinagar to NTPC gate').
       - Validate Mode of Transport: For short distances (<5 km), Auto Rickshaw must be used. Taxi is NOT allowed unless justified (e.g., heavy rain, route diverted, mountains).
       - Distance check: Verify if the claimed Km and amount match standard expectations. If Source and Destination are missing, flag it.
       - Short travel (<100km or <300km in home state): Only Bus or Train Chair Car allowed unless approved.
    
    Expense Document Text:
    {pdf_text}
    
    Output Format (Strictly structured):
    ### 📊 Fully-Automatic Audit Report
    - **Detected Designation:** [Designation name]
    - **Detected Places & City Categories:** [e.g., Anpra (Other Cities), Mumbai (Metro)]
    
    #### 💰 Financial Summary
    - **Total Claimed Amount:** Rs. [Total]
    - **Total Allowed Amount:** Rs. [Calculated Total]
    
    #### 🚗 Individual Conveyance Audit
    [Go row-by-row for each conveyance entry found in text. Check if Mode used (Auto/Taxi) matches the distance and if remarks like 'heavy rain/route diverted' justify any deviations. State whether it is Approved or Flagged.]
    
    #### ⚠️ Non-Compliance & Violations
    [List specific violations, over-claimed amounts, or missing details clearly.]
    """
    
    with st.spinner("Analyzing text, fetching details and auditing conveyance..."):
        try:
            # Using the absolute verified string identifier format for modern genai python packages
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(prompt)
            st.subheader("📋 Final Audit Results")
            st.write(response.text)
        except Exception as e:
            # Ultimate fail-safe if the system strictly expects text-generation model labels
            try:
                model_alt = genai.GenerativeModel('gemini-pro')
                response_alt = model_alt.generate_content(prompt)
                st.subheader("📋 Final Audit Results")
                st.write(response_alt.text)
            except Exception as e2:
                st.error(f"Initialization Error: Please verify your API Key or library versions. Info: {e2}")
