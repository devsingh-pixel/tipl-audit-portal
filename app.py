import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Date-Wise Auditor)")

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
            # Cleansing for formats like 09:15:00
            time_str_clean = re.sub(r':\d{2}$', '', time_str) if len(time_str.split(':')) == 3 else time_str
            if "AM" in time_str_clean.upper() or "PM" in time_str_clean.upper():
                return datetime.strptime(time_str_clean.upper(), "%I:%M %p").time()
            else:
                return datetime.strptime(time_str_clean, "%H:%M").time()
        except Exception:
            pass
    return None

# ---------- METICULOUS EXPENSES DETAIL AUDITOR ----------
def audit_expenses_detail(text, designation, days, start_time):
    # Split text to only capture data AFTER "Expenses Detail" section to eliminate JV Detail duplication
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

    # Mapping keywords to human-readable names
    categories = {
        "boarding": "Boarding",
        "lodging": "Lodging",
        "conveyance": "Conveyance",
        "travel ticket": "Travel ticket",
        "lodging relative": "Lodging relative"
    }

    raw_lines = target_section.split("\n")
    audit_data = []

    for i, line in enumerate(raw_lines):
        # Look for Date pattern (e.g., 2026-05-04 or 2026-05-05)
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
        
        # Determine current expense type in the line
        detected_category = None
        for cat_key in categories.keys():
            if cat_key in line:
                detected_category = categories[cat_key]
                break
                
        if detected_category:
            # Extract the amount (usually the standalone number at the end or before 'bill copy')
            amounts = re.findall(r'\d+(?:\.\d+)?', line)
            if amounts:
                # Find the actual amount by skipping the date tokens if any
                valid_amounts = [float(amt) for amt in amounts if float(amt) > 50 and not re.match(r'^\d{4}$', amt)]
                if not valid_amounts:
                    continue
                original_amount = valid_amounts[-1] # Pick the actual expense amount
                
                # Default assignments
                approved_amount = original_amount
                status = "Passed"
                remarks = "Approved as per policy"
                row_date = date_match.group(1) if date_match else "In Travelling"

                # If date is missing on this specific line, check previous lines for contextual date buffer
                if row_date == "In Travelling" and i > 0:
                    prev_date_match = re.search(r'(\d{4}-\d{2}-\d{2})', raw_lines[i-1])
                    if prev_date_match:
                        row_date = prev_date_match.group(1)

                # --- 1. Date-Wise Boarding Audit ---
                if detected_category == "Boarding":
                    # Policy validation: check if it's the first day of travel and time is after 10:00 AM
                    if start_time and start_time > cutoff_time and ("travelling" in line or audit_data == []):
                        approved_amount = original_amount * 0.70
                        remarks = f"30% Late Start Cut applied (Tour started at {start_time.strftime('%I:%M %p')})"
                        status = "Adjusted"
                    
                    if approved_amount > limits["boarding"]:
                        approved_amount = limits["boarding"]
                        remarks = f"Exceeded daily allowance ceiling of ₹{limits['boarding']}."
                        status = "Adjusted"

                # --- 2. Lodging Cap Audit ---
                elif detected_category == "Lodging":
                    if original_amount > limits["lodging"]:
                        approved_amount = limits["lodging"]
                        remarks = f"Exceeded single day limit of ₹{limits['lodging']}."
                        status = "Adjusted"

                # --- 3. Conveyance, Tickets, & Relatives Audits ---
                elif detected_category == "Lodging relative" and original_amount > limits["lodging_relative"]:
                    approved_amount = limits["lodging_relative"]
                    remarks = "Capped at relative stay daily limit."
                    status = "Adjusted"
                elif detected_category == "Travel ticket" and original_amount > limits["travel_ticket"]:
                    approved_amount = limits["travel_ticket"]
                    remarks = "Ticket cost exceeded policy limits."
                    status = "Adjusted"
                elif detected_category == "Conveyance":
                    remarks = "Conveyance approved (Receipt matching recommended)."

                audit_data.append({
                    "Date": row_date,
                    "Expense Type": detected_category,
                    "Claimed Amount": original_amount,
                    "Approved Amount": approved_amount,
                    "Status": status,
                    "Audit Remarks": remarks
                })

    return audit_data, matched_grade

# ---------- STREAMLIT UI APP ----------
file = st.file_uploader("Upload TE PDF File", type=["pdf"])

if file:
    text = extract_text(file)
    if text:
        designation = find_designation(text)
        days = find_days(text)
        start_time = find_start_time(text)
        
        st.success("🎉 Expenses Detail Section Parsed Successfully!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Departure Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        expenses, applied_grade = audit_expenses_detail(text, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            st.subheader(f"📊 Date-Wise Audit Ledger (Applied Matrix: {applied_grade})")
            
            # Displaying ultra clean ledger view
            st.table(df[["Date", "Expense Type", "Claimed Amount", "Approved Amount", "Status", "Audit Remarks"]])
            
            total_claimed = df["Claimed Amount"].sum()
            total_approved = df["Approved Amount"].sum()
            
            col_tot1, col_tot2 = st.columns(2)
            col_tot1.info(f"Total Claimed (Base Records): ₹ {total_claimed:.2f}")
            col_tot2.success(f"Total AI Verified Approved: ₹ {total_approved:.2f}")
            
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Clean Audit Report (CSV)",
                data=csv,
                file_name=f"TIPL_Clean_Report_{designation.replace(' ', '_')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("⚠️ No records found under 'Expenses Detail' section.")
else:
    st.info("ℹ️ Upload the PDF to see the clean date-wise audit summary.")
