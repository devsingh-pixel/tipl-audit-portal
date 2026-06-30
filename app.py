import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Robust Text-Table Parser)")

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

# ---------- PDF STRUCTURAL PROCESSING ENGINE ----------
def extract_robust_expenses(file):
    raw_text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                raw_text += page_text + "\n"
                
    expenses_ledger = []
    
    # Isolate the segment after "Expenses Detail" to eliminate JV table completely
    if "expenses detail" in raw_text.lower():
        target_chunk = raw_text.lower().split("expenses detail")[1]
        # Ignore the footer metrics
        if "grand total" in target_chunk:
            target_chunk = target_chunk.split("grand total")[0]
    else:
        target_chunk = raw_text.lower()

    lines = target_chunk.split("\n")
    current_date = "In Travelling"
    
    categories = {
        "boarding": "Boarding",
        "lodging": "Lodging",
        "conveyance": "Conveyance",
        "travel ticket": "Travel ticket",
        "lodging relative": "Lodging relative"
    }

    for line in lines:
        line_clean = line.strip()
        if not line_clean or any(x in line_clean for x in ["grand total", "account code", "sn", "particulars"]):
            continue
            
        # Contextual Date Locking
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
        if date_match:
            current_date = date_match.group(1)
            
        detected_cat = None
        for k, v in categories.items():
            if k in line_clean:
                detected_cat = v
                break
                
        if detected_cat:
            # Extract currency numbers safely (ignoring small codes or distance matrices)
            amounts = re.findall(r'\b\d+(?:\.\d+)?\b', line_clean)
            valid_amounts = [float(a) for a in amounts if float(a) > 50 and not re.match(r'^20\d{2}$', a)]
            
            if valid_amounts:
                # The terminal amount field contains the true expense value
                original_amount = valid_amounts[-1]
                
                expenses_ledger.append({
                    "Date": current_date,
                    "Expense Type": detected_cat,
                    "Amount": original_amount
                })
                
    return raw_text, expenses_ledger

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

# ---------- SYSTEMIC AUDITING CORE ----------
def apply_tipl_audit(ledger, designation, days, start_time):
    cutoff_time = datetime.strptime("10:00 AM", "%I:%M %p").time()
    
    desig_upper = designation.upper()
    matched_grade = "DEFAULT"
    for grade in POLICY_LIMITS.keys():
        if grade in desig_upper:
            matched_grade = grade
            break
    limits = POLICY_LIMITS[matched_grade]

    audited_rows = []
    seen_signatures = set()
    is_first_boarding = True

    for row in ledger:
        unique_sig = (row["Date"], row["Expense Type"], row["Amount"])
        if unique_sig in seen_signatures:
            continue
        seen_signatures.add(unique_sig)

        original_amount = row["Amount"]
        approved_amount = original_amount
        status = "Passed"
        remarks = "Approved as per TIPL policy"

        if row["Expense Type"] == "Boarding":
            if start_time and start_time > cutoff_time and is_first_boarding:
                approved_amount = original_amount * 0.70
                remarks = f"30% late start cut applied (Departure: {start_time.strftime('%I:%M %p')})."
                status = "Adjusted"
                is_first_boarding = False
            if approved_amount > limits["boarding"]:
                approved_amount = limits["boarding"]
                remarks = f"Exceeded daily boarding limit of ₹{limits['boarding']}."
                status = "Adjusted"
        elif row["Expense Type"] == "Lodging" and original_amount > limits["lodging"]:
            approved_amount = limits["lodging"]
            remarks = f"Exceeded daily lodging allowance of ₹{limits['lodging']}."
            status = "Adjusted"
        elif row["Expense Type"] == "Conveyance":
            remarks = "Conveyance passed systemic validation."

        audited_rows.append({
            "Date": row["Date"],
            "Expense Type": row["Expense Type"],
            "Claimed Amount": original_amount,
            "Approved Amount": approved_amount,
            "Status": status,
            "Audit Remarks": remarks
        })

    return sorted(audited_rows, key=lambda x: x['Date']), matched_grade

# ---------- STREAMLIT INTERFACE ----------
file = st.file_uploader("Upload TE PDF File", type=["pdf"])

if file:
    raw_text, expenses_ledger = extract_robust_expenses(file)
    
    if raw_text and expenses_ledger:
        designation = find_designation(raw_text)
        days = find_days(raw_text)
        start_time = find_start_time(raw_text)
        
        st.success("🎉 Audit Summary Generated Successfully!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Departure Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        expenses, applied_grade = apply_tipl_audit(expenses_ledger, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            st.subheader(f"📊 Pure Date-Wise Audit Ledger (Applied Matrix: {applied_grade})")
            
            st.table(df[["Date", "Expense Type", "Claimed Amount", "Approved Amount", "Status", "Audit Remarks"]])
            
            total_claimed = df["Claimed Amount"].sum()
            total_approved = df["Approved Amount"].sum()
            
            col_tot1, col_tot2 = st.columns(2)
            col_tot1.info(f"Total Claimed Amount: ₹ {total_claimed:.2f}")
            col_tot2.success(f"Total AI Verified Approved: ₹ {total_approved:.2f}")
            
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Clean Official Audit Report (CSV)",
                data=csv,
                file_name=f"TIPL_Clean_Report_{designation.replace(' ', '_')}.csv",
                mime="text/csv"
            )
    else:
        st.warning("⚠️ High structural variance detected. Could not match elements.")
else:
    st.info("ℹ️ File uploaded? Click the small (x) close icon on the right side of the filename box if you wish to swap documents.")
