import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader

# Page Configuration
st.set_page_config(page_title="TIPL TE Rules Fully-Auto Audit Portal", layout="wide")

st.title("🛄 TIPL Travel Expense Fully-Automatic Audit Portal")
st.write("Upload tour bills or expense logs. The AI will automatically fetch Designation, City Category, and audit Conveyance based on [TIPL TE Rules (w.e.f. 1 April 2025)](http://live.tipl.com/pdf/TIPL_TE%20Rules_w.e.f.%201%20April.2025.pdf).")

# Sidebar Setup
st.sidebar.header("📋 Setup & Manual Inputs")
# Universal key injection container
api_key_input = st.sidebar.text_input("Enter your Gemini API Key / Access Token:", value="AQ.Ab8RN6JlJppsRRWjK9Hny4kK_SDbZ8aP-SBlMu7R4EfaO3rOwQ", type="password")
gender = st.sidebar.selectbox("Gender of Employee:", ["Male", "Female"])

uploaded_file = st.file_uploader("Upload Tour Bill / Expense Text / PDF", type=["pdf", "txt"])

if st.button("Run Fully-Automatic Audit") and uploaded_file:
    if not api_key_input:
        st.error("🔑 Please enter the API key or token in the sidebar!")
    else:
        # Strip any extra spaces
        clean_key = api_key_input.strip()
        genai.configure(api_key=clean_key)
        
        # Extract text from file
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
        1. Identify the Employee's Designation from the text (e.g., Sr. Engineer).
        2. Identify the visited places/cities from the text and automatically categorize the City Category for each day/expense based on these rules:
           - 'Metro (Mumbai)' if Mumbai is mentioned.
           - 'Metros' if Delhi, Kolkata, Chennai, NCR, Bangalore, Hyderabad are mentioned.
           - 'State Capitals' if any state capital (e.g., Jaipur, Lucknow) is mentioned.
           - 'Other Cities' for places like Anpra, Singrauli, Rihand, Vindhyachal etc.
        
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
           - Look at every individual conveyance line.
           - Validate Mode of Transport: For short distances (<5 km), Auto Rickshaw must be used. Taxi is NOT allowed unless justified (e.g., heavy rain, route diverted, mountains).
           - Distance check: Verify if the claimed Km and amount match standard expectations.
        
        Expense Document Text:
        {pdf_text}
        
        Output Format (Strictly structured):
        ### 📊 Fully-Automatic Audit Report
        - **Detected Designation:** [Designation name]
        - **Detected Places & City Categories:** [e.g., Anpra (Other Cities)]
        
        #### 💰 Financial Summary
        - **Total Claimed Amount:** Rs. [Total]
        - **Total Allowed Amount:** Rs. [Calculated Total]
        
        #### 🚗 Individual Conveyance Audit
        [Go row-by-row for each conveyance entry found in text. Check if Mode used (Auto/Taxi) matches the distance and if remarks like 'heavy rain/route diverted' justify any deviations. State whether it is Approved or Flagged.]
        
        #### ⚠️ Non-Compliance & Violations
        [List specific violations, over-claimed amounts, or missing details clearly.]
        """
        
        with st.spinner("Analyzing uploaded bill, fetching details and auditing..."):
            try:
                # Direct generation call setup using absolute identifier mapping
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(prompt)
                st.subheader("📋 Final Audit Results")
                st.write(response.text)
            except Exception as e:
                st.error(f"Error executing audit: {e}. Please make sure your token is active or input a new key string.")
