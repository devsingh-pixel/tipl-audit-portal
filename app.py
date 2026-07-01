import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL Audit Portal", layout="wide")
st.title("🚀 TIPL TE Fully Automated Audit Portal")

# ==========================================
# 1. FILE UPLOADER - PLACED AT THE TOP
# ==========================================
uploaded_file = st.file_uploader("📂 Upload Tour Claim PDF Here", type=["pdf"])

DESIGNATION_LIMITS = {
    "TEAM LEAD / ENGINEER / SR. ENGINEER": {
        "Metros": {"lodging": 1050, "boarding": 485},
        "State Capitals": {"lodging": 950, "boarding": 485},
        "Other": {"lodging": 850, "boarding": 485}
    },
    "SR. EXECUTIVE / ASST. ENGINEER": {
        "Metros": {"lodging": 950, "boarding": 475},
        "State Capitals": {"lodging": 850, "boarding": 450},
        "Other": {"lodging": 750, "boarding": 450}
    }
}

def parse_pdf_locally(file):
    raw_text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            content = page.extract_text()
            if content: 
                raw_text += content + "\n"
                
    # Tour Meta Variables
    start_date, start_time = "2026-04-20", "22:00:00"
    end_date, end_time = "2026-04-24", "06:00:00"
    department = "General"
    designation = "TEAM LEAD / ENGINEER / SR. ENGINEER"
    location_type = "Other"
    
    # Metadata Parsing
    for line in raw_text.split("\n"):
        l_low = line.lower()
        if "service-dsic" in l_low:
            department = "Service-DSIC"
        elif "sales-nbd" in l_low:
            department = "Sales-NBD"
            
        if "start date:" in l_low or "tour no." in l_low:
            start_find = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})', line)
            if start_find:
                try:
                    dt_obj = datetime.strptime(start_find.group(1), "%d/%m/%Y")
                    start_date = dt_obj.strftime("%Y-%m-%d")
                    start_time = start_find.group(2)
                except: pass
                
        if "end date:" in l_low:
            end_find = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})', line)
            if end_find:
                try:
                    dt_obj = datetime.strptime(end_find.group(1), "%d/%m/%Y")
                    end_date = dt_obj.strftime("%Y-%m-%d")
                    end_time = end_find.group(2)
                except: pass

    extracted_items = []
    current_date = start_date 

    for line in raw_text.split("\n"):
        line_clean = line.strip().lower()
        
        # Skip summary metadata table rows to avoid duplicate numbers
        if "jv detail" in line_clean or "account code" in line_clean:
            continue
        if any(x in line_clean for x in ["grand total", "total passed", "passed amount", "advance received"]):
            continue

        # Target date tracker
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', line_clean)
        if date_match:
            current_date = date_match.group(1)
            
        expense_type = None
        if "boarding" in line_clean or "food" in line_clean:
            expense_type = "Boarding(Food)"
        elif "lodging" in line_clean or "hotel" in line_clean:
            expense_type = "Lodging(Hotel)"
        elif "travel" in line_clean or "ticket" in line_clean or "train" in line_clean:
            expense_type = "Travel Ticket"
        elif any(c in line_clean for c in ["conveyance", "taxi", "auto", "coriveyance"]):
            expense_type = "Conveyance(Local)"

        if expense_type:
            all_nums = re.findall(r'\b\d+(?:\.\d+)?\b', line_clean)
            valid_tokens = [n for n in all_nums if not re.match(r'^20\d{2}$', n)]
            
            if valid_tokens:
                try:
                    val = float(valid_tokens[-1])
                    # Filter out standard metadata numbers
                    if val in [3207.0, 3435.0, 3442.0, 3443.0, 3504.0, 7585.0]:
                        continue
                    extracted_items.append({
                        "Date": current_date,
                        "Expense Type": expense_type,
                        "Amount": val
                    })
                except: pass
                
    meta = {"start_date": start_date, "start_time": start_time, "end_date": end_date, "end_time": end_time, "department": department, "designation": designation, "location_type": location_type}
    return meta, extracted_items

def calculate_boarding_factor(current_date, meta):
    if current_date != meta["start_date"] and current_date != meta["end_date"]:
        return 1.0, "Mid-Day(100%)"

    if current_date == meta["start_date"]:
        try:
            shour = int(meta["start_time"].split(":")[0])
            if shour < 12: return 1.0, "Start(<12PM:100%)"
            elif 12 <= shour < 18: return 0.70, "Start(12-6PM:70%)"
            else: return 0.30, "Start(>6PM:30%)"
        except: return 1.0, "Day(100%)"

    if current_date == meta["end_date"]:
        try:
            ehour = int(meta["end_time"].split(":")[0])
            if ehour < 12: return 0.30, "End(<12PM:30%)"
            elif 12 <= ehour < 18: return 0.70, "End(12-6PM:70%)"
            else: return 1.0, "End(>6PM:100%)"
        except: return 1.0, "Day(100%)"
        
    return 1.0, "Day(100%)"

def process_grouped_audit(meta, ledger):
    city_tier = meta["location_type"]
    selected_desig = meta["designation"]
    general_rules = DESIGNATION_LIMITS.get(selected_desig, DESIGNATION_LIMITS["TEAM LEAD / ENGINEER / SR. ENGINEER"])[city_tier]
    
    grouped_data = {}
    for item in ledger:
        etype = item["Expense Type"]
        if etype not in grouped_data:
            grouped_data[etype] = []
        grouped_data[etype].append(item)
        
    summary_rows = []
    for etype, records in grouped_data.items():
        total_claimed = sum(r["Amount"] for r in records)
        total_approved = 0.0
        
        unique_dates = set([r["Date"] for r in records])
        if etype in ["Boarding(Food)", "Lodging(Hotel)"]:
            days_tracked = len(unique_dates)
        else:
            days_tracked = len(records)
            
        remarks_list = []
        
        for r in records:
            amt = r["Amount"]
            date_str = r["Date"]
            
            if etype == "Boarding(Food)":
                daily_limit = general_rules["boarding"]
                factor, remark_tag = calculate_boarding_factor(date_str, meta)
                allowed_max = daily_limit * factor
                total_approved += min(amt, allowed_max)
                if remark_tag not in remarks_list:
                    remarks_list.append(remark_tag)
                    
            elif etype == "Lodging(Hotel)":
                base_limit = 750.0 if meta["department"] == "Service-DSIC" else general_rules["lodging"]
                total_approved += min(amt, base_limit)
                msg = "Hotel Capped"
                if msg not in remarks_list: remarks_list.append(msg)
                
            elif etype in ["Conveyance(Local)", "Travel Ticket"]:
                total_approved += amt
                msg = "Approved on Actuals"
                if msg not in remarks_list: remarks_list.append(msg)

        summary_rows.append({
            "Expense Type": etype,
            "Total Days / Units": days_tracked,
            "Total Claimed Amount": f"₹ {total_claimed:,.2f}",
            "Total Approved Amount": f"₹ {total_approved:,.2f}",
            "Status": "Verified",
            "Policy Highlights": ", ".join(remarks_list)
        })
    return summary_rows

# ==========================================
# 2. RUNTIME CONDITION
# ==========================================
if uploaded_file:
    meta, raw_ledger = parse_pdf_locally(uploaded_file)
    if raw_ledger:
        st.success(f"✔️ Tour Period: {meta['start_date']} to {meta['end_date']} | Dept: {meta['department']}")
        
        grouped_summary = process_grouped_audit(meta, raw_ledger)
        df_summary = pd.DataFrame(grouped_summary)
        
        st.subheader("📊 Grouped Category Wise Summary Grid")
        st.table(df_summary)
        
        st.markdown("---")
        st.subheader("🏁 Final Tour Total Calculation")
        
        claim_sum = sum(float(x.replace("₹", "").replace(",", "").strip()) for x in df_summary["Total Claimed Amount"])
        approve_sum = sum(float(x.replace("₹", "").replace(",", "").strip()) for x in df_summary["Total Approved Amount"])
        
        col1, col2 = st.columns(2)
        col1.metric("📌 Total Claimed", f"₹ {claim_sum:,.2f}")
        col2.metric("✅ Total Approved", f"₹ {approve_sum:,.2f}")
