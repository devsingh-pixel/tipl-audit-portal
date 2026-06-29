import streamlit as st
import google.generativeai as genai
from pypdf import PdfReader
import urllib.parse

# Page Configuration
st.set_page_config(page_title="TIPL TE Rules Audit Portal v3", layout="wide")

st.title("🛄 TIPL Travel Expense & Conveyance Audit Portal")
st.write("Upload tour bills or local conveyance vouchers. Designation will be automatically fetched from the file based on [TIPL TE Rules (w.e.f. 1 April 2025)](http://live.tipl.com/pdf/TIPL_TE%20Rules_w.e.f.%201%20April.2025.pdf).")

# Sidebar for Setup & Employee Details
st.sidebar.header("📋 Setup & Manual Details")
api_key = st.sidebar.text_input("Enter Google AI Studio API Key:", type="password")

# Designation dropdown removed to auto-fetch from file text
gender = st.sidebar.selectbox("Gender:", ["Male", "Female"])
city_category = st.sidebar.selectbox("City Category:", ["Metro (Mumbai)", "Metros (Delhi, Kolkata, Chennai, NCR, Bangalore, Hyderabad)", "State Capitals", "Other Cities"])

st.sidebar.markdown("---")
st.sidebar.header("🗺️ Quick Distance Verify (Google Maps)")
origin = st.sidebar.text_input("From (Source):", placeholder="e.g., Adarsh Nagar")
destination = st.sidebar.text_input("To (Destination):", placeholder="e.g., Pvt Bus Stand Jaipur Road")

if origin and destination:
    query = f"{origin} to {destination}"
    maps_url = f"https://www.google.com/maps/dir/{urllib.parse.quote(origin)}/{urllib.parse.quote(destination)}"
    st.sidebar.markdown(f"🔗 [Verify Distance on Google Maps]({maps_url})")

uploaded_file = st.file_uploader("Upload Tour Bill / Conveyance Voucher (PDF)", type=["pdf"])

if st.button("Run Instant Audit") and uploaded_file and api_key:
    genai.configure(api_key=api_key)
    
    # Extract text from PDF
    reader = PdfReader(uploaded_file)
    pdf_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pdf_text += text
        
    # AI Prompt embedding accurate TIPL Policy Guidelines & Auto-fetch Instruction
    prompt = f"""
    You are an expert internal auditor for TIPL. First, extract the employee's designation automatically from the text. Then audit the text based strictly on the TIPL TE Rules w.e.f. 1 April 2025.
    
    Employee Context:
    - Gender: {gender}
    - City Category: {city_category}
    
    Designation & Lodging/Hotel Limits per day Matrix to apply after auto-fetching:
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
       
    Strict Rules to Validate:
    1. Special Lodging Allowances:
       - Mumbai Location: Additional Rs. 200 allowance for Lodging.
       - Female Employees: Additional Rs. 200 allowance for Lodging.
       - No Hotel stay/Own arrangement: Pay 40% of max lodging (Max Rs. 400).
    2. Boarding (Food) Splits (Breakfast 30%, Lunch 30%, Dinner 30%, Miscellaneous 10%): Check if time limits match or if customer provided meals (Rs. 100 limit if all meals provided).
    3. Local Conveyance & Distance Rules:
       - Short Distance (<5 km): Auto Rickshaw (Ola/Uber/Local) must be used. Taxi not allowed unless exceptional.
       - Longer Distance: OLA/Uber Taxi allowed if no economic/faster way. Metro/Local trains preferred where available.
       - Distance Disclosure: Ensure origin and destination are clearly written (e.g., 'From X to Y'). If missing, flag it.
       - Short travel (<100km or <300km in home state): Only Bus or Train Chair Car allowed unless approved.
    
    Expense Text to Audit:
    {pdf_text}
    
    Output Format:
    ### 📊 Audit Report
    - **Fetched Designation:** [Identify and display the employee's designation found in the text. If not found, mention 'Not Found in Text' and state which limits you assumed based on standard guessing]
    - **Total Claimed Amount:** [Extract from text]
    - **Allowed Amount as per Rules:** [Calculate based on rules for the fetched designation]
    - **Conveyance Audit:** [Check if source/destination is mentioned, if distance looks reasonable, and mode used like Auto vs Taxi for <5km]
    - **Violations/Remarks:** [List any non-compliance or missing details clear and direct]
    """
    
    model = genai.GenerativeModel('models/gemini-1.5-flash')
    
    with st.spinner("Fetching designation & auditing text..."):
        try:
            response = model.generate_content(prompt)
            st.subheader("📋 Final Audit Results")
            st.write(response.text)
        except Exception as e:
            st.error(f"Error during AI Generation: {e}")
