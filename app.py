import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

# 1. Page Configuration (Strictly at the absolute top of the file)
st.set_page_config(page_title="TIPL TE Auto-Audit Engine", layout="wide")
st.title("🚀 TIPL TE Fully Automated Audit Portal")

# =====================================================================
# COMPLETE TIPL POLICY DATABASE (As per PDF Pages 1, 2 & 3)
# =====================================================================
DESIGNATION_LIMITS = {
    "WORKMEN": {"Metros": {"lodging": 550, "boarding": 330}, "State Capitals": {"lodging": 500, "boarding": 305}, "Other": {"lodging": 450, "boarding": 305}},
    "TRAINEES / EXEC / JR. ENGINEER": {"Metros": {"lodging": 900, "boarding": 415}, "State Capitals": {"lodging": 800, "boarding": 390}, "Other": {"lodging": 700, "boarding": 390}},
    "SR. EXECUTIVE / ASST. ENGINEER": {"Metros": {"lodging": 950, "boarding": 475}, "State Capitals": {"lodging": 850, "boarding": 450}, "Other": {"lodging": 750, "boarding": 450}},
    "TEAM LEAD / ENGINEER / SR. ENGINEER": {"Metros": {"lodging": 1050, "boarding": 510}, "State Capitals": {"lodging": 950, "boarding": 485}, "Other": {"lodging": 850, "boarding": 485}},
    "ASST. MANAGERS / DEPUTY MANAGERS": {"Metros": {"lodging": 1200, "boarding": 550}, "State Capitals": {"lodging": 1100, "boarding": 525}, "Other": {"lodging": 1000, "boarding": 525}},
    "MANAGERS / SR. MANAGERS": {"Metros": {"lodging": 1350, "boarding": 600}, "State Capitals": {"lodging": 1250, "boarding": 575}, "Other": {"lodging": 1150, "boarding": 575}},
    "AGM": {"Metros": {"lodging": 1500, "boarding": 700}, "State Capitals": {"lodging": 1400, "boarding": 675}, "Other": {"lodging": 1300, "boarding": 675}},
    "DGM": {"Metros": {"lodging": 1600, "boarding": 725}, "State Capitals": {"lodging": 1500, "boarding": 700}, "Other": {"lodging": 1400, "boarding": 700}},
    "GM": {"Metros": {"lodging": 1700, "boarding": 850}, "State Capitals": {"lodging": 1600, "boarding": 825}, "Other": {"lodging": 1500, "boarding": 825}},
    "SR. GM & ABOVE": {"Metros": {"lodging": 1800, "boarding": 900}, "State Capitals": {"lodging": 1700, "boarding": 875}, "Other": {"lodging": 1600, "boarding": 875}}
}

# Service-DSIC Sliding Scale Matrix (Page 3 of PDF)
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
                
    # Intelligent Defaults (Will be overwritten dynamically if matched)
    start_date, start_time = "2026-05-04", "09:30:00"
    end_date, end_time = "2026-05-07", "20:00:00"
    department = "General"
    designation = "TEAM LEAD / ENGINEER / SR. ENGINEER" 
    location_type = "Other" 
    
    lines = raw_text.split("\n")
    for line in lines:
        l_lower = line.lower()
        
        # 1. Automatic Department Mapping
        if "service-dsic" in l_lower or "service dsic" in l_lower or "dsic" in l_lower:
            department = "Service-DSIC"
            
        # 2. Automatic City Tier Lookup 
        if any(m in l_lower for m in ["mumbai", "kolkata", "chennai", "delhi", "ncr", "bangalore", "hyderabad"]):
            location_type = "Metros"
        elif any(c in l_lower for c in ["jaipur", "lucknow", "patna", "bhopal", "ahmedabad", "capital"]):
            if location_type != "Metros":
                location_type = "State Capitals"
                
        # 3. Automatic Profile Designation Context Matching
        if "workman" in l_lower or "workmen" in l_lower:
            designation = "WORKMEN"
        elif any(x in l_lower for x in ["trainee", "junior executive", "jr engineer", "jr. engineer"]):
            designation = "TRAINEES / EXEC / JR. ENGINEER"
        elif "asst manager" in l_lower or "deputy manager" in l_lower:
            designation = "ASST. MANAGERS / DEPUTY MANAGERS"
        elif "manager" in l_lower or "sr. manager" in l_lower:
            designation = "MANAGERS / SR. MANAGERS"
        elif "sr. engineer" in l_lower or "engineer" in l_lower:
            designation = "TEAM LEAD / ENGINEER / SR. ENGINEER"
            
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        total_tour_days = (d2 - d1).days + 1
    except:
        total_tour_days = 4 

    # Cleaned slicing block to separate items from grand totals
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
            valid_amounts =
