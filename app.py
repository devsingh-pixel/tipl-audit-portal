"""
TIPL Travel Expense Auto-Audit Engine
--------------------------------------
A Streamlit application that parses TIPL travel expense PDF statements,
strictly isolates the "Expense Detail" section (skipping the "JV Detail"
summary block and any structural/reference numbers), extracts only valid
transaction line items, applies TIPL travel policy caps, and produces a
clean audit summary comparing Claimed vs Approved amounts.

Run with:  streamlit run app.py
"""

import io
import re
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ----------------------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="TIPL Travel Expense Auto-Audit Engine",
    page_icon="🧾",
    layout="wide",
)


# ----------------------------------------------------------------------
# FILE UPLOADER — MUST BE AT THE VERY TOP OF THE INTERFACE
# ----------------------------------------------------------------------
st.title("🧾 TIPL Travel Expense Auto-Audit Engine")
st.caption("Upload a travel expense statement PDF to auto-parse, validate, and audit against TIPL policy caps.")

uploaded_file = st.file_uploader("Upload Expense Statement (PDF)", type=["pdf"])

st.divider()


# ----------------------------------------------------------------------
# CONSTANTS / POLICY CONFIG
# ----------------------------------------------------------------------
CATEGORY_KEYWORDS = {
    "Boarding(Food)": ["boarding", "food"],
    "Lodging(Hotel)": ["lodging", "hotel"],
    "Conveyance(Local)": ["conveyance", "taxi", "auto"],
    "Travel Ticket": ["travel", "ticket", "train", "rail"],
}

SECTION_START_KEYWORD = "expense detail"

AMOUNT_PATTERN = re.compile(r"\d+\.\d{2}")
DATE_PATTERN = re.compile(
    r"\b(\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{2,4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b"
)
TIME_PATTERN = re.compile(r"\b(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?\b")

DATE_FORMATS = ["%d-%b-%Y", "%d-%b-%y", "%d/%b/%Y", "%d/%b/%y", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"]


# ----------------------------------------------------------------------
# SIDEBAR — EDITABLE POLICY PARAMETERS
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Policy Parameters")
    employee_category = st.selectbox("Employee Category", ["Sr. Engineer (Other Category)"], index=0)
    boarding_daily_cap = st.number_input("Boarding(Food) Daily Cap (₹)", min_value=0.0, value=485.0, step=5.0)
    lodging_daily_cap = st.number_input("Lodging(Hotel) Daily Cap (₹)", min_value=0.0, value=850.0, step=10.0)
    st.markdown("---")
    st.markdown("**Check-in/out Factors**")
    st.caption("Start day check-in after 6 PM → 30% of cap")
    st.caption("End day check-out before 12 PM → 30% of cap")
    st.caption("All middle days → 100% of cap")


# ----------------------------------------------------------------------
# HELPER FUNCTIONS
# ----------------------------------------------------------------------
def classify_line(line_lower):
    """Return the policy bucket name for a line, or None if no category keyword matches."""
    for bucket, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in line_lower:
                return bucket
    return None


def extract_final_amount(line):
    """Extract ONLY the final monetary decimal token in the line (ignore distances/rates earlier in the string)."""
    matches = AMOUNT_PATTERN.findall(line)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except (ValueError, TypeError):
        return None


def extract_date_token(line):
    """Extract a date-like token from the line, if present."""
    match = DATE_PATTERN.search(line)
    if match:
        return match.group(1)
    return None


def parse_date_safe(date_token):
    """Attempt to parse a date token into a real datetime for sorting. Returns None if unparseable."""
    if not date_token:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(date_token, fmt)
        except ValueError:
            continue
    return None


def extract_hour_value(line):
    """Extract a 24-hour float hour value (e.g. 18.5 for 6:30 PM) from the line, if present."""
    match = TIME_PATTERN.search(line)
    if not match:
        return None
    try:
        hour = int(match.group(1))
        minute = int(match.group(2))
        meridian = match.group(3)
        if meridian:
            meridian = meridian.upper()
            if meridian == "PM" and hour != 12:
                hour += 12
            if meridian == "AM" and hour == 12:
                hour = 0
        return hour + (minute / 60.0)
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------------
# CORE PDF PARSING (STRICT BOUNDARY-AWARE)
# ----------------------------------------------------------------------
def parse_expense_pdf(file_bytes):
    """
    Strict parsing architecture:
      1. Stream through every page's text lines in order (Expense Detail spans page boundaries).
      2. Skip everything (including the entire JV Detail block) until the
         'Expense Detail' keyword is encountered.
      3. Only after that boundary, evaluate each line for a valid
         transaction category keyword.
      4. For each valid line, capture ONLY the final currency-formatted
         decimal token — never intermediate distances/rates/reference numbers.
    """
    collected_rows = []
    boundary_found = False
    raw_lines = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            for text_line in page_text.split("\n"):
                raw_lines.append(text_line)

    for raw_line in raw_lines:
        clean_line = raw_line.strip()
        if not clean_line:
            continue

        if not boundary_found:
            if SECTION_START_KEYWORD in clean_line.lower():
                boundary_found = True
            continue

        line_lower = clean_line.lower()
        bucket = classify_line(line_lower)
        if bucket is None:
            continue

        amount = extract_final_amount(clean_line)
        if amount is None:
            continue

        date_token = extract_date_token(clean_line)
        hour_value = extract_hour_value(clean_line)

        collected_rows.append(
            {
                "Bucket": bucket,
                "Date_Token": date_token,
                "Date_Parsed": parse_date_safe(date_token),
                "Hour": hour_value,
                "Claimed Amount": amount,
                "Raw Line": clean_line,
            }
        )

    return pd.DataFrame(collected_rows)


# ----------------------------------------------------------------------
# POLICY ENGINE
# ----------------------------------------------------------------------
def compute_boarding_approval(df_bucket, daily_cap):
    """
    Group boarding/food items by date, then apply the check-in/out
    factor logic:
      - Start day, check-in after 6 PM  -> 30% of cap
      - End day, check-out before 12 PM -> 30% of cap
      - Middle days                     -> 100% of cap
    Approved for each date = min(claimed sum for that date, cap * factor)
    """
    if df_bucket.empty:
        return df_bucket.assign(**{"Approved Amount": []}), pd.DataFrame()

    df = df_bucket.copy()
    df["Date_Key"] = df["Date_Token"].fillna("UNKNOWN")

    unique_dates = df[["Date_Key", "Date_Parsed"]].drop_duplicates()
    parseable = unique_dates.dropna(subset=["Date_Parsed"]).sort_values("Date_Parsed")

    if len(parseable) >= 1:
        ordered_keys = parseable["Date_Key"].tolist()
        unparsed_keys = [k for k in unique_dates["Date_Key"].tolist() if k not in ordered_keys]
        ordered_keys.extend(unparsed_keys)
    else:
        ordered_keys = unique_dates["Date_Key"].tolist()

    start_key = ordered_keys[0] if ordered_keys else None
    end_key = ordered_keys[-1] if ordered_keys else None

    day_summary_rows = []
    df["Approved Amount"] = 0.0

    for date_key in ordered_keys:
        day_mask = df["Date_Key"] == date_key
        day_claimed = df.loc[day_mask, "Claimed Amount"].sum()
        day_hours = df.loc[day_mask, "Hour"].dropna().tolist()

        factor = 1.0
        factor_reason = "Middle day — 100%"

        is_start = date_key == start_key
        is_end = date_key == end_key
        single_day_trip = is_start and is_end

        if single_day_trip:
            factor = 1.0
            factor_reason = "Single-day trip — 100%"
        elif is_start and any(h > 18.0 for h in day_hours):
            factor = 0.30
            factor_reason = "Start day, check-in after 6 PM — 30%"
        elif is_end and any(h < 12.0 for h in day_hours):
            factor = 0.30
            factor_reason = "End day, check-out before 12 PM — 30%"
        elif is_start or is_end:
            factor = 1.0
            factor_reason = "Boundary day, no late/early flag — 100%"

        day_limit = round(daily_cap * factor, 2)
        day_approved = round(min(day_claimed, day_limit), 2)

        df.loc[day_mask, "Approved Amount"] = day_approved / max(day_mask.sum(), 1)

        day_summary_rows.append(
            {
                "Date": date_key,
                "Claimed": round(day_claimed, 2),
                "Applicable Cap": day_limit,
                "Factor Applied": factor_reason,
                "Approved": day_approved,
            }
        )

    day_detail_df = pd.DataFrame(day_summary_rows)
    return df, day_detail_df


def compute_lodging_approval(df_bucket, daily_cap):
    """
    Cap each lodging line item (or date-grouped total) at the daily cap.
    Anything above the cap is flagged as a policy deduction.
    """
    if df_bucket.empty:
        return df_bucket.assign(**{"Approved Amount": [], "Deduction": []}), pd.DataFrame()

    df = df_bucket.copy()
    df["Date_Key"] = df["Date_Token"].fillna("UNKNOWN")

    day_summary_rows = []
    df["Approved Amount"] = 0.0
    df["Deduction"] = 0.0

    for date_key, group in df.groupby("Date_Key", sort=False):
        day_claimed = group["Claimed Amount"].sum()
        day_approved = round(min(day_claimed, daily_cap), 2)
        day_deduction = round(max(day_claimed - daily_cap, 0.0), 2)

        mask = df["Date_Key"] == date_key
        count = mask.sum()
        df.loc[mask, "Approved Amount"] = day_approved / max(count, 1)
        df.loc[mask, "Deduction"] = day_deduction / max(count, 1)

        day_summary_rows.append(
            {
                "Date": date_key,
                "Claimed": round(day_claimed, 2),
                "Daily Cap": daily_cap,
                "Approved": day_approved,
                "Policy Deduction": day_deduction,
                "Flag": "⚠️ Over Cap" if day_deduction > 0 else "✅ Within Cap",
            }
        )

    day_detail_df = pd.DataFrame(day_summary_rows)
    return df, day_detail_df


def compute_actuals_approval(df_bucket):
    """Conveyance and Travel Ticket are approved on actuals — no cap logic."""
    if df_bucket.empty:
        return df_bucket.assign(**{"Approved Amount": []})
    df = df_bucket.copy()
    df["Approved Amount"] = df["Claimed Amount"]
    return df


def count_units(df_bucket, is_dated_bucket):
    """Distinct dates for Boarding/Lodging; row count for Conveyance/Ticket."""
    if df_bucket.empty:
        return 0
    if is_dated_bucket:
        dated = df_bucket["Date_Token"].fillna("UNKNOWN")
        return dated.nunique()
    return len(df_bucket)


# ----------------------------------------------------------------------
# MAIN APPLICATION FLOW
# ----------------------------------------------------------------------
if uploaded_file is None:
    st.info("👆 Upload a TIPL travel expense PDF above to begin the auto-audit.")
    st.stop()

if pdfplumber is None:
    st.error("The 'pdfplumber' package is required. Install it with: pip install pdfplumber")
    st.stop()

try:
    file_bytes = uploaded_file.read()
    parsed_df = parse_expense_pdf(file_bytes)
except Exception as exc:
    st.error("Could not parse the uploaded PDF. Please confirm it is a valid TIPL expense statement.")
    st.exception(exc)
    st.stop()

if parsed_df.empty:
    st.warning(
        "No valid line items were found under the 'Expense Detail' section. "
        "Please verify the PDF contains a section explicitly titled 'Expense Detail' "
        "with recognizable category keywords (boarding, food, lodging, hotel, travel, "
        "ticket, train, rail, conveyance, taxi, auto)."
    )
    st.stop()

st.success(f"Parsed {len(parsed_df)} valid transaction line item(s) from the 'Expense Detail' section.")

with st.expander("🔍 View Raw Extracted Line Items (debug / traceability)"):
    st.dataframe(
        parsed_df[["Bucket", "Date_Token", "Hour", "Claimed Amount", "Raw Line"]].rename(
            columns={"Date_Token": "Date", "Hour": "Detected Hour"}
        ),
        use_container_width=True,
    )

st.divider()

# ---------------------- Split into buckets ----------------------
df_boarding = parsed_df[parsed_df["Bucket"] == "Boarding(Food)"].copy()
df_lodging = parsed_df[parsed_df["Bucket"] == "Lodging(Hotel)"].copy()
df_conveyance = parsed_df[parsed_df["Bucket"] == "Conveyance(Local)"].copy()
df_ticket = parsed_df[parsed_df["Bucket"] == "Travel Ticket"].copy()

# ---------------------- Apply policy engine ----------------------
boarding_detail, boarding_day_summary = compute_boarding_approval(df_boarding, boarding_daily_cap)
lodging_detail, lodging_day_summary = compute_lodging_approval(df_lodging, lodging_daily_cap)
conveyance_detail = compute_actuals_approval(df_conveyance)
ticket_detail = compute_actuals_approval(df_ticket)

# ---------------------- Build summary table ----------------------
summary_rows = []

summary_rows.append(
    {
        "Expense Type": "Boarding(Food)",
        "Total Days / Units": count_units(df_boarding, is_dated_bucket=True),
        "Total Claimed Amount (₹)": round(boarding_detail["Claimed Amount"].sum(), 2) if not boarding_detail.empty else 0.0,
        "Total Approved Amount (₹)": round(boarding_detail["Approved Amount"].sum(), 2) if not boarding_detail.empty else 0.0,
    }
)
summary_rows.append(
    {
        "Expense Type": "Lodging(Hotel)",
        "Total Days / Units": count_units(df_lodging, is_dated_bucket=True),
        "Total Claimed Amount (₹)": round(lodging_detail["Claimed Amount"].sum(), 2) if not lodging_detail.empty else 0.0,
        "Total Approved Amount (₹)": round(lodging_detail["Approved Amount"].sum(), 2) if not lodging_detail.empty else 0.0,
    }
)
summary_rows.append(
    {
        "Expense Type": "Conveyance(Local)",
        "Total Days / Units": count_units(df_conveyance, is_dated_bucket=False),
        "Total Claimed Amount (₹)": round(conveyance_detail["Claimed Amount"].sum(), 2) if not conveyance_detail.empty else 0.0,
        "Total Approved Amount (₹)": round(conveyance_detail["Approved Amount"].sum(), 2) if not conveyance_detail.empty else 0.0,
    }
)
summary_rows.append(
    {
        "Expense Type": "Travel Ticket",
        "Total Days / Units": count_units(df_ticket, is_dated_bucket=False),
        "Total Claimed Amount (₹)": round(ticket_detail["Claimed Amount"].sum(), 2) if not ticket_detail.empty else 0.0,
        "Total Approved Amount (₹)": round(ticket_detail["Approved Amount"].sum(), 2) if not ticket_detail.empty else 0.0,
    }
)

summary_df = pd.DataFrame(summary_rows)

st.subheader("📊 Audit Summary by Expense Type")
st.table(summary_df.style.format({"Total Claimed Amount (₹)": "{:.2f}", "Total Approved Amount (₹)": "{:.2f}"}))

# ---------------------- Detailed breakdowns ----------------------
st.subheader("📁 Detailed Policy Breakdown")

col_a, col_b = st.columns(2)

with col_a:
    st.markdown("**Boarding(Food) — Day-wise Factor Application**")
    if not boarding_day_summary.empty:
        st.dataframe(boarding_day_summary, use_container_width=True, hide_index=True)
    else:
        st.caption("No boarding/food line items found.")

    st.markdown("**Conveyance(Local) — Actuals**")
    if not conveyance_detail.empty:
        st.dataframe(
            conveyance_detail[["Date_Token", "Claimed Amount", "Approved Amount", "Raw Line"]].rename(
                columns={"Date_Token": "Date"}
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No conveyance line items found.")

with col_b:
    st.markdown("**Lodging(Hotel) — Day-wise Cap Application**")
    if not lodging_day_summary.empty:
        st.dataframe(lodging_day_summary, use_container_width=True, hide_index=True)
    else:
        st.caption("No lodging/hotel line items found.")

    st.markdown("**Travel Ticket — Actuals**")
    if not ticket_detail.empty:
        st.dataframe(
            ticket_detail[["Date_Token", "Claimed Amount", "Approved Amount", "Raw Line"]].rename(
                columns={"Date_Token": "Date"}
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No travel ticket line items found.")

st.divider()

# ---------------------- Grand totals ----------------------
grand_claimed = round(summary_df["Total Claimed Amount (₹)"].sum(), 2)
grand_approved = round(summary_df["Total Approved Amount (₹)"].sum(), 2)
grand_delta = round(grand_approved - grand_claimed, 2)

st.subheader("🧮 Grand Total — Claimed vs Approved")

metric_col1, metric_col2, metric_col3 = st.columns(3)
metric_col1.metric("Grand Total Claimed (₹)", f"{grand_claimed:,.2f}")
metric_col2.metric("Grand Total Approved (₹)", f"{grand_approved:,.2f}", delta=f"{grand_delta:,.2f}")
metric_col3.metric(
    "Policy Deduction (₹)",
    f"{round(grand_claimed - grand_approved, 2):,.2f}",
    delta=f"-{round(grand_claimed - grand_approved, 2):,.2f}" if grand_claimed > grand_approved else "0.00",
)

st.caption(f"Employee Category: {employee_category} | Boarding Cap: ₹{boarding_daily_cap}/day | Lodging Cap: ₹{lodging_daily_cap}/day")
