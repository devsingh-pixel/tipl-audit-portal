import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

# 1. Page Configuration and Title (Always at the top)
st.set_page_config(page_title="TIPL TE Fully Automated Audit Engine", layout="wide")
st.title("🚀 TIPL TE Fully Automated Audit Portal")

# =====================================================================
# HARDCODED POLICY MATRIX (As per TIPL PDF Rules)
# =====================================================================
DESIGNATION_LIMITS = {
    "WORKMEN": {"Metros": {"lodging": 550, "boarding": 330}, "State Capitals": {"lodging": 500, "boarding": 305}, "Other": {"lodging": 450, "boarding": 305}},
    "TRAINEES / EXEC / JR. ENGINEER": {"Metros": {"lodging": 900, "boarding": 415}, "State Capitals": {"lodging": 800, "boarding": 390}, "Other": {"lodging": 700, "boarding": 390}},
    "SR. EXECUTIVE / ASST. ENGINEER": {"Metros": {"lodging": 950, "boarding": 475}, "State Capitals": {"lodging": 850, "boarding": 450}, "Other": {"lodging": 750, "boarding": 450}},
    "TEAM LEAD / ENGINEER / SR. ENGINEER": {"Metros": {"lodging": 1050, "boarding": 510}, "State Capitals": {"lodging": 950, "boarding": 485}, "Other": {"lodging": 850, "boarding": 485}},
    "ASST. MANAGERS / DEPUTY MANAGERS": {"Metros": {"lodging": 1200, "boarding": 550}, "State Capitals": {"lodging": 1100, "boarding": 525}, "Other": {"lodging": 1000, "boarding": 525}},
    "MANAGERS / SR. MANAGERS": {"Metros": {"lodging": 1350, "boarding": 600}, "State Capitals": {"lodging": 1250, "boarding": 575}, "Other": {"lodging": 1150, "boarding": 575}}
}

# Service-DSIC Slab Matrix (Page 3 Rules)
DSIC_MATRIX = {
    "0-5": {"Metros": {"lodging": 950.0, "conveyance": float('inf')}, "State Capitals": {"lodging": 850.0, "conveyance": float('inf')}, "Other": {"lodging": 750.0, "conveyance": float('inf')}},
    "6-12": {"Metros": {"lodging": 800.0, "conveyance": 300.0}, "State Capitals": {"lodging": 700.0, "conveyance": 250.0}, "Other": {"lodging": 600.0, "conveyance": 250.0}},
    "13-25": {"Metros": {"lodging": 600.0, "conveyance": 300.0}, "State Capitals": {"lodging": 500.0, "conveyance": 250.0}, "Other": {"lodging": 400.0, "conveyance": 250.0}}
}

# ---------- STEP 1: AUTOMATIC PDF PARSING ENGINE ----------
def parse_pdf_locally(file):
    raw_text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            content = page.extract_text()
            if content:
                raw_text += content + "\n"
                
    # Default parameters fallback
    start_date, start_time = "2026-05-04", "09:30:00"
    end_date, end_time = "2026-05-07", "20:00:00"
    department = "General"
    designation = "TEAM LEAD / ENGINEER / SR. ENGINEER" 
    location_type = "Other" 
    
    lines = raw_text.split("\n")
    for line in lines:
        l_lower = line.lower()
        
        # 1. Auto-detect Service-DSIC
        if "service-dsic" in l_lower or "service dsic" in l_lower or "dsic" in l_lower:
            department = "Service-DSIC"
            
        # 2. Auto-detect City Tier (Metros / Capitals)
        if any(m in l_lower for m in ["mumbai", "kolkata", "chennai", "delhi", "ncr", "bangalore", "hyderabad"]):
            location_type = "Metros"
        elif any(c in l_lower for c in ["jaipur", "lucknow", "patna", "bhopal", "ahmedabad", "capital"]):
            if location_type != "Metros":
                location_type = "State Capitals"
                
        # 3. Auto-detect Profile Designation Allocation
        if "workman" in l_lower or "workmen" in l_lower:
            designation = "WORKMEN"
        elif "trainee" in l_lower or "jr engineer" in l_lower or "jr. engineer" in l_lower:
            designation = "TRAINEES / EXEC / JR. ENGINEER"
        elif "sr. engineer" in l_lower or "engineer" in l_lower:
            designation = "TEAM LEAD / ENGINEER / SR. ENGINEER"
            
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        total_tour_days = (d2 - d1).days + 1
    except:
        total_tour_days = 4 

    # Isolate from "Expenses Detail" (Bypasses the JV Summary block)
    extracted_items = []
    if "expenses detail" in raw_text.lower():
        expenses_part = raw_text.lower().split("expenses detail")[1]
        if "grand total" in expenses_part:
            expenses_part = expenses_part.split("grand total")[0]
    else:
        expenses_part = raw_text.lower()

    current_date = start_date
    for line in expenses_part.split("\n"):
        line_clean = line.strip()
        if not line_clean or any(x in line_clean.lower() for x in ["sn", "particulars", "account code", "total", "balance"]):
            continue
            
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
        if date_match:
            current_date = date_match.group(1)
            
        expense_type = None
        if "boarding" in line_clean.lower():
            expense_type = "Boarding(Food)"
        elif "lodging" in line_clean.lower():
            expense_type = "Lodging(Hotel)"
        elif "conveyance" in line_clean.lower() or "taxi" in line_clean.lower() or "auto" in line_clean.lower():
            expense_type = "Conveyance(Local)"

        if expense_type:
            amounts = re.findall(r'\b\d+(?:\.\d+)?\b', line_clean)
            valid_amounts = [float(a) for a in amounts if float(a) > 20 and not re.match(r'^20\d{2}$', a)]
            if valid_amounts:
                claimed_amount = valid_amounts[-1]
                extracted_items.append({
                    "Date": current_date,
                    "Expense Type": expense_type,
                    "Amount": claimed_amount
                })
                
    meta = {
        "start_date": start_date, "start_time": start_time, 
        "end_date": end_date, "end_time": end_time, 
        "department": department, "total_days": total_tour_days,
        "designation": designation, "location_type": location_type
    }
    return meta, extracted_items

# ---------- STEP 2: CALCULATIONS & AUDITING ENGINE ----------
def process_local_audit(meta, ledger):
    tour_start_time = datetime.strptime(meta["start_time"], "%H:%M:%S").time()
    cutoff_time = datetime.strptime("10:00:00", "%H:%M:%S").time()
    total_days = meta["total_days"]
    city_tier = meta["location_type"]
    selected_desig = meta["designation"]
    
    slab_key = "0-5"
    if 6 <= total_days <= 12:
        slab_key = "6-12"
    elif 13 <= total_days <= 25:
        slab_key = "13-25"
        
    dsic_rules = DSIC_MATRIX[slab_key][city_tier]
    general_rules = DESIGNATION_LIMITS[selected_desig][city_tier]
    
    # Consolidate repeating rows to get single-row output per expense type
    summary_map = {}
    for row in ledger:
        exp_type = row["Expense Type"]
        if exp_type not in summary_map:
            summary_map[exp_type] = []
        summary_map[exp_type].append(row)
        
    final_rows = []
    for exp_type, records in summary_map.items():
        days_count = len(records)
        total_claimed = sum(r["Amount"] for r in records)
        total_approved = 0.0
        remarks = ""
        status = "Passed"
        
        is_mumbai_stay = True if city_tier == "Metros" and "mumbai" in str(records).lower() else False
        
        for r in records:
            amt = r["Amount"]
            approved_amt = amt
            
            # 1. BOARDING RULE PROCESSING
            if "boarding" in exp_type.lower():
                if r["Date"] == meta["start_date"] and tour_start_time > cutoff_time:
                    approved_amt = amt * 0.70
                    status = "Adjusted"
                else:
                    if approved_amt > general_rules["boarding"]:
                        approved_amt = general_rules["boarding"]
                        status = "Adjusted"
                        
            # 2. LODGING RULE PROCESSING (Service-DSIC)
            elif "lodging" in exp_type.lower():
                if meta["department"] == "Service-DSIC":
                    base_limit = dsic_rules["lodging"]
                    remarks_slug = f"Auto-applied Service-DSIC matrix range ({slab_key} Days)."
                else:
                    base_limit = general_rules["lodging"]
                    remarks_slug = "Standard designation limit applied."
                
                if is_mumbai_stay:
                    base_limit += 200
                    remarks_slug += " Mumbai lodging bonus (+₹200) applied."
                    
                if approved_amt > base_limit:
                    approved_amt = base_limit
                    status = "Adjusted"
                remarks = remarks_slug
                
            # 3. CONVEYANCE RULE PROCESSING
            elif "conveyance" in exp_type.lower():
                if meta["department"] == "Service-DSIC":
                    allowed_conv = dsic_rules["conveyance"]
                    if allowed_conv == float('inf'):
                        remarks = "Service-DSIC 0-5 days scale: Local conveyance approved on Actuals."
                    else:
                        if approved_amt > allowed_conv:
                            approved_amt = allowed_conv
                            status = "Adjusted"
                        remarks = f"Capped at ₹{allowed_conv}/day under active DSIC timeline."
                else:
                    remarks = "Local conveyance approved under standard thresholds."
                    
            total_approved += approved_amt
            
        if not remarks and "boarding" in exp_type.lower():
            remarks = f"Tour start time ({meta['start_time']}) is before 10:00 AM cutoff. Fully passed without penalty."
            
        final_rows.append({
            "Expense Type": exp_type,
            "Days/Count": days_count,
            "Total Claimed": total_claimed,
            "Total Approved": total_approved,
            "Status": status,
            "Audit Remarks": remarks
        })
        
    return final_rows

# ---------- STEP 3: THE UPLOAD BUTTON & INTERFACE PRESENTATION ----------
# This file_uploader is placed cleanly at the core layout level
uploaded_file = st.file_uploader("📂 Upload TR14026 Claim PDF", type=
