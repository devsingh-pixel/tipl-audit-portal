import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (FY 2025-26 Compliant)")

# =====================================================================
# TIPL COMPANY POLICY CONFIGURATION MATRIX (As per 1 April 2025 Rules)
# =====================================================================
POLICY_LIMITS = {
    "MANAGEMENT": {"lodging": 6000.0, "boarding": 1500.0},
    "GRADE A": {"lodging": 4500.0, "boarding": 1000.0},
    "GRADE B": {"lodging": 3500.0, "boarding": 800.0},
    "GRADE C": {"lodging": 2500.0, "boarding": 600.0},
    "DEFAULT": {"lodging": 2000.0, "boarding": 500.0}
}

# ---------- PDF TEXT EXTRACTION ----------
def extract_text(file):
    text = ""
    try:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        st.error(f"🚨 Error reading PDF file: {e}")
        return None
    return text

# ---------- FIND TOUR DETAILS ----------
def find_days(text):
    match = re.search(r'Days\s+(\d+)', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1 # Default 1 day if not specified

def find_designation(text):
    match = re.search(r'Designation:\s*(.*)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Not Found"

def find_start_time(text):
    # RegEx to match patterns like "Start Time: 10:30 AM" or "Departure: 14:15"
    match = re.search(r'(?:Start Time|Departure Time|Departure):\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?)', text, re.IGNORECASE)
    if match:
        time_str = match.group(1).strip()
        try:
            if "AM" in time_str.upper() or "PM" in time_str.upper():
                return datetime.strptime(time_str.upper(), "%I:%M %p").time()
            else:
                return datetime.strptime(time_str, "%H:%M").time()
        except Exception:
            pass
    return None

# ---------- CORE AUTOMATED AUDIT ENGINE ----------
def process_and_audit_expenses(text, designation, days, start_time):
    data = []
    # Flexible amount regex to catch both whole numbers and decimals
    pattern = r'\d+\s+\d+\s+([A-Za-z()]+).*?(\d+(?:\.\d+)?)'
    rows = re.findall(pattern, text, re.DOTALL)
    
    # 10:00 AM Boarding Cutoff Setup
    cutoff_time = datetime.strptime("10:00 AM", "%I:%M %p").time()
    
    # Determine Policy Rules based on Designation
    desig_upper = designation.upper()
    matched_grade = "DEFAULT"
    for grade in POLICY_LIMITS.keys():
        if grade in desig_upper:
            matched_grade = grade
            break
            
    limits = POLICY_LIMITS[matched_grade]
    
    for name, amount in rows:
        expense_head = name.strip().capitalize()
        if expense_head.lower() in ["conveyance", "lodging", "boarding"]:
            original_amount = float(amount)
            approved_amount = original_amount
            remarks = "Fully Approved as per policy"
            status = "Passed"
            
            # RULE 1: Boarding Time-based & Cap Audit
            if expense_head.lower() == "boarding":
                max_boarding_allowed = limits["boarding"] * days
                
                # Check 10:00 AM Rule
                if start_time and start_time > cutoff_time:
                    approved_amount = original_amount * 0.70 # 30% cut applied
                    remarks = f"30% Cut Applied (Tour started late: {start_time.strftime('%I:%M %p')})."
                    status = "Adjusted"
                
                # Check Cap Limit Violation
                if approved_amount > max_boarding_allowed:
                    approved_amount = max_boarding_allowed
                    remarks += f" Capped at max policy limit of ₹{max_boarding_allowed} for {matched_grade}."
                    status = "Adjusted"
                    
            # RULE 2: Lodging Cap Audit
            elif expense_head.lower() == "lodging":
                max_lodging_allowed = limits["lodging"] * days
                if original_amount > max_lodging_allowed:
                    approved_amount = max_lodging_allowed
                    remarks = f"Exceeded limit! Capped at max allowed ₹{max_lodging_allowed} for {matched_grade}."
                    status = "Adjusted"
            
            # RULE 3: Conveyance Validation (Basic Policy Check)
            elif expense_head.lower() == "conveyance":
                remarks = "Conveyance approved subject to manager's approval."
            
            data.append({
                "Expense Head": expense_head,
                "Claimed Amount": original_amount,
                "Approved Amount": approved_amount,
                "Status": status,
                "Audit Remarks": remarks
            })
            
    return data, matched_grade

# ---------- STREAMLIT UI APP ----------
file = st.file_uploader("Upload TE PDF File", type=["pdf"])

if file:
    text = extract_text(file)
    
    if text:
        designation = find_designation(text)
        days = find_days(text)
        start_time = find_start_time(text)
        
        st.success("🎉 PDF Successfully Uploaded & Parsed!")
        
        # Metadata Dashboard Section
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Start Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        # Process and Audit Engine Call
        expenses, applied_grade = process_and_audit_expenses(text, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            
            st.subheader(f"📊 TIPL Policy Engine Summary (Applied Grade Grid: {applied_grade})")
            
            # Render complete transparent audit table
            st.table(df[["Expense Head", "Claimed Amount", "Approved Amount", "Status", "Audit Remarks"]])
            
            total_claimed = df["Claimed Amount"].sum()
            total_approved = df["Approved Amount"].sum()
            
            col_tot1, col_tot2 = st.columns(2)
            col_tot1.info(f"Total Employee Claimed: ₹ {total_claimed:.2f}")
            col_tot2.success(f"Total AI System Approved: ₹ {total_approved:.2f}")
            
            # CSV Download Generation
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Official Audit Report (CSV)",
                data=csv,
                file_name=f"TIPL_Audit_Report_{designation.replace(' ', '_')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("⚠️ No valid JV Expense Head rows (Boarding/Lodging/Conveyance) detected.")
else:
    st.info("ℹ️ Please upload the tour expense claim PDF to initiate the automatic audit process.")
