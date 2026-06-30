import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Final Clean Auditor)")

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

# ---------- METADATA EXTRACTION ----------
def find_days(text):
    match = re.search(r'Days\s*[:\-]?\s*(\d+)', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1 

def find_designation(text):
    match = re.search(r'Designation\s*[:\-]?\s*(.*)', text, re.IGNORECASE)
    if match:
        clean_desig = re.sub(r'Days.*', '', match.group(1), flags=re.IGNORECASE).strip()
        return clean_desig
    return "Not Found"

def find_start_time(text):
    match = re.search(r'(?:Start|Departure|Dep\.?|Journey)(?:\s+Time)?:\s*(\d{1,2}:\d{2}(?:\s*:\d{2})?\s*(?:AM|PM)?)', text, re.IGNORECASE)
    if match:
        time_str = match.group(1).strip()
        try:
            time_str_clean = re.sub(r':\d{2}$', '', time_str) if len(time_str.split(':')) == 3 else time_str
            if "AM" in time_str_clean.upper() or "PM" in time_str_clean.upper():
                return datetime.strptime(time_str_clean.upper(), "%I:%M %p").time()
            else:
                return datetime.strptime(time_str_clean, "%H:%M").time()
        except Exception:
            pass
    return None

# ---------- SMART DATE-WISE GROUPED AUDITOR ----------
def audit_expenses_detail(text, designation, days, start_time):
    # Strict isolation: Focus only on content after "Expenses Detail"
    if "expenses detail" in text.lower():
        target_section = text.lower().split("expenses detail")[1]
    else:
        target_section = text.lower()

    cutoff_time = datetime.strptime("10:00 AM", "%I:%M %p").time()
    
    desig_upper = designation.upper()
    matched_grade = "DEFAULT"
    for grade in POLICY_LIMITS.keys():
        if grade in desig_upper:
            matched_grade = grade
            break
    limits = POLICY_LIMITS[matched_grade]

    categories = {
        "boarding": "Boarding",
        "lodging": "Lodging",
        "conveyance": "Conveyance",
        "travel ticket": "Travel ticket",
        "lodging relative": "Lodging relative"
    }

    raw_lines = target_section.split("\n")
    
    # Dictionary to aggregate amounts: key as (Date, Expense Type) -> value as total amount
    aggregated_claims = {}
    current_date = "In Travelling"

    for line in raw_lines:
        line_clean = line.strip()
        
        # Hard skip for summary or total rows
        if any(term in line_clean for term in ["total", "grand", "sub", "jv"]):
            continue

        # Extract Date if present in the line
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
        if date_match:
            current_date = date_match.group(1)
        
        # Check for category match
        detected_category = None
        for cat_key in categories.keys():
            if cat_key in line_clean:
                detected_category = categories[cat_key]
                break
                
        if detected_category:
            amounts = re.findall(r'\d+(?:\.\d+)?', line_clean)
            if amounts:
                # Exclude strings that resemble years or tiny noise figures
                valid_amounts = [float(amt) for amt in amounts if float(amt) > 50 and not re.match(r'^20\d{2}$', amt)]
                if not valid_amounts:
                    continue
                original_amount = valid_amounts[-1]
                
                # Combine matching date + category to prevent repetition rows
                key = (current_date, detected_category)
                aggregated_claims[key] = aggregated_claims.get(key, 0.0) + original_amount

    # Process audited rules over the clean aggregated dataset
    audit_data = []
    is_first_boarding_processed = False

    for (row_date, expense_head), total_claimed_amt in aggregated_claims.items():
        approved_amount = total_claimed_amt
        status = "Passed"
        remarks = "Approved as per policy"

        # --- 1. Boarding Automation Check ---
        if expense_head == "Boarding":
            # Apply 30% cut if it's the start/first record of boarding and time > 10 AM
            if start_time and start_time > cutoff_time and not is_first_boarding_processed:
                approved_amount = total_claimed_amt * 0.70
                remarks = f"30% Late Start Cut applied (Started at {start_time.strftime('%I:%M %p')})"
                status = "Adjusted"
                is_first_boarding_processed = True
            
            if approved_amount > limits["boarding"]:
                approved_amount = limits["boarding"]
                remarks = f"Exceeded daily allowance limit of ₹{limits['boarding']}."
                status = "Adjusted"

        # --- 2. Lodging Automation Check ---
        elif expense_head == "Lodging":
            if total_claimed_amt > limits["lodging"]:
                approved_amount = limits["lodging"]
                remarks = f"Exceeded single day limit of ₹{limits['lodging']}."
                status = "Adjusted"

        # --- 3. Other Dynamic Modules ---
        elif expense_head == "Lodging relative" and total_claimed_amt > limits["lodging_relative"]:
            approved_amount = limits["lodging_relative"]
            remarks = "Capped at relative stay limit."
            status = "Adjusted"
        elif expense_head == "Travel ticket" and total_claimed_amt > limits["travel_ticket"]:
            approved_amount = limits["travel_ticket"]
            remarks = "Ticket price exceeded policy ceiling thresholds."
            status = "Adjusted"
        elif expense_head == "Conveyance":
            remarks = "Conveyance approved (Receipt matching mandatory)."

        audit_data.append({
            "Date": row_date,
            "Expense Type": expense_head,
            "Claimed Amount": total_claimed_amt,
            "Approved Amount": approved_amount,
            "Status": status,
            "Audit Remarks": remarks
        })

    # Sort data by Date to look professional
    audit_data = sorted(audit_data, key=lambda x: x['Date'])
    return audit_data, matched_grade

# ---------- STREAMLIT UI APP ----------
file = st.file_uploader("Upload TE PDF File", type=["pdf"])

if file:
    text = extract_text(file)
    if text:
        designation = find_designation(text)
        days = find_days(text)
        start_time = find_start_time(text)
        
        st.success("🎉 PDF Successfully Uploaded & Audited!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Departure Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        expenses, applied_grade = audit_expenses_detail(text, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            st.subheader(f"📊 Live Date-Wise Audit Ledger (Applied Grid: {applied_grade})")
            
            # Rendering final clean table without repetitions
            st.table(df[["Date", "Expense Type", "Claimed Amount", "Approved Amount", "Status", "Audit Remarks"]])
            
            total_claimed = df["Claimed Amount"].sum()
            total_approved = df["Approved Amount"].sum()
            
            col_tot1, col_tot2 = st.columns(2)
            col_tot1.info(f"Total Claimed: ₹ {total_claimed:.2f}")
            col_tot2.success(f"Total Approved: ₹ {total_approved:.2f}")
            
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Clean Audit Report (CSV)",
                data=csv,
                file_name=f"TIPL_Clean_Report_{designation.replace(' ', '_')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("⚠️ No valid individual records caught inside 'Expenses Detail' zone.")
else:
    st.info("ℹ]. Please upload your official T&E file to initiate live policy mapping.")
