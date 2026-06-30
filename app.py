import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Audit Portal", layout="wide")
st.title("📋 TIPL TE Audit Portal (Consolidated Summary View)")

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
            page_text = page.extract_text()
            if page_text:
                raw_text += page_text + "\n"
            
    # Focus strictly on data after Expenses Detail header block
    if "expenses detail" in raw_text.lower():
        expenses_block = raw_text.lower().split("expenses detail")[1]
        if "grand total" in expenses_block:
            expenses_block = expenses_block.split("grand total")[0]
    else:
        expenses_block = raw_text.lower()
        
    lines = expenses_block.split("\n")
    extracted_data = []
    
    categories = {
        "boarding": "Boarding",
        "lodging": "Lodging",
        "conveyance": "Conveyance",
        "travel ticket": "Travel ticket",
        "lodging relative": "Lodging relative"
    }
    
    for line in lines:
        line_clean = line.strip().lower()
        if not line_clean or any(term in line_clean for term in ["sn", "particulars", "account code"]):
            continue
            
        detected_cat = None
        for k, v in categories.items():
            if k in line_clean:
                detected_cat = v
                break
                
        if detected_cat:
            digits = re.findall(r'\b\d+(?:\.\d+)?\b', line_clean)
            valid_prices = [float(d) for d in digits if float(d) > 50 and not re.match(r'^20\d{2}$', d)]
            
            if valid_prices:
                original_amount = valid_prices[-1]
                extracted_data.append({
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

# ---------- CONSOLIDATED SUMMARY AUDIT ENGINE ----------
def run_consolidated_audit(ledger, designation, tour_days, start_time):
    cutoff_time = datetime.strptime("10:00 AM", "%I:%M %p").time()
    
    desig_upper = designation.upper()
    matched_grade = "DEFAULT"
    for grade in POLICY_LIMITS.keys():
        if grade in desig_upper:
            matched_grade = grade
            break
    limits = POLICY_LIMITS[matched_grade]

    # Step 1: Group and Sum same expense types + count days/instances
    summary_map = {}
    for row in ledger:
        exp_type = row["Expense Type"]
        if exp_type not in summary_map:
            summary_map[exp_type] = {"total_claimed": 0.0, "count_days": 0}
        summary_map[exp_type]["total_claimed"] += row["Amount"]
        summary_map[exp_type]["count_days"] += 1

    audited_summary = []

    # Step 2: Apply TIPL Matrix over the consolidated values
    for exp_type, metrics in summary_map.items():
        original_amount = metrics["total_claimed"]
        item_days = metrics["count_days"]
        approved_amount = original_amount
        status = "Passed"
        remarks = "Fully Approved as per TIPL policy"

        if exp_type == "Boarding":
            max_allowed = limits["boarding"] * item_days
            # Check late departure cut on total logic if applicable
            if start_time and start_time > cutoff_time:
                # Apply 30% cut on the first day's worth of limit split proportionally
                penalty = (limits["boarding"] * 0.30)
                approved_amount = original_amount - penalty
                remarks = f"30% late start cut applied on Day 1 base."
                status = "Adjusted"
            
            if approved_amount > max_allowed:
                approved_amount = max_allowed
                remarks = f"Capped at ceiling: ₹{limits['boarding']} × {item_days} Days = ₹{max_allowed}."
                status = "Adjusted"
                
        elif exp_type == "Lodging":
            max_allowed = limits["lodging"] * item_days
            if original_amount > max_allowed:
                approved_amount = max_allowed
                remarks = f"Capped at ceiling: ₹{limits['lodging']} × {item_days} Days = ₹{max_allowed}."
                status = "Adjusted"
                
        elif exp_type == "Conveyance":
            remarks = "Conveyance approved subject to receipt validation."

        audited_summary.append({
            "Expense Type": exp_type,
            "Days/Count": item_days,
            "Total Claimed": original_amount,
            "Total Approved": approved_amount,
            "Status": status,
            "Audit Remarks": remarks
        })

    return audited_summary, matched_grade

# ---------- STREAMLIT INTERFACE RENDERING ----------
file = st.file_uploader("Upload TE PDF File", type=["pdf"])

if file:
    raw_text, expenses_ledger = parse_pdf_unified(file)
    
    if raw_text and expenses_ledger:
        designation = find_designation(raw_text)
        days = find_days(raw_text)
        start_time = find_start_time(raw_text)
        
        st.success("🎉 PDF Parsed & Consolidated Successfully!")
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Extracted Designation", designation)
        col2.metric("Calculated Tour Days", days)
        col3.metric("Tour Departure Time", start_time.strftime("%I:%M %p") if start_time else "Not Detected")
        
        expenses, applied_grade = run_consolidated_audit(expenses_ledger, designation, days, start_time)
        
        if expenses:
            df = pd.DataFrame(expenses)
            st.subheader(f"📊 Consolidated Summary Table (Applied Matrix: {applied_grade})")
            
            # Ultra clean UI: Expense type is unique with a direct Days column
            st.table(df[["Expense Type", "Days/Count", "Total Claimed", "Total Approved", "Status", "Audit Remarks"]])
            
            total_claimed = df["Total Claimed"].sum()
            total_approved = df["Total Approved"].sum()
            
            col_tot1, col_tot2 = st.columns(2)
            col_tot1.info(f"Total Claimed Amount: ₹ {total_claimed:.2f}")
            col_tot2.success(f"Total AI Verified Approved: ₹ {total_approved:.2f}")
            
            st.markdown("---")
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Summary Audit Report (CSV)",
                data=csv,
                file_name=f"TIPL_Summary_Report_{designation.replace(' ', '_')}.csv",
                mime="text/csv"
            )
    else:
        st.warning("⚠️ Could not aggregate elements. Check the PDF text formatting.")
else:
    st.info("ℹ️ Please upload your official T&E file to view the consolidated matrix.")
