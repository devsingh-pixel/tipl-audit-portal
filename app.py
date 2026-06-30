import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Strict Column Target)")

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
                
                # Check headers index to map exact columns safely
                headers = [str(cell).lower().replace('\n', ' ').strip() for cell in table[0] if cell]
                
                # Verify if this specific grid belongs to "Expenses Detail" table block
                if any("expense type" in h or "particulars" in h for h in headers):
                    
                    # Track index positions dynamically
                    date_idx, type_idx, amount_idx = -1, -1, -1
                    for idx, cell in enumerate(table[0]):
                        if not cell: continue
                        c_clean = str(cell).lower().replace('\n', ' ')
                        if "date" in c_clean: date_idx = idx
                        elif "expense type" in c_clean or "expense  type" in c_clean: type_idx = idx
                        elif "amount" in c_clean: amount_idx = idx

                    # Process content data rows sequentially 
                    for row in table[1:]:
                        if not row or len(row) <= max(date_idx, type_idx, amount_idx):
                            continue
                        
                        row_clean = [str(c).replace('\n', ' ').strip() if c else "" for c in row]
                        
                        # Eliminate structural metadata headers inside multi-page table splits
                        if any(t in " ".join(row_clean).lower() for t in ["grand total", "sn", "particulars"]):
                            continue
                            
                        # Extract details from targets
                        raw_date = row_clean[date_idx] if date_idx != -1 else ""
                        raw_type = row_clean[type_idx] if type_idx != -1 else ""
                        raw_amount = row_clean[amount_idx] if amount_idx != -1 else ""
                        
                        # Extract clean standard date logic sequence
                        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', raw_date)
                        cleaned_date = date_match.group(1) if date_match else ""
                        
                        # Match valid types
                        matched_cat = None
                        for cat in ["boarding", "lodging", "conveyance", "travel ticket", "lodging relative"]:
                            if cat in raw_type.lower():
                                matched_cat = cat.capitalize()
                                break
                                
                        # Extract the exact numeric currency from the isolated Amount cell index only
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
        # Prevent repetition overlaps
        unique_sig = (row["Date"], row["Expense Type"], row["Amount"])
        if unique_sig in seen_signatures:
            continue
        seen_signatures.add(unique_sig)

        original_amount = row["Amount"]
        approved_amount = original_amount
        status = "Passed"
        remarks = "Approved as per TIPL policy"

        # Apply specific logic rules constraints
        if row["Expense Type"] == "Boarding":
            if start_time and start_time > cutoff_time and is_first_boarding:
                approved_amount = original_amount * 0.70
                remarks = f"30% late start cut applied (Started at {start_time.strftime('%I:%M %p')})."
                status = "Adjusted"
                is_first_boarding = False
            if approved_amount > limits["boarding"]:
                approved_amount = limits["boarding"]
                remarks = f"Exceeded single day allowance limit of ₹{limits['boarding']}."
                status = "Adjusted"
        elif row["Expense Type"] == "Lodging" and original_amount > limits["lodging"]:
            approved_amount = limits["lodging"]
            remarks = f"Exceeded daily allowance ceiling limit of ₹{limits['lodging']}."
            status = "Adjusted"
        elif row["Expense Type"] == "Conveyance":
            remarks = "Conveyance approved (Receipt matching mandatory)."

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
