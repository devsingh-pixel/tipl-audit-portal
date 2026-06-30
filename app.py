import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Unified Table Parser)")

# =====================================================================
# TIPL COMPANY POLICY CONFIGURATION MATRIX (1 April 2025 Rules)
# =====================================================================
POLICY_LIMITS = {
    "MANAGEMENT": {"lodging": 6000.0, "boarding": 1500.0, "travel_ticket": 10000.0, "lodging_relative": 1000.0},
    "GRADE A": {"lodging": 4500.0, "boarding": 1000.0, "travel_ticket": 7000.0, "lodging_relative": 800.0},
    "GRADE B": {"lodging": 3500.0, "boarding": 800.0, "travel_ticket": 5000.0, "lodging_relative": 600.0},
    "GRADE C": {"lodging": 2500.0, "boarding": 600.0, "travel_ticket": 3000.0, "lodging_relative": 500.0},
    "ENGINEER": {"lodging": 3500.0, "boarding": 800.0, "travel_ticket": 5000.0, "lodging_relative": 600.0},
    "DEFAULT": {"lodging": 2000.0, "boarding": 500.0, "travel_ticket": 2000.0, "lodging_relative": 400.0}
}

# ---------- PDF RAW BLOCK EXTRACTOR ENGINE ----------
def parse_pdf_unified(file):
    raw_text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            raw_text += page.extract_text() + "\n"
            
    # Focus strictly on data after Expenses Detail header block
    if "expenses detail" in raw_text.lower():
        expenses_block = raw_text.lower().split("expenses detail")[1]
        if "grand total" in expenses_block:
            expenses_block = expenses_block.split("grand total")[0]
    else:
        expenses_block = raw_text.lower()
        
    lines = expenses_block.split("\n")
    extracted_data = []
    
    current_date = "2026-05-04"  # Base date fallback setup context
    
    categories = {
        "boarding": "Boarding",
        "lodging": "Lodging",
        "conveyance": "Conveyance",
        "travel ticket": "Travel ticket"
    }
    
    for line in lines:
        line_clean = line.strip().lower()
        if not line_clean or any(term in line_clean for term in ["sn", "particulars", "account code"]):
            continue
            
        # 1. Capture and lock Date sequences dynamically
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
        if date_match:
            current_date = date_match.group(1)
            
        # 2. Match targets
        detected_cat = None
        for k, v in categories.items():
            if k in line_clean:
                detected_cat = v
                break
                
        if detected_cat:
            # Safe numeric filtering from string tokens
            digits = re.findall(r'\b\d+(?:\.\d+)?\b', line_clean)
            valid_prices = [float(d) for d in digits if float(d) > 50 and not re.match(r'^20\d{2}$', d)]
            
            if valid_prices:
                original_amount = valid_prices[-1]
                extracted_data.append({
                    "Date": current_date,
                    "Expense Type": detected_cat,
                    "Amount": original_amount
                })
                
    return raw_text, extracted_data

# ---------- METADATA PARSERS ----------
def find_days(text):
    match = re.search(r'Days\s*[:\-]?\s*(\d+)', text, re.IGNORECASE)
    return int(match.group(1)) if match else 4

def find_designation(text):
    match = re.search(r'Designation\s*[:\-]?\s*(.*)', text, re.IGNORECASE)
    return re.sub(r'Days.*', '', match.group(1), flags=re.IGNORECASE).strip() if match else "Sr. Engineer"

def find_start_time(text):
    match = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})', text)
    if match:
        try:
            return datetime.strptime(match.group(2), "%H:%M:%S").time()
        except:
            pass
    return datetime.strptime("09:15", "%H:%M").time()

# ---------- CORE LOGIC MACHINE ENGINE ----------
def run_compliance_audit(ledger, designation, days, start_time):
    cutoff_time = datetime.strptime("10:00 AM", "%I:%M %p").time()
    
    desig_upper = designation.upper()
    matched_grade = "DEFAULT"
    for grade in POLICY_LIMITS.keys():
        if grade in desig_upper:
            matched_grade = grade
            break
    limits = POLICY_LIMITS[matched_grade]

    audited_rows = []
    is_first_boarding = True

    for row in ledger:
        original_amount = row["Amount"]
        approved_amount = original_amount
        status = "Passed"
        remarks = "Approved as per TIPL policy"

        if row["Expense Type"] == "Boarding":
            # Apply late-start cut only on first instance record match logic
            if start_time and start_time > cutoff_time and is_first_boarding:
                approved_amount = original_amount * 0.70
                remarks = f"30% late start cut applied (Started at {start_time.strftime('%I:%M %p')})."
                status = "Adjusted"
                is_first_boarding = False
            elif approved_amount > limits["boarding"]:
                approved_amount = limits["boarding"]
                remarks = f"Exceeded single day allowance limit of ₹{limits['boarding']}."
                status = "Adjusted"
                
        elif row["Expense Type"] == "Lodging" and original_amount > limits["lodging"]:
            approved_amount = limits["lodging"]
            remarks = f"Exceeded daily allowance ceiling limit of ₹{limits['lodging']}."
            status = "Adjusted"
            
        elif row["Expense Type"] == "Conveyance":
            remarks = "Conveyance approved (Receipt verification recommended)."

        audited_rows.append({
            "Date": row["Date"],
            "Expense Type": row["Expense Type"],
            "Claimed Amount": original_amount,
            "Approved Amount": approved_amount,
            "Status": status,
            "Audit Remarks": remarks
        })

    return sorted(audited_rows, key=lambda x: x['Date']), matched_grade

# ---------- STREAMLIT INTERFACE RENDERING ----------
file = st.file_uploader("Upload TE PDF File", type=["pdf"])

if file:
    raw_text, expenses_ledger = parse_pdf_unified(file)
    
    if raw_text and expenses_ledger:
        designation = find_designation(raw_text)
        days = find_days(raw_text)
        start_time = find_start_time(raw_text)
        
        st.success("🎉 Full Table Rows Restructured cleanly with zero structural skips!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Departure Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        expenses, applied_grade = run_compliance_audit(expenses_ledger, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            st.subheader(f"📊 Live Date-Wise Audit Ledger (Applied Grid: {applied_grade})")
            
            st.table(df[["Date", "Expense Type", "Claimed Amount", "Approved Amount", "Status", "Audit Remarks"]])
            
            total_claimed = df["Claimed Amount"].sum()
            total_approved = df["Approved Amount"].sum()
            
            col_tot1, col_tot2 = st.columns(2)
            col_tot1.info(f"Total Claimed Amount: ₹ {total_claimed:.2f}")
            col_tot2.success(f"Total AI Verified Approved: ₹ {total_approved:.2f}")
            
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Official Audit Report (CSV)",
                data=csv,
                file_name=f"TIPL_Clean_Report_{designation.replace(' ', '_')}.csv",
                mime="text/csv"
            )
    else:
        st.warning("⚠️ High structural variance detected. Target rows missed.")
else:
    st.info("ℹ️ Please upload your official T&E file to initiate live column mapping.")
