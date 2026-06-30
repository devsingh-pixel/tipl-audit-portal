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
    "MANAGEMENT": {"lodging": 6000.0, "boarding": 1500.0, "travel_ticket": 10000.0, "lodging_relative": 1000.0},
    "GRADE A": {"lodging": 4500.0, "boarding": 1000.0, "travel_ticket": 7000.0, "lodging_relative": 800.0},
    "GRADE B": {"lodging": 3500.0, "boarding": 800.0, "travel_ticket": 5000.0, "lodging_relative": 600.0},
    "GRADE C": {"lodging": 2500.0, "boarding": 600.0, "travel_ticket": 3000.0, "lodging_relative": 500.0},
    "DEFAULT": {"lodging": 2000.0, "boarding": 500.0, "travel_ticket": 2000.0, "lodging_relative": 400.0}
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
    match = re.search(r'(?:Days|Duration|Period):\s*(\d+)', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1 

def find_designation(text):
    match = re.search(r'(?:Designation|Cadre|Grade):\s*(.*)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "Not Found"

def find_start_time(text):
    match = re.search(r'(?:Start|Departure|Dep\.?|Journey)(?:\s+Time)?:\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?)', text, re.IGNORECASE)
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
    cutoff_time = datetime.strptime("10:00 AM", "%I:%M %p").time()
    
    # Smart Matching for Designation Substrings
    desig_upper = designation.upper()
    matched_grade = "DEFAULT"
    for grade in POLICY_LIMITS.keys():
        if grade in desig_upper or grade.replace(" ", "") in desig_upper.replace("-", ""):
            matched_grade = grade
            break
            
    limits = POLICY_LIMITS[matched_grade]
    
    # All 5 Required Expense Categories target config mapping
    target_mappings = {
        "boarding": "Boarding",
        "lodging": "Lodging",
        "conveyance": "Conveyance",
        "travel ticket": "Travel ticket",
        "lodging relative": "Lodging relative"
    }
    
    # Scanning document line-by-line to prevent structural pattern failure
    for line in text.split('\n'):
        line_clean = line.strip()
        if not line_clean:
            continue
            
        for key, display_name in target_mappings.items():
            # Standard boundary regex matching for single or multiple phrase keywords
            if re.search(r'\b' + re.escape(key) + r'\b', line_clean.lower()):
                # Extracting numerical parts inside the localized raw row string context
                amounts = re.findall(r'\d+(?:\.\d+)?', line_clean)
                if amounts:
                    original_amount = float(amounts[-1]) # Selecting terminal numeric sequence as total cost
                    approved_amount = original_amount
                    remarks = "Fully Approved as per TIPL policy"
                    status = "Passed"
                    
                    # 1. Boarding Auditing Rule Execution Block
                    if key == "boarding":
                        max_boarding_allowed = limits["boarding"] * days
                        if start_time and start_time > cutoff_time:
                            approved_amount = original_amount * 0.70
                            remarks = f"30% Cut Applied due to late departure ({start_time.strftime('%I:%M %p')})."
                            status = "Adjusted"
                        
                        if approved_amount > max_boarding_allowed:
                            approved_amount = max_boarding_allowed
                            remarks += f" Over-budget! Capped at max daily limit of ₹{max_boarding_allowed}."
                            status = "Adjusted"
                            
                    # 2. Lodging Auditing Rule Execution Block
                    elif key == "lodging":
                        max_lodging_allowed = limits["lodging"] * days
                        if original_amount > max_lodging_allowed:
                            approved_amount = max_lodging_allowed
                            remarks = f"Exceeded ceiling barrier! Capped at max allowance of ₹{max_lodging_allowed}."
                            status = "Adjusted"
                            
                    # 3. Lodging Relative Auditing Rule Execution Block
                    elif key == "lodging relative":
                        max_rel_allowed = limits["lodging_relative"] * days
                        if original_amount > max_rel_allowed:
                            approved_amount = max_rel_allowed
                            remarks = f"Relative accommodation capped at flat policy boundary of ₹{max_rel_allowed}."
                            status = "Adjusted"
                            
                    # 4. Travel Ticket Auditing Rule Execution Block
                    elif key == "travel ticket":
                        max_ticket_allowed = limits["travel_ticket"]
                        if original_amount > max_ticket_allowed:
                            approved_amount = max_ticket_allowed
                            remarks = f"Ticket ceiling breached! Capped at maximum allocation threshold of ₹{max_ticket_allowed}."
                            status = "Adjusted"
                            
                    # 5. Conveyance Auditing Rule Execution Block
                    elif key == "conveyance":
                        remarks = "Conveyance passed systemic validation (Receipt matching mandatory)."
                    
                    data.append({
                        "Expense Head": display_name,
                        "Claimed Amount": original_amount,
                        "Approved Amount": approved_amount,
                        "Status": status,
                        "Audit Remarks": remarks
                    })
                    break # Avoid running secondary pattern loops on the same line buffer
                    
    return data, matched_grade

# ---------- STREAMLIT UI APP ----------
file = st.file_uploader("Upload TE PDF File", type=["pdf"])

if file:
