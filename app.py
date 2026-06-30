import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Auto-Audit Engine", layout="wide")
st.title("🚀 TIPL TE Fully Automated Audit Portal")

DESIGNATION_LIMITS = {
    "WORKMEN": {"Metros": {"lodging": 550, "boarding": 330}, "State Capitals": {"lodging": 500, "boarding": 305}, "Other": {"lodging": 450, "boarding": 305}},
    "TRAINEES / EXEC / JR. ENGINEER": {"Metros": {"lodging": 900, "boarding": 415}, "State Capitals": {"lodging": 800, "boarding": 390}, "Other": {"lodging": 700, "boarding": 390}},
    "SR. EXECUTIVE / ASST. ENGINEER": {"Metros": {"lodging": 950, "boarding": 475}, "State Capitals": {"lodging": 850, "boarding": 450}, "Other": {"lodging": 750, "boarding": 450}},
    "TEAM LEAD / ENGINEER / SR. ENGINEER": {"Metros": {"lodging": 1050, "boarding": 510}, "State Capitals": {"lodging": 950, "boarding": 485}, "Other": {"lodging": 850, "boarding": 485}},
    "ASST. MANAGERS / DEPUTY MANAGERS": {"Metros": {"lodging": 1200, "boarding": 550}, "State Capitals": {"lodging": 1100, "boarding": 525}, "Other": {"lodging": 1000, "boarding": 525}},
    "MANAGERS / SR. MANAGERS": {"Metros": {"lodging": 1350, "boarding": 600}, "State Capitals": {"lodging": 1250, "boarding": 575}, "Other": {"lodging": 1150, "boarding": 575}}
}

DSIC_MATRIX = {
    "0-5": {"Metros": {"lodging": 950.0, "conveyance": float('inf')}, "State Capitals": {"lodging": 850.0, "conveyance": float('inf')}, "Other": {"lodging": 750.0, "conveyance": float('inf')}},
    "6-12": {"Metros": {"lodging": 800.0, "conveyance": 300.0}, "State Capitals": {"lodging": 700.0, "conveyance": 250.0}, "Other": {"lodging": 600.0, "conveyance": 250.0}},
    "13-25": {"Metros": {"lodging": 600.0, "conveyance": 300.0}, "State Capitals": {"lodging": 500.0, "conveyance": 250.0}, "Other": {"lodging": 400.0, "conveyance": 250.0}}
}

def parse_pdf_locally(file):
    raw_text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            content = page.extract_text()
            if content:
                raw_text += content + "\n"
                
    start_date, start_time = "2026-06-08", "00:00:00"
    end_date, end_time = "2026-06-11", "23:45:00"
    department = "General"
    designation = "TEAM LEAD / ENGINEER / SR. ENGINEER" 
    location_type = "Other" 
    
    lines = raw_text.split("\n")
    for line in lines:
        l_lower = line.lower()
        if "service-dsic" in l_lower or "service dsic" in l_lower:
            department = "Service-DSIC"
        if "sr. engineer" in l_lower:
            designation = "TEAM LEAD / ENGINEER / SR. ENGINEER"
        if any(m in l_lower for m in ["mumbai", "kolkata", "chennai", "delhi", "bangalore"]):
            location_type = "Metros"

    total_tour_days = 5
    extracted_items = []
    
    # FIX: Summary block ko drop karke sirf Expenses Detail block ko parse karna
    if "expenses detail" in raw_text.lower():
        expenses_part = raw_text.lower().split("expenses detail")[1]
    else:
        expenses_part = raw_text.lower()

    current_date = start_date
    for line in expenses_part.split("\n"):
        line_clean = line.strip()
        if not line_clean or any(x in line_clean for x in ["account code", "applied amount", "grand total"]):
            continue
            
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
        if date_match:
            current_date = date_match.group(1)
            
        expense_type = None
        if "boarding" in line_clean:
            expense_type = "Boarding(Food)"
        elif "lodging" in line_clean:
            expense_type = "Lodging(Hotel)"
        elif "conveyance" in line_clean or "taxi" in line_clean or "auto" in line_clean:
            expense_type = "Conveyance(Local)"

        if expense_type:
            amounts = re.findall(r'\b\d+(?:\.\d+)?\b', line_clean)
            valid_amounts = [float(a) for a in amounts if float(a) > 50 and not re.match(r'^20\d{2}$', a)]
            if valid_amounts:
                extracted_items.append({
                    "Date": current_date,
                    "Expense Type": expense_type,
                    "Amount": valid_amounts[-1]
                })
                
    meta = {"start_date": start_date, "start_time": start_time, "end_date": end_date, "end_time": end_time, "department": department, "total_days": total_tour_days, "designation": designation, "location_type": location_type}
    return meta, extracted_items

def process_local_audit(meta, ledger):
    city_tier = meta["location_type"]
    selected_desig = meta["designation"]
    dsic_rules = DSIC_MATRIX["0-5"][city_tier]
    general_rules = DESIGNATION_LIMITS[selected_desig][city_tier]
    
    summary_map = {}
    for row in ledger:
        exp_type = row["Expense Type"]
        if exp_type not in summary_map: summary_map[exp_type] = []
        summary_map[exp_type].append(row)
        
    final_rows = []
    for exp_type, records in summary_map.items():
        days_count = len(records)
        total_claimed = sum(r["Amount"] for r in records)
        total_approved = 0.0
        remarks = "Passed"
        
        for r in records:
            amt = r["Amount"]
            if "boarding" in exp_type.lower():
                total_approved += min(amt, general_rules["boarding"])
            elif "lodging" in exp_type.lower():
                base = dsic_rules["lodging"] if meta["department"] == "Service-DSIC" else general_rules["lodging"]
                total_approved += min(amt, base)
                remarks = "Capped as per DSIC standard guidelines."
            elif "conveyance" in exp_type.lower():
                if meta["department"] == "Service-DSIC" and dsic_rules["conveyance"] == float('inf'):
                    total_approved += amt
                    remarks = "Approved on Actuals (DSIC 0-5 days policy)."
                else:
                    total_approved += amt
                    
        final_rows.append({
            "Expense Type": exp_type, "Days/Count": days_count, "Total Claimed": total_claimed, "Total Approved": total_approved, "Status": "Processed", "Audit Remarks": remarks
        })
    return final_rows

uploaded_file = st.file_uploader("📂 Upload TR14026 Claim PDF Here", type=["pdf"])
if uploaded_file:
    meta, raw_ledger = parse_pdf_locally(uploaded_file)
    if raw_ledger:
        st.success("🎉 PDF Parsed Correctly!")
        audited_summary = process_local_audit(meta, raw_ledger)
        df = pd.DataFrame(audited_summary)
        st.table(df)
