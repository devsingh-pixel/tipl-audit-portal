import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime

st.set_page_config(page_title="TIPL TE Auto-Audit Engine", layout="wide")
st.title("🚀 TIPL TE Fully Automated Audit Portal")

# =====================================================================
# COMPLETE TIPL POLICY DATABASE (Page 1, 2 & 3 of PDF)
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

# ---------- STEP 1: AUTOMATICALLY PARSE PDF (METADATA + PROFILE + TIER) ----------
def parse_pdf_locally(file):
    raw_text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            content = page.extract_text()
            if content:
                raw_text += content + "\n"
                
    # Intelligent Defaults (Will overwrite if explicitly found in text streams)
    start_date, start_time = "2026-05-04", "09:30:00"
    end_date, end_time = "2026-05-07", "20:00:00"
    department = "General"
    designation = "TEAM LEAD / ENGINEER / SR. ENGINEER" # Maps perfectly to Sr. Engineer
