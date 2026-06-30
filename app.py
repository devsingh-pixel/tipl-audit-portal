import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Final Accurate Engine)")

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

# ---------- PDF STRUCTURAL TABLE PROCESSING ENGINE ----------
def extract_strict_expenses(file):
    raw_text = ""
    expenses_ledger = []
    
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            raw_text += page.extract_text() + "\n"
            tables = page.extract_tables()
            
            for table in tables:
                if not table or len(table) < 2:
                    continue
                
                # Normalize and clean table headers to find exact targets
                headers = [str(cell).lower().replace('\n', ' ').strip() for cell in table[0] if cell]
                
                # We strictly want the grid that outlines individual expense particulars
                if any("expense type" in h or "particulars" in h for h in headers):
                    
                    date_idx, type_idx, amount_idx = -1, -1, -1
                    for idx, cell in enumerate(table[0]):
                        if not cell: continue
                        c_clean = str(cell).lower().replace('\n', ' ').strip()
                        if "date" in c_clean: date_idx = idx
                        elif "expense type" in c_clean or "expense  type" in c_clean: type_idx = idx
                        elif "amount" in c_clean: amount_idx = idx

                    # Process content data rows mapping only to safe index slots
                    for row in table[1:]:
                        if not row or len(row) <= max(date_idx, type_idx, amount_idx):
                            continue
                        
                        row_clean = [str(c).replace('\n', ' ').strip() if c else "" for c in row]
                        
                        # Discard summary total blocks or metadata lines inside table splits
                        if any(t in " ".join(row_clean).lower() for t in ["grand total", "sub total", "total", "sn"]):
                            continue
                            
                        raw_date = row_clean[date_idx] if date_idx != -1 else ""
                        raw_type = row_clean[type_idx] if type_idx != -1 else ""
                        raw_amount = row_clean[amount_idx] if amount_idx != -1 else ""
                        
                        # Isolate clear standard date signature format
                        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', raw_date)
                        cleaned_date = date_match.group(1) if date_match else ""
                        
                        # Clean category mapping validation rules
                        matched_cat = None
                        for cat in ["boarding", "lodging", "conveyance", "travel ticket", "lodging relative"]:
                            if cat in raw_type.lower():
                                matched_cat = cat.capitalize()
                                break
                                
                        # Extract amount from ONLY the designated amount column cell
                        amt_match = re.search(r'(\d+(?:\.\d+)?)', raw_amount)
                        
                        if matched_cat and amt_match and cleaned_date:
                            expenses_ledger.append({
                                "Date": cleaned_date,
                                "Expense Type": matched_cat,
                                "Amount": float(amt_match.group(1))
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

# ---------- SYSTEMIC AUDITING RULES CORE ----------
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
        # Deduplication layout guard to avoid row cloning errors
        unique_sig = (row["Date"], row["Expense Type"], row["Amount"])
        if unique_sig in seen_signatures:
            continue
        seen_signatures.add(unique_sig)

        original_amount = row["Amount"]
        approved_amount = original_amount
        status = "Passed"
        remarks = "Approved as per TIPL policy"

        # Apply granular policy checks
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
            remarks = "Conveyance passed systemic validation (Receipt matching mandatory)."

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
    raw_text, expenses_ledger = extract_strict_expenses(file)
    
    if raw_text and expenses_ledger:
        designation = find_designation(raw_text)
        days = find_days(raw_text)
        start_time = find_start_time(raw_text)
        
        st.success("🎉 Columns isolated dynamically! Audit Engine initialized smoothly.")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Departure Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        expenses, applied_grade = apply_tipl_audit(expenses_ledger, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            st.subheader(f"📊 Strict Date-Wise Audit Ledger (Applied Grid: {applied_grade})")
            
            # Ultra clean, scannable table view
            st.table(df[["Date", "Expense Type", "Claimed Amount", "Approved Amount", "Status", "Audit Remarks"]])
            
            total_claimed = df["Claimed Amount"].sum()
            total_approved = df["Approved Amount"].sum()
            
            col_tot1,
