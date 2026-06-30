import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Smart Aggregator)")

# =====================================================================
# TIPL COMPANY POLICY CONFIGURATION MATRIX
# =====================================================================
POLICY_LIMITS = {
    "MANAGEMENT": {"lodging": 6000.0, "boarding": 1500.0, "travel_ticket": 10000.0, "lodging_relative": 1000.0},
    "GRADE A": {"lodging": 4500.0, "boarding": 1000.0, "travel_ticket": 7000.0, "lodging_relative": 800.0},
    "GRADE B": {"lodging": 3500.0, "boarding": 800.0, "travel_ticket": 5000.0, "lodging_relative": 600.0},
    "GRADE C": {"lodging": 2500.0, "boarding": 600.0, "travel_ticket": 3000.0, "lodging_relative": 500.0},
    "ENGINEER": {"lodging": 3500.0, "boarding": 800.0, "travel_ticket": 5000.0, "lodging_relative": 600.0}, # Added for Sr. Engineer context
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

# ---------- SMART FIX FOR DAYS & DESIGNATION ----------
def find_days(text):
    # Flexible scan for "Days 4" or "Days: 4"
    match = re.search(r'Days\s*[:\-]?\s*(\d+)', text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1 

def find_designation(text):
    match = re.search(r'Designation\s*[:\-]?\s*(.*)', text, re.IGNORECASE)
    if match:
        # Clean up unwanted words caught in the same line
        clean_desig = re.sub(r'Days.*', '', match.group(1), flags=re.IGNORECASE).strip()
        return clean_desig
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

# ---------- AGGREGATED AUDIT ENGINE ----------
def process_and_audit_expenses(text, designation, days, start_time):
    cutoff_time = datetime.strptime("10:00 AM", "%I:%M %p").time()
    
    # Dynamic Grade Logic mapping
    desig_upper = designation.upper()
    matched_grade = "DEFAULT"
    for grade in POLICY_LIMITS.keys():
        if grade in desig_upper:
            matched_grade = grade
            break
            
    limits = POLICY_LIMITS[matched_grade]
    
    target_mappings = {
        "boarding": "Boarding",
        "lodging": "Lodging",
        "conveyance": "Conveyance",
        "travel ticket": "Travel ticket",
        "lodging relative": "Lodging relative"
    }
    
    # Store raw sums to avoid duplicate line prints
    raw_totals = {v: 0.0 for v in target_mappings.values()}
    
    for line in text.split('\n'):
        line_clean = line.strip()
        for key, display_name in target_mappings.items():
            if re.search(r'\b' + re.escape(key) + r'\b', line_clean.lower()):
                amounts = re.findall(r'\d+(?:\.\d+)?', line_clean)
                if amounts:
                    raw_totals[display_name] += float(amounts[-1])
                    break
                    
    # Process aggregated calculations
    data = []
    for expense_head, original_amount in raw_totals.items():
        if original_amount == 0.0:
            continue # Clean UI: Skip showing 0 value headers
            
        approved_amount = original_amount
        remarks = "Fully Approved as per TIPL policy"
        status = "Passed"
        
        if expense_head == "Boarding":
            max_allowed = limits["boarding"] * days
            if start_time and start_time > cutoff_time:
                approved_amount = original_amount * 0.70
                remarks = f"30% late start cut applied."
                status = "Adjusted"
            if approved_amount > max_allowed:
                approved_amount = max_allowed
                remarks = f"Capped at max policy limit (₹{limits['boarding']} * {days} days = ₹{max_allowed})."
                status = "Adjusted"
                
        elif expense_head == "Lodging":
            max_allowed = limits["lodging"] * days
            if original_amount > max_allowed:
                approved_amount = max_allowed
                remarks = f"Capped at max limit (₹{limits['lodging']} * {days} days = ₹{max_allowed})."
                status = "Adjusted"
                
        elif expense_head == "Lodging relative":
            max_allowed = limits["lodging_relative"] * days
            if original_amount > max_allowed:
                approved_amount = max_allowed
                remarks = f"Capped at max relative limit (₹{limits['lodging_relative']} * {days} days)."
                status = "Adjusted"
                
        elif expense_head == "Travel ticket":
            max_allowed = limits["travel_ticket"]
            if original_amount > max_allowed:
                approved_amount = max_allowed
                remarks = f"Ticket price capped at single tour limit ₹{max_allowed}."
                status = "Adjusted"
                
        elif expense_head == "Conveyance":
            remarks = "Conveyance approved subject to receipt check."
            
        data.append({
            "Expense Type": expense_head,
            "Tour Days": days if expense_head in ["Boarding", "Lodging", "Lodging relative"] else "-",
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
        
        st.success("🎉 PDF Successfully Uploaded & Aggregated!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Start Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        expenses, applied_grade = process_and_audit_expenses(text, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            st.subheader(f"📊 TIPL Aggregated Policy Clean Summary (Applied Grid: {applied_grade})")
            
            # Rendering clean UI table
            st.table(df[["Expense Type", "Tour Days", "Claimed Amount", "Approved Amount", "Status", "Audit Remarks"]])
            
            total_claimed = df["Claimed Amount"].sum()
            total_approved = df["Approved Amount"].sum()
            
            col_tot1, col_tot2 = st.columns(2)
            col_tot1.info(f"Total Claimed: ₹ {total_claimed:.2f}")
            col_tot2.success(f"Total Approved: ₹ {total_approved:.2f}")
            
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Aggregated Audit Report (CSV)",
                data=csv,
                file_name=f"TIPL_Aggregated_Report_{designation.replace(' ', '_')}.csv",
                mime="text/csv"
            )
        else:
            st.warning("⚠️ No valid matches found.")
else:
    st.info("ℹ️ Please upload your official T&E file to initiate live policy mapping.")
