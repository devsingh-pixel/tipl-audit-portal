"""
TIPL Travel Expense Auto-Audit Engine
--------------------------------------
Upload a TIPL Tour Expense (TR) PDF and this app will:
  1. Read the tour header (Employee, Designation, Tour Start/End date-time, Days).
  2. Strictly parse ONLY the "Expenses Detail" line-item table (never the JV Detail
     summary block), using PDF table structure so distances/rates/reference numbers
     are never mistaken for claim amounts.
  3. Map the employee's Designation to the correct TIPL TE Rules (w.e.f. 1-Apr-2025)
     slab, apply the Lodging/Boarding daily caps for the selected Place Category.
  4. Validate every line item's date against the tour's Start/End date boundary.
  5. Apply Boarding check-in/out day factors and Lodging night-count checks.
  6. Reconcile the computed totals against the PDF's own JV Detail summary.
  7. Present an easy-to-scan audit summary with a plain-language verdict.

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
st.set_page_config(page_title="TIPL Travel Expense Auto-Audit Engine", page_icon="🧾", layout="wide")

st.title("🧾 TIPL Travel Expense Auto-Audit Engine")
st.caption("Upload a Tour Expense (TR) PDF. TE Rules w.e.f. 1-Apr-2025 are built in — no need to upload the policy document each time.")


# ----------------------------------------------------------------------
# FILE UPLOADER — VERY TOP OF THE INTERFACE
# ----------------------------------------------------------------------
uploaded_file = st.file_uploader("Upload Tour Expense (TR) PDF", type=["pdf"])

st.divider()


# ----------------------------------------------------------------------
# HARD-CODED POLICY TABLE — TIPL TE Rules w.e.f. 1st April 2025
# ----------------------------------------------------------------------
# caps = {"Metro": (lodging, boarding), "State Capital": (lodging, boarding), "Other": (lodging, boarding)}
SLAB_TABLE = [
    {"category": 1, "name": "Workmen", "keywords": ["workmen", "workman"],
     "caps": {"Metro": (550, 330), "State Capital": (500, 305), "Other": (450, 305)}},
    {"category": 2, "name": "Trainees / Jr. Executive / Executive / Jr. Tech. Asst. / Tech. Asst. / Jr. Engineer",
     "keywords": ["trainee", "junior executive", "jr. tech. assistant", "jr tech assistant",
                  "tech. assistant", "tech assistant", "jr engineer", "jr. engineer", "junior engineer"],
     "caps": {"Metro": (900, 415), "State Capital": (800, 390), "Other": (700, 390)}},
    {"category": 3, "name": "Sr. Executive / Asst. Team Lead / Asst. Engineer",
     "keywords": ["sr. executive", "senior executive", "asst. team lead", "assistant team lead",
                  "asstt. team lead", "asst. engineer", "assistant engineer", "asstt. engineer"],
     "caps": {"Metro": (950, 475), "State Capital": (850, 450), "Other": (750, 450)}},
    {"category": 4, "name": "Team Lead / Sr. Team Lead / Engineer / Sr. Engineer",
     "keywords": ["sr. team lead", "senior team lead", "team lead", "sr. engineer",
                  "senior engineer", "engineer"],
     "caps": {"Metro": (1050, 510), "State Capital": (950, 485), "Other": (850, 485)}},
    {"category": 5, "name": "Asst. Managers / Deputy Managers",
     "keywords": ["asst. manager", "assistant manager", "asstt. manager", "deputy manager"],
     "caps": {"Metro": (1200, 550), "State Capital": (1100, 525), "Other": (1000, 525)}},
    {"category": 6, "name": "Managers / Sr. Managers",
     "keywords": ["sr. manager", "senior manager", "manager"],
     "caps": {"Metro": (1350, 600), "State Capital": (1250, 575), "Other": (1150, 575)}},
    {"category": 7, "name": "AGM", "keywords": ["agm", "assistant general manager"],
     "caps": {"Metro": (1500, 700), "State Capital": (1400, 675), "Other": (1300, 675)}},
    {"category": 8, "name": "DGM", "keywords": ["dgm", "deputy general manager"],
     "caps": {"Metro": (1600, 725), "State Capital": (1500, 700), "Other": (1400, 700)}},
    {"category": 9, "name": "GM", "keywords": ["gm", "general manager"],
     "caps": {"Metro": (1700, 850), "State Capital": (1600, 825), "Other": (1500, 825)}},
    {"category": 10, "name": "Sr. GM & above", "keywords": ["sr. gm", "senior general manager"],
     "caps": {"Metro": (1800, 900), "State Capital": (1700, 875), "Other": (1600, 875)}},
    {"category": 11, "name": "Directors", "keywords": ["director"],
     "caps": {"Metro": ("Actuals", "Actuals"), "State Capital": ("Actuals", "Actuals"), "Other": ("Actuals", "Actuals")}},
]

METRO_CITIES = ["Mumbai", "Kolkata", "Chennai", "Delhi", "NCR", "Bangalore", "Bengaluru", "Hyderabad"]

STATE_CAPITALS = [
    "Jaipur", "Lucknow", "Bhopal", "Patna", "Bhubaneswar", "Raipur", "Ranchi",
    "Dehradun", "Shimla", "Chandigarh", "Gandhinagar", "Panaji", "Panjim",
    "Thiruvananthapuram", "Trivandrum", "Amaravati", "Imphal", "Shillong",
    "Aizawl", "Kohima", "Itanagar", "Gangtok", "Jammu", "Srinagar",
    "Bengaluru", "Bangalore", "Guwahati", "Dispur", "Puducherry",
]

CATEGORY_KEYWORDS = {
    "Boarding(Food)": ["boarding", "food"],
    "Lodging(Hotel)": ["lodging", "hotel"],
    "Conveyance(Local)": ["conveyance", "taxi", "auto"],
    "Travel Ticket": ["travel ticket", "ticket", "train", "rail"],
}

AMOUNT_PATTERN = re.compile(r"\d+\.\d{2}")
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
HEADER_DATE_FMT = "%d/%m/%Y %H:%M:%S"

# ----------------------------------------------------------------------
# DSIC ENGINEERS — Revised Lodging & Conveyance (TE Rules Note 3, applicable
# from 01-Jan-2023). This REPLACES the general Metro/State-Capital/Other
# Lodging & Conveyance caps for employees on DSIC tours; Boarding is NOT
# revised by this note and continues to use the general designation table.
# Each day-bracket lists 3 tiers (highest to lowest); the policy text does
# not explicitly label which designation maps to which tier, so this app
# maps them onto the same seniority ordering used by the general table:
#   Tier 0 (highest) -> Category 4 and above (Team Lead / Engineer and up)
#   Tier 1 (middle)   -> Category 3 (Sr. Executive / Asst. Team Lead / Asst. Engineer)
#   Tier 2 (lowest)   -> Category 1-2 (Workmen / Trainee / Jr. roles)
# This mapping is a reasonable assumption, not stated verbatim in the policy
# text - it is shown in the UI so it can be verified or overridden.
DSIC_BRACKETS = [
    {"label": "0-5 Days", "min_days": 0, "max_days": 5,
     "lodging_tiers": [950, 850, 750], "conveyance_tiers": ["Actuals", "Actuals", "Actuals"]},
    {"label": "06-12 Days", "min_days": 6, "max_days": 12,
     "lodging_tiers": [800, 700, 600], "conveyance_tiers": [300, 250, 250]},
    {"label": "13-25 Days", "min_days": 13, "max_days": 25,
     "lodging_tiers": [600, 500, 400], "conveyance_tiers": [300, 250, 250]},
    {"label": "26-30 Days", "min_days": 26, "max_days": 30,
     "lodging_tiers": ["Rental <= 10000", "Rental <= 10000", "Rental <= 10000"],
     "conveyance_tiers": ["Rental <= 6000", "Rental <= 6000", "Rental <= 6000"]},
]

# When a DSIC tour's total claimed Lodging (or Conveyance) days exceed 30,
# the tiered day-brackets above are NOT used. Instead the whole claim is
# audited at a single per-day-equivalent rate derived from the Rental cap
# (Rental cap / 30 days), applied uniformly across every claimed day of the
# ENTIRE tour - e.g. 36 lodging nights -> 36 x (10000/30) = 36 x 333.33.
RENTAL_BRACKET_DAYS = 30
RENTAL_LODGING_CAP_TOTAL = 10000
RENTAL_CONVEYANCE_CAP_TOTAL = 6000
RENTAL_LODGING_PER_DAY = RENTAL_LODGING_CAP_TOTAL / RENTAL_BRACKET_DAYS
RENTAL_CONVEYANCE_PER_DAY = RENTAL_CONVEYANCE_CAP_TOTAL / RENTAL_BRACKET_DAYS


def dsic_tier_index(category_num):
    if category_num >= 4:
        return 0
    if category_num == 3:
        return 1
    return 2


def get_dsic_bracket_for_day(day_number):
    """DSIC rates step DOWN as the tour progresses. day_number is the elapsed
    day of the tour (Day 1 = tour Start Date). Any day beyond 30 continues
    under the same 26-30 Rental bracket, since the policy text does not
    define anything past day 30 - this is an assumption, flagged in the UI."""
    for bracket in DSIC_BRACKETS:
        if bracket["min_days"] <= day_number <= bracket["max_days"]:
            return bracket
    return DSIC_BRACKETS[-1]  # day 31+ -> continue the 26-30 Rental bracket


# ----------------------------------------------------------------------
# SIDEBAR — POLICY REFERENCE + OVERRIDES
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Audit Settings")
    st.caption("Place Category (Metro / State Capital / Other) is auto-detected from the tour's Place names after upload.")
    st.caption("Metros: " + ", ".join(METRO_CITIES))
    manual_place_override = st.checkbox("Manually override Place Category", value=False)
    manual_place_category = None
    if manual_place_override:
        manual_place_category = st.selectbox("Place Category for this Tour", ["Other", "State Capital", "Metro"], index=0)
    st.markdown("---")
    manual_category_override = st.checkbox("Manually select Designation Slab", value=False)
    manual_category = None
    if manual_category_override:
        manual_category = st.selectbox(
            "Designation Category",
            [f"Category {s['category']}: {s['name']}" for s in SLAB_TABLE],
        )
    st.markdown("---")
    manual_dsic_tier_override = st.checkbox("Manually override DSIC Tier (if applicable)", value=False)
    manual_dsic_tier = None
    if manual_dsic_tier_override:
        manual_dsic_tier = st.selectbox("DSIC Rate Tier", ["Tier 1 (highest)", "Tier 2 (middle)", "Tier 3 (lowest)"], index=1)
    st.markdown("---")
    with st.expander("📖 TE Rules Reference (w.e.f. 1-Apr-2025)"):
        ref_rows = []
        for s in SLAB_TABLE:
            ref_rows.append({
                "Category": s["category"], "Designation Band": s["name"],
                "Lodging (Metro/StateCap/Other)": f"{s['caps']['Metro'][0]} / {s['caps']['State Capital'][0]} / {s['caps']['Other'][0]}",
                "Boarding (Metro/StateCap/Other)": f"{s['caps']['Metro'][1]} / {s['caps']['State Capital'][1]} / {s['caps']['Other'][1]}",
            })
        st.dataframe(pd.DataFrame(ref_rows), use_container_width=True, hide_index=True)

        st.markdown("**DSIC Engineers — Revised Lodging & Conveyance (Note 3)**")
        dsic_ref_rows = []
        for b in DSIC_BRACKETS:
            dsic_ref_rows.append({
                "Tour Duration": b["label"],
                "Lodging Tiers (Rs./day)": " / ".join(str(v) for v in b["lodging_tiers"]),
                "Conveyance Tiers (Rs./day)": " / ".join(str(v) for v in b["conveyance_tiers"]),
            })
        st.dataframe(pd.DataFrame(dsic_ref_rows), use_container_width=True, hide_index=True)
        st.caption("Tiers are ordered highest→lowest; this app maps Category 4+ → Tier 1, Category 3 → Tier 2, Category 1-2 → Tier 3 (assumption, not explicitly labeled in the policy text). Boarding is unaffected by this note.")


# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def classify_line(text_lower):
    """Classify by the EARLIEST-occurring category keyword in the text.
    This matters because free-text remarks can contain a rival keyword later
    in the string (e.g. a Conveyance remark 'Hotel to BSP Plant' contains the
    word 'hotel' - but the real Expense Type keyword 'conveyance' always sits
    at the very start of the row, before any remark text, so earliest-position
    wins rather than a fixed Boarding->Lodging->Conveyance->Ticket scan order)."""
    best_pos = None
    best_bucket = None
    for bucket, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            idx = text_lower.find(kw)
            if idx != -1 and (best_pos is None or idx < best_pos):
                best_pos = idx
                best_bucket = bucket
    return best_bucket


def match_designation_slab(designation_text):
    """Longest-keyword-first, word-boundary match of designation string to a policy slab."""
    if not designation_text:
        return None
    designation_lower = designation_text.lower()
    candidates = []
    for slab in SLAB_TABLE:
        for kw in slab["keywords"]:
            candidates.append((kw, slab))
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    for kw, slab in candidates:
        if re.search(r"\b" + re.escape(kw) + r"\b", designation_lower):
            return slab
    return None


def auto_detect_place_category(place_names):
    """Check the tour's ACTUAL per-line-item place names (where the expenses
    really happened) against the Metro / State Capital reference lists.
    Deliberately does NOT use the header's 'Place Visited' text - that field
    can be a stale/generic tour-destination label that doesn't match where
    daily Lodging/Boarding/Conveyance actually occurred. Metro takes priority
    over State Capital if both appear; defaults to 'Other' if nothing matches."""
    combined_lower = " ".join([p for p in place_names if p]).lower()

    matched_metro = [city for city in METRO_CITIES if re.search(r"\b" + re.escape(city.lower()) + r"\b", combined_lower)]
    if matched_metro:
        return "Metro", matched_metro

    matched_capital = [city for city in STATE_CAPITALS if re.search(r"\b" + re.escape(city.lower()) + r"\b", combined_lower)]
    if matched_capital:
        return "State Capital", matched_capital

    return "Other", []


def is_dsic_tour(header_info):
    """DSIC rules apply ONLY to employees whose Employee Department is
    Service-DSIC (or similar). This is checked primarily from that field;
    full-text is only used as a fallback if the Department field itself
    could not be parsed from the PDF, so other designations/departments
    never get the DSIC bracket rules by accident."""
    dept = header_info.get("Employee Department")
    if dept:
        return "dsic" in dept.lower()
    full_text = (header_info.get("_full_text") or "").lower()
    return "dsic" in full_text


def parse_header_info(full_text):
    info = {}
    patterns = {
        "Tour No": r"Tour No\.\s*([A-Za-z0-9/\-]+)",
        "Employee Name": r"Employee Name:\s*([A-Za-z .]+?)\s+Employee ID",
        "Employee ID": r"Employee ID:\s*(\S+)",
        "Employee Department": r"Employee Department:\s*(\S+)",
        "Designation": r"Designation:\s*([A-Za-z.() ]+?)\s+Days",
        "Start Date Raw": r"Start Date:\s*([\d/]+\s+[\d:]+)",
        "End Date Raw": r"End Date:\s*([\d/]+\s+[\d:]+)",
        "Days": r"\bDays\s+(\d+)",
        "Advance": r"Advance received.*?:\s*([\d,]+)",
        "PDF Grand Total": r"Grand Total,\s*Rs\.:\s*([\d,]+\.\d{2})",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, full_text, re.S)
        info[key] = match.group(1).strip() if match else None

    info["Start Date"] = None
    info["End Date"] = None
    try:
        if info["Start Date Raw"]:
            info["Start Date"] = datetime.strptime(info["Start Date Raw"], HEADER_DATE_FMT)
    except ValueError:
        pass
    try:
        if info["End Date Raw"]:
            info["End Date"] = datetime.strptime(info["End Date Raw"], HEADER_DATE_FMT)
    except ValueError:
        pass

    try:
        info["Advance"] = float(info["Advance"].replace(",", "")) if info["Advance"] else None
    except (ValueError, AttributeError):
        info["Advance"] = None
    try:
        info["PDF Grand Total"] = float(info["PDF Grand Total"].replace(",", "")) if info["PDF Grand Total"] else None
    except (ValueError, AttributeError):
        info["PDF Grand Total"] = None

    return info


def parse_expense_row(row):
    """Parse one 'Expenses Detail' table row (from pdfplumber table extraction) into a claim line item."""
    cells = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
    if not cells:
        return None

    sn_candidate = cells[0].strip()
    if not sn_candidate.isdigit():
        return None

    date_val = None
    for c in cells[1:4]:
        cclean = c.replace("\n", "").replace(" ", "")
        m = re.match(r"^(\d{4}-\d{2}-\d{2})$", cclean)
        if m:
            date_val = m.group(1)
            break
    if date_val is None:
        joined_clean = "".join(c.replace("\n", "").replace(" ", "") for c in cells)
        m = DATE_PATTERN.search(joined_clean)
        if m:
            date_val = m.group(1)
    if date_val is None:
        return None

    full_text = " ".join(c.replace("\n", " ") for c in cells)
    bucket = classify_line(full_text.lower())
    if bucket is None:
        return None

    # Amount must be a STANDALONE cell that is fully a currency-decimal token
    # (e.g. "2100.00"). A plain substring search is unsafe: bill attachment
    # filenames like "..._22.11.48_1_...jpeg" also contain a \d+\.\d{2}-shaped
    # fragment ("22.11") that would otherwise be picked up as the amount.
    # Requiring the ENTIRE cell to match rules that out, since filenames
    # always carry extra letters/underscores/extensions.
    amount = None
    for c in reversed(cells):
        c_clean = c.replace("\n", "").strip()
        if AMOUNT_PATTERN.fullmatch(c_clean):
            amount = float(c_clean)
            break
    if amount is None:
        return None

    distance = None
    for c in cells:
        cs = c.strip()
        if cs.isdigit() and len(cs) <= 4 and cs != sn_candidate:
            distance = cs
            break

    place = None
    for c in cells[1:]:
        cs = c.strip()
        cclean = cs.replace("\n", "").replace(" ", "")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", cclean):
            continue
        low = cs.lower()
        if any(kw in low for kws in CATEGORY_KEYWORDS.values() for kw in kws):
            break
        if cs and not cs.isdigit():
            place = cs.replace("\n", " ").strip()
            break

    try:
        parsed_date = datetime.strptime(date_val, "%Y-%m-%d")
    except ValueError:
        parsed_date = None

    return {
        "SN": sn_candidate,
        "Date": date_val,
        "Date_Parsed": parsed_date,
        "Place": place,
        "Bucket": bucket,
        "Distance (Km)": distance,
        "Claimed Amount": amount,
        "Raw Row": full_text.strip(),
    }


def parse_jv_row(row):
    """Parse one 'JV Detail' summary table row (for reconciliation only — never mixed with claim lines)."""
    cells = [str(c).strip() for c in row if c is not None and str(c).strip() != ""]
    if len(cells) < 4:
        return None
    if not cells[0].isdigit() or not cells[1].isdigit():
        return None
    if not AMOUNT_PATTERN.fullmatch(cells[-1]) or not AMOUNT_PATTERN.fullmatch(cells[-2]):
        return None
    expense_type_raw = cells[2]
    bucket = classify_line(expense_type_raw.lower())
    if bucket is None:
        return None
    try:
        applied = float(cells[-2])
        approved = float(cells[-1])
    except ValueError:
        return None
    return {"Bucket": bucket, "Account Code": cells[1], "JV Applied": applied, "JV Approved": approved}


def parse_tr_pdf(file_bytes):
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        full_text = "\n".join((page.extract_text() or "") for page in pdf.pages)
        all_rows = []
        for page in pdf.pages:
            for table in page.extract_tables():
                all_rows.extend(table)

    header_info = parse_header_info(full_text)
    header_info["_full_text"] = full_text

    expense_rows = []
    for row in all_rows:
        parsed = parse_expense_row(row)
        if parsed:
            expense_rows.append(parsed)

    jv_rows = []
    for row in all_rows:
        parsed = parse_jv_row(row)
        if parsed:
            jv_rows.append(parsed)

    return header_info, pd.DataFrame(expense_rows), pd.DataFrame(jv_rows)


# ----------------------------------------------------------------------
# POLICY ENGINE
# ----------------------------------------------------------------------
def audit_boarding(df_bucket, daily_cap, start_dt, end_dt):
    rows = []
    if df_bucket.empty:
        return pd.DataFrame(rows)

    start_date = start_dt.date() if start_dt else None
    end_date = end_dt.date() if end_dt else None

    for date_str, group in df_bucket.groupby("Date", sort=True):
        claimed = round(group["Claimed Amount"].sum(), 2)
        try:
            this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            this_date = None

        out_of_range = False
        if start_date and end_date and this_date:
            out_of_range = this_date < start_date or this_date > end_date

        if out_of_range:
            factor, reason, approved = 0.0, "⛔ Outside tour date range — NOT approved", 0.0
        elif isinstance(daily_cap, str):
            factor, reason, approved = 1.0, "On actuals (Director slab)", claimed
        else:
            if start_date and end_date and start_date == end_date:
                factor, reason = 1.0, "Single-day trip — 100%"
            elif start_date and this_date == start_date:
                if start_dt.hour + start_dt.minute / 60.0 > 18.0:
                    factor, reason = 0.30, "Start day, check-in after 6 PM — 30%"
                else:
                    factor, reason = 1.0, "Start day, normal check-in — 100%"
            elif end_date and this_date == end_date:
                if end_dt.hour + end_dt.minute / 60.0 < 12.0:
                    factor, reason = 0.30, "End day, check-out before 12 PM — 30%"
                else:
                    factor, reason = 1.0, "End day, normal check-out — 100%"
            else:
                factor, reason = 1.0, "Middle day — 100%"
            limit = round(daily_cap * factor, 2)
            approved = round(min(claimed, limit), 2)

        rows.append({
            "Date": date_str, "Claimed (Rs.)": claimed,
            "Applicable Cap (Rs.)": "Actuals" if isinstance(daily_cap, str) else round(daily_cap * factor, 2),
            "Rule Applied": reason, "Approved (Rs.)": approved,
        })
    return pd.DataFrame(rows)


def audit_lodging(df_bucket, daily_cap, start_dt, end_dt):
    rows = []
    if df_bucket.empty:
        return pd.DataFrame(rows), 0, 0

    start_date = start_dt.date() if start_dt else None
    end_date = end_dt.date() if end_dt else None
    expected_nights = (end_date - start_date).days if (start_date and end_date) else None

    for date_str, group in df_bucket.groupby("Date", sort=True):
        claimed = round(group["Claimed Amount"].sum(), 2)
        try:
            this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            this_date = None

        out_of_range = False
        if start_date and end_date and this_date:
            out_of_range = this_date < start_date or this_date > end_date

        if out_of_range:
            approved, deduction, flag = 0.0, claimed, "⛔ Outside tour date range — NOT approved"
        elif isinstance(daily_cap, str) and daily_cap.startswith("Rental"):
            approved, deduction, flag = claimed, 0.0, f"⚠️ {daily_cap} (lump-sum for whole tour, not per day) — manual RA review recommended"
        elif isinstance(daily_cap, str):
            approved, deduction, flag = claimed, 0.0, "On actuals (Director slab)"
        else:
            approved = round(min(claimed, daily_cap), 2)
            deduction = round(max(claimed - daily_cap, 0.0), 2)
            flag = "⚠️ Over daily cap" if deduction > 0 else "✅ Within cap"

        rows.append({
            "Date": date_str, "Claimed (Rs.)": claimed,
            "Daily Cap (Rs.)": "Actuals" if isinstance(daily_cap, str) else daily_cap,
            "Approved (Rs.)": approved, "Deduction (Rs.)": deduction, "Flag": flag,
        })

    actual_nights = df_bucket["Date"].nunique()
    return pd.DataFrame(rows), actual_nights, expected_nights


def audit_lodging_dsic(df_bucket, start_dt, end_dt, tier_index):
    """DSIC Lodging.
    - If total claimed Lodging days <= 30: cap steps down per elapsed
      tour-day bracket (0-5 / 6-12 / 13-25 / 26-30), as tabulated.
    - If total claimed Lodging days > 30: the tiered brackets are NOT used.
      Instead the Rental cap (Rs. 10000 for 30 days) is converted into a
      per-day-equivalent rate (10000 / 30 = Rs. 333.33/day) and applied
      UNIFORMLY across every claimed day of the whole tour."""
    rows = []
    if df_bucket.empty or start_dt is None:
        return pd.DataFrame(rows), 0, None

    start_date = start_dt.date()
    end_date = end_dt.date() if end_dt else None
    expected_nights = (end_date - start_date).days if end_date else None
    total_lodging_days = df_bucket["Date"].nunique()

    if total_lodging_days > RENTAL_BRACKET_DAYS:
        # Flat per-day-equivalent-of-Rental-cap mode across the WHOLE claim
        per_day_cap = round(RENTAL_LODGING_PER_DAY, 2)
        for date_str, group in df_bucket.groupby("Date", sort=True):
            claimed = round(group["Claimed Amount"].sum(), 2)
            try:
                this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if end_date and (this_date < start_date or this_date > end_date):
                rows.append({"Date": date_str, "Tour Day": "-", "Bracket": "-", "Claimed (Rs.)": claimed,
                             "Cap (Rs.)": "-", "Approved (Rs.)": 0.0, "Deduction (Rs.)": claimed,
                             "Flag": "⛔ Outside tour date range — NOT approved"})
                continue
            day_number = (this_date - start_date).days + 1
            approved = round(min(claimed, per_day_cap), 2)
            deduction = round(max(claimed - per_day_cap, 0.0), 2)
            rows.append({
                "Date": date_str, "Tour Day": day_number,
                "Bracket": f">30 days total — flat Rental-equivalent rate (10000/30)",
                "Claimed (Rs.)": claimed, "Cap (Rs.)": per_day_cap, "Approved (Rs.)": approved,
                "Deduction (Rs.)": deduction, "Flag": "⚠️ Over DSIC Rental-equivalent rate" if deduction > 0 else "✅ Within cap",
            })
        return pd.DataFrame(rows), total_lodging_days, expected_nights

    # Tiered day-bracket mode (tour total <= 30 days)
    for date_str, group in df_bucket.groupby("Date", sort=True):
        claimed = round(group["Claimed Amount"].sum(), 2)
        try:
            this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if end_date and (this_date < start_date or this_date > end_date):
            rows.append({"Date": date_str, "Tour Day": "-", "Bracket": "-", "Claimed (Rs.)": claimed,
                         "Cap (Rs.)": "-", "Approved (Rs.)": 0.0, "Deduction (Rs.)": claimed,
                         "Flag": "⛔ Outside tour date range — NOT approved"})
            continue

        day_number = (this_date - start_date).days + 1
        bracket = get_dsic_bracket_for_day(day_number)
        cap = bracket["lodging_tiers"][tier_index]

        if isinstance(cap, str):
            cap = round(RENTAL_LODGING_PER_DAY, 2)  # single day within a <=30-day tour's rental bracket
            bracket_label = f"{bracket['label']} (Rental-equivalent, 10000/30)"
        else:
            bracket_label = bracket["label"]

        approved = round(min(claimed, cap), 2)
        deduction = round(max(claimed - cap, 0.0), 2)
        rows.append({
            "Date": date_str, "Tour Day": day_number, "Bracket": bracket_label,
            "Claimed (Rs.)": claimed, "Cap (Rs.)": cap, "Approved (Rs.)": approved,
            "Deduction (Rs.)": deduction, "Flag": "⚠️ Over DSIC cap" if deduction > 0 else "✅ Within cap",
        })

    return pd.DataFrame(rows), total_lodging_days, expected_nights


def audit_conveyance_dsic(df_bucket, start_dt, end_dt, tier_index):
    """DSIC Conveyance.
    - If total claimed Conveyance days <= 30: Days 0-5 on actuals, Days 6-25
      have a tiered daily cap, as tabulated.
    - If total claimed Conveyance days > 30: the tiers are NOT used. Instead
      the Rental cap (Rs. 6000 for 30 days) is converted into a per-day-
      equivalent rate (6000 / 30 = Rs. 200/day) and applied UNIFORMLY across
      every claimed day of the whole tour."""
    rows = []
    if df_bucket.empty or start_dt is None:
        return pd.DataFrame(rows)

    start_date = start_dt.date()
    end_date = end_dt.date() if end_dt else None
    total_conveyance_days = df_bucket["Date"].nunique()

    if total_conveyance_days > RENTAL_BRACKET_DAYS:
        per_day_cap = round(RENTAL_CONVEYANCE_PER_DAY, 2)
        for date_str, group in df_bucket.groupby("Date", sort=True):
            claimed = round(group["Claimed Amount"].sum(), 2)
            try:
                this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if end_date and (this_date < start_date or this_date > end_date):
                rows.append({"Date": date_str, "Tour Day": "-", "Bracket": "-", "Claimed (Rs.)": claimed,
                             "Cap (Rs.)": "-", "Approved (Rs.)": 0.0, "Deduction (Rs.)": claimed,
                             "Flag": "⛔ Outside tour date range — NOT approved"})
                continue
            day_number = (this_date - start_date).days + 1
            approved = round(min(claimed, per_day_cap), 2)
            deduction = round(max(claimed - per_day_cap, 0.0), 2)
            rows.append({
                "Date": date_str, "Tour Day": day_number,
                "Bracket": ">30 days total — flat Rental-equivalent rate (6000/30)",
                "Claimed (Rs.)": claimed, "Cap (Rs.)": per_day_cap, "Approved (Rs.)": approved,
                "Deduction (Rs.)": deduction, "Flag": "⚠️ Over DSIC Rental-equivalent rate" if deduction > 0 else "✅ Within cap",
            })
        return pd.DataFrame(rows)

    # Tiered day-bracket mode (tour total <= 30 days)
    for date_str, group in df_bucket.groupby("Date", sort=True):
        claimed = round(group["Claimed Amount"].sum(), 2)
        try:
            this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if end_date and (this_date < start_date or this_date > end_date):
            rows.append({"Date": date_str, "Tour Day": "-", "Bracket": "-", "Claimed (Rs.)": claimed,
                         "Cap (Rs.)": "-", "Approved (Rs.)": 0.0, "Deduction (Rs.)": claimed,
                         "Flag": "⛔ Outside tour date range — NOT approved"})
            continue

        day_number = (this_date - start_date).days + 1
        bracket = get_dsic_bracket_for_day(day_number)
        cap = bracket["conveyance_tiers"][tier_index]

        if isinstance(cap, str) and cap.startswith("Rental"):
            cap = round(RENTAL_CONVEYANCE_PER_DAY, 2)
            bracket_label = f"{bracket['label']} (Rental-equivalent, 6000/30)"
            approved = round(min(claimed, cap), 2)
            deduction = round(max(claimed - cap, 0.0), 2)
            rows.append({
                "Date": date_str, "Tour Day": day_number, "Bracket": bracket_label,
                "Claimed (Rs.)": claimed, "Cap (Rs.)": cap, "Approved (Rs.)": approved,
                "Deduction (Rs.)": deduction, "Flag": "⚠️ Over DSIC cap" if deduction > 0 else "✅ Within cap",
            })
            continue

        if cap == "Actuals":
            rows.append({"Date": date_str, "Tour Day": day_number, "Bracket": bracket["label"],
                         "Claimed (Rs.)": claimed, "Cap (Rs.)": "Actuals", "Approved (Rs.)": claimed,
                         "Deduction (Rs.)": 0.0, "Flag": "✅ On actuals (Day 0-5)"})
            continue

        approved = round(min(claimed, cap), 2)
        deduction = round(max(claimed - cap, 0.0), 2)
        rows.append({
            "Date": date_str, "Tour Day": day_number, "Bracket": bracket["label"],
            "Claimed (Rs.)": claimed, "Cap (Rs.)": cap, "Approved (Rs.)": approved,
            "Deduction (Rs.)": deduction, "Flag": "⚠️ Over DSIC cap" if deduction > 0 else "✅ Within cap",
        })

    return pd.DataFrame(rows)


def audit_actuals(df_bucket, start_dt, end_dt):
    if df_bucket.empty:
        return df_bucket.assign(**{"Approved Amount": []})
    df = df_bucket.copy()
    start_date = start_dt.date() if start_dt else None
    end_date = end_dt.date() if end_dt else None

    def _approve(row):
        try:
            this_date = datetime.strptime(row["Date"], "%Y-%m-%d").date()
        except ValueError:
            return row["Claimed Amount"]
        if start_date and end_date and (this_date < start_date or this_date > end_date):
            return 0.0
        return row["Claimed Amount"]

    df["Approved Amount"] = df.apply(_approve, axis=1)
    df["Flag"] = df.apply(
        lambda r: "⛔ Outside tour date range" if r["Approved Amount"] == 0 and r["Claimed Amount"] > 0 else "✅ On actuals",
        axis=1,
    )
    return df


# ----------------------------------------------------------------------
# MAIN FLOW
# ----------------------------------------------------------------------
if uploaded_file is None:
    st.info("👆 Upload a TIPL Tour Expense (TR) PDF above to run the auto-audit.")
    st.stop()

if pdfplumber is None:
    st.error("The 'pdfplumber' package is required. Install it with: pip install pdfplumber")
    st.stop()

try:
    file_bytes = uploaded_file.read()
    header_info, expense_df, jv_df = parse_tr_pdf(file_bytes)
except Exception as exc:
    st.error("Could not parse the uploaded PDF. Please confirm it is a valid TIPL TR statement.")
    st.exception(exc)
    st.stop()

if expense_df.empty:
    st.warning("No valid line items were found in the 'Expenses Detail' table of this PDF. Please check the file.")
    st.stop()

# ---------------------- Header card ----------------------
st.subheader("🗂️ Tour Information")
h1, h2, h3, h4, h5 = st.columns(5)
h1.metric("Tour No.", header_info.get("Tour No") or "—")
h2.metric("Employee", header_info.get("Employee Name") or "—")
h3.metric("Designation", header_info.get("Designation") or "—")
h4.metric("Days", header_info.get("Days") or "—")
h5.metric("Department", header_info.get("Employee Department") or "—")

start_dt = header_info.get("Start Date")
end_dt = header_info.get("End Date")
d1, d2 = st.columns(2)
d1.info(f"**Tour Start:** {start_dt.strftime('%d-%b-%Y %I:%M %p') if start_dt else 'Not detected'}")
d2.info(f"**Tour End:** {end_dt.strftime('%d-%b-%Y %I:%M %p') if end_dt else 'Not detected'}")

# ---------------------- Slab detection ----------------------
if manual_category_override and manual_category:
    cat_num = int(manual_category.split(":")[0].replace("Category", "").strip())
    slab = next(s for s in SLAB_TABLE if s["category"] == cat_num)
else:
    slab = match_designation_slab(header_info.get("Designation"))

if slab is None:
    st.error("Could not auto-match this Designation to a TE Rules slab. Please tick 'Manually select Designation Slab' in the sidebar.")
    st.stop()

# ---------------------- Place Category auto-detection ----------------------
detected_place_category, matched_place_names = auto_detect_place_category(
    expense_df["Place"].dropna().unique().tolist()
)
if manual_place_override and manual_place_category:
    place_category = manual_place_category
    st.caption(f"📍 Place Category manually set to **{place_category}** (auto-detection suggested **{detected_place_category}**).")
else:
    place_category = detected_place_category
    if matched_place_names:
        st.caption(f"📍 Place Category auto-detected as **{place_category}** (matched: {', '.join(matched_place_names)}).")
    else:
        st.caption(f"📍 Place Category auto-detected as **{place_category}** (no Metro/State Capital name found among tour places — default applied).")

lodging_cap, boarding_cap = slab["caps"][place_category]

# ---------------------- DSIC override (Note 3: Revised Lodging & Conveyance) ----------------------
dsic_active = is_dsic_tour(header_info)
dsic_tier = None

if dsic_active:
    if manual_dsic_tier_override and manual_dsic_tier:
        dsic_tier = {"Tier 1 (highest)": 0, "Tier 2 (middle)": 1, "Tier 3 (lowest)": 2}[manual_dsic_tier]
    else:
        dsic_tier = dsic_tier_index(slab["category"])

    tour_span_days = (end_dt.date() - start_dt.date()).days + 1 if (start_dt and end_dt) else None
    tier_source_note = "manually set" if manual_dsic_tier_override else f"auto-mapped from Category {slab['category']}"
    lodging_days_preview = expense_df[expense_df["Bucket"] == "Lodging(Hotel)"]["Date"].nunique()
    conveyance_days_preview = expense_df[expense_df["Bucket"] == "Conveyance(Local)"]["Date"].nunique()

    if lodging_days_preview > RENTAL_BRACKET_DAYS or conveyance_days_preview > RENTAL_BRACKET_DAYS:
        mode_note = (
            f"Lodging claimed on **{lodging_days_preview} day(s)** and Conveyance on **{conveyance_days_preview} day(s)** — "
            f"since this exceeds the tabulated 30-day range, the tiered day-brackets are **not** used. Instead a flat "
            f"per-day-equivalent rate is applied across the WHOLE claim: Lodging @ ₹{RENTAL_LODGING_PER_DAY:.2f}/day "
            f"(= 10000 ÷ 30) and Conveyance @ ₹{RENTAL_CONVEYANCE_PER_DAY:.2f}/day (= 6000 ÷ 30)."
        )
    else:
        mode_note = (
            "Rates step down as the tour progresses through the tiered day-brackets "
            f"(Day 1-5, 6-12, 13-25, then Rental from Day 26) using **Tier {dsic_tier + 1} of 3** ({tier_source_note})."
        )

    st.warning(
        f"🔧 **DSIC Engineer Tour Detected** — Department: {header_info.get('Employee Department')}. "
        f"Per TE Rules Note 3, Lodging & Conveyance are audited under the DSIC table. {mode_note} "
        f"Tour spans **{tour_span_days if tour_span_days else '—'} day(s)**. "
        f"Boarding stays on the general table (₹{boarding_cap}/day) — Note 3 does not revise Boarding."
    )

st.success(
    f"**Policy Slab Detected:** Category {slab['category']} — {slab['name']}  |  "
    f"**Place Category:** {place_category}  |  "
    f"**Lodging/Conveyance Basis:** {'DSIC day-bracket table (see warning above)' if dsic_active else ('₹' + str(lodging_cap) + '/night')}  |  "
    f"**Boarding Cap:** ₹{boarding_cap}/day"
)

st.divider()

# ---------------------- Split into buckets ----------------------
df_boarding = expense_df[expense_df["Bucket"] == "Boarding(Food)"].copy()
df_lodging = expense_df[expense_df["Bucket"] == "Lodging(Hotel)"].copy()
df_conveyance = expense_df[expense_df["Bucket"] == "Conveyance(Local)"].copy()
df_ticket = expense_df[expense_df["Bucket"] == "Travel Ticket"].copy()

# ---------------------- Run policy engine ----------------------
boarding_day_summary = audit_boarding(df_boarding, boarding_cap, start_dt, end_dt)
ticket_detail = audit_actuals(df_ticket, start_dt, end_dt)

if dsic_active:
    lodging_day_summary, lodging_actual_nights, lodging_expected_nights = audit_lodging_dsic(df_lodging, start_dt, end_dt, dsic_tier)
    conveyance_day_summary = audit_conveyance_dsic(df_conveyance, start_dt, end_dt, dsic_tier)
    conveyance_detail = audit_actuals(df_conveyance, start_dt, end_dt)  # per-row detail, always shown for traceability
else:
    lodging_day_summary, lodging_actual_nights, lodging_expected_nights = audit_lodging(df_lodging, lodging_cap, start_dt, end_dt)
    conveyance_detail = audit_actuals(df_conveyance, start_dt, end_dt)
    conveyance_day_summary = pd.DataFrame()

boarding_claimed = round(df_boarding["Claimed Amount"].sum(), 2) if not df_boarding.empty else 0.0
boarding_approved = round(boarding_day_summary["Approved (Rs.)"].sum(), 2) if not boarding_day_summary.empty else 0.0
lodging_claimed = round(df_lodging["Claimed Amount"].sum(), 2) if not df_lodging.empty else 0.0
lodging_approved = round(lodging_day_summary["Approved (Rs.)"].sum(), 2) if not lodging_day_summary.empty else 0.0
conveyance_claimed = round(conveyance_detail["Claimed Amount"].sum(), 2) if not conveyance_detail.empty else 0.0
if dsic_active and not conveyance_day_summary.empty:
    conveyance_approved = round(conveyance_day_summary["Approved (Rs.)"].sum(), 2)
else:
    conveyance_approved = round(conveyance_detail["Approved Amount"].sum(), 2) if not conveyance_detail.empty else 0.0
ticket_claimed = round(ticket_detail["Claimed Amount"].sum(), 2) if not ticket_detail.empty else 0.0
ticket_approved = round(ticket_detail["Approved Amount"].sum(), 2) if not ticket_detail.empty else 0.0

# ---------------------- Summary table ----------------------
summary_df = pd.DataFrame([
    {"Expense Type": "Boarding(Food)", "Total Days / Units": df_boarding["Date"].nunique() if not df_boarding.empty else 0,
     "Total Claimed Amount (Rs.)": boarding_claimed, "Total Approved Amount (Rs.)": boarding_approved,
     "Verdict": "✅ Compliant" if boarding_claimed == boarding_approved else "⚠️ Deduction Applied"},
    {"Expense Type": "Lodging(Hotel)", "Total Days / Units": df_lodging["Date"].nunique() if not df_lodging.empty else 0,
     "Total Claimed Amount (Rs.)": lodging_claimed, "Total Approved Amount (Rs.)": lodging_approved,
     "Verdict": "✅ Compliant" if lodging_claimed == lodging_approved else "⚠️ Deduction Applied"},
    {"Expense Type": "Conveyance(Local)", "Total Days / Units": len(df_conveyance),
     "Total Claimed Amount (Rs.)": conveyance_claimed, "Total Approved Amount (Rs.)": conveyance_approved,
     "Verdict": "✅ Compliant" if conveyance_claimed == conveyance_approved else "⚠️ Deduction Applied"},
    {"Expense Type": "Travel Ticket", "Total Days / Units": len(df_ticket),
     "Total Claimed Amount (Rs.)": ticket_claimed, "Total Approved Amount (Rs.)": ticket_approved,
     "Verdict": "✅ Compliant" if ticket_claimed == ticket_approved else "⚠️ Deduction Applied"},
])

st.subheader("📊 Audit Summary by Expense Type")
st.table(summary_df.style.format({"Total Claimed Amount (Rs.)": "{:.2f}", "Total Approved Amount (Rs.)": "{:.2f}"}))

# ---------------------- Plain-language verdict ----------------------
st.subheader("📝 Easy Summary")
verdict_lines = []

verdict_lines.append(f"- Designation **{header_info.get('Designation') or '—'}** → Policy **Category {slab['category']}** ({slab['name']}), Place Category treated as **{place_category}**.")

if dsic_active:
    verdict_lines.append(f"- 🔧 **DSIC tour** — Lodging/Conveyance audited under TE Rules Note 3's day-bracket table (Tier {dsic_tier + 1} of 3), stepping down as the tour progresses; Boarding still uses the general table.")

all_dates_ok = True
if start_dt and end_dt:
    oob_boarding = boarding_day_summary[boarding_day_summary["Rule Applied"].astype(str).str.contains("Outside")] if not boarding_day_summary.empty else pd.DataFrame()
    oob_lodging = lodging_day_summary[lodging_day_summary["Flag"].astype(str).str.contains("Outside")] if not lodging_day_summary.empty else pd.DataFrame()
    oob_conv = conveyance_detail[conveyance_detail.get("Flag", pd.Series(dtype=str)).astype(str).str.contains("Outside")] if not conveyance_detail.empty else pd.DataFrame()
    oob_ticket = ticket_detail[ticket_detail.get("Flag", pd.Series(dtype=str)).astype(str).str.contains("Outside")] if not ticket_detail.empty else pd.DataFrame()
    total_oob = len(oob_boarding) + len(oob_lodging) + len(oob_conv) + len(oob_ticket)
    if total_oob == 0:
        verdict_lines.append(f"- ✅ All claim dates fall within the tour boundary **{start_dt.date()} to {end_dt.date()}** — no out-of-range claims found.")
    else:
        all_dates_ok = False
        verdict_lines.append(f"- ⛔ **{total_oob} line item(s)** have dates OUTSIDE the tour's Start/End range and have been marked NOT approved.")
else:
    verdict_lines.append("- ⚠️ Tour Start/End date-time could not be detected — date-boundary check was skipped.")

if not boarding_day_summary.empty:
    if boarding_claimed == boarding_approved:
        verdict_lines.append(f"- ✅ Boarding(Food): all {df_boarding['Date'].nunique()} day(s) claimed at or below the ₹{boarding_cap}/day cap.")
    else:
        verdict_lines.append(f"- ⚠️ Boarding(Food): claimed ₹{boarding_claimed} vs approved ₹{boarding_approved} — factor/cap deductions applied (see day-wise table).")

if not lodging_day_summary.empty:
    nights_note = ""
    if lodging_expected_nights is not None:
        if lodging_actual_nights == lodging_expected_nights:
            nights_note = f" Night count ({lodging_actual_nights}) matches expected nights for a {header_info.get('Days')}-day tour."
        else:
            nights_note = f" ⚠️ {lodging_actual_nights} night(s) claimed vs {lodging_expected_nights} expected for this tour duration — please verify."
    if lodging_claimed == lodging_approved:
        verdict_lines.append(f"- ✅ Lodging(Hotel): all nights within the ₹{lodging_cap}/night cap.{nights_note}")
    else:
        verdict_lines.append(f"- ⚠️ Lodging(Hotel): claimed ₹{lodging_claimed} vs approved ₹{lodging_approved} — amounts above cap were deducted.{nights_note}")

if not conveyance_detail.empty:
    if dsic_active and conveyance_claimed != conveyance_approved:
        verdict_lines.append(f"- ⚠️ Conveyance(Local): {len(df_conveyance)} trip(s), claimed ₹{conveyance_claimed} vs DSIC-capped approved ₹{conveyance_approved} — see day-wise table for which dates were over the cap.")
    elif dsic_active:
        verdict_lines.append(f"- ✅ Conveyance(Local): {len(df_conveyance)} trip(s), all within the DSIC day-bracket conveyance caps, total ₹{conveyance_approved}.")
    else:
        verdict_lines.append(f"- ✅ Conveyance(Local): {len(df_conveyance)} trip(s) approved on actuals (Taxi/Auto), total ₹{conveyance_approved}.")
if not ticket_detail.empty:
    verdict_lines.append(f"- ✅ Travel Ticket: {len(df_ticket)} ticket(s) approved on actuals, total ₹{ticket_approved}.")
elif df_ticket.empty:
    verdict_lines.append("- ℹ️ No Travel Ticket claims found (likely booked directly by the company, which per Rule IV.9 does not need to be claimed).")

st.markdown("\n".join(verdict_lines))

st.divider()

# ---------------------- Detailed day-wise breakdown ----------------------
st.subheader("📁 Detailed Policy Breakdown")
col_a, col_b = st.columns(2)

with col_a:
    st.markdown("**Boarding(Food) — Day-wise Factor Application**")
    if not boarding_day_summary.empty:
        st.dataframe(boarding_day_summary, use_container_width=True, hide_index=True)
    else:
        st.caption("No boarding/food line items found.")

    st.markdown("**Conveyance(Local) — Actuals**" if not dsic_active else "**Conveyance(Local) — DSIC Day-wise Cap Application**")
    if dsic_active and not conveyance_day_summary.empty:
        st.dataframe(conveyance_day_summary, use_container_width=True, hide_index=True)
        with st.expander("View individual conveyance line items"):
            if not conveyance_detail.empty:
                st.dataframe(conveyance_detail[["Date", "Place", "Claimed Amount", "Distance (Km)"]],
                             use_container_width=True, hide_index=True)
    elif not conveyance_detail.empty:
        st.dataframe(conveyance_detail[["Date", "Place", "Claimed Amount", "Approved Amount", "Distance (Km)"]],
                     use_container_width=True, hide_index=True)
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
        st.dataframe(ticket_detail[["Date", "Place", "Claimed Amount", "Approved Amount"]],
                     use_container_width=True, hide_index=True)
    else:
        st.caption("No travel ticket line items found.")

with st.expander("🔍 View Raw Extracted Line Items (traceability)"):
    st.dataframe(expense_df[["SN", "Date", "Place", "Bucket", "Distance (Km)", "Claimed Amount", "Raw Row"]],
                 use_container_width=True, hide_index=True)

st.divider()

# ---------------------- JV Detail reconciliation ----------------------
st.subheader("🔁 Reconciliation vs PDF's JV Detail Summary")
if jv_df.empty:
    st.caption("No JV Detail summary block found in this PDF to reconcile against.")
else:
    jv_grouped = jv_df.groupby("Bucket").agg(**{"JV Applied (Rs.)": ("JV Applied", "sum"), "JV Approved (Rs.)": ("JV Approved", "sum")}).reset_index()
    computed = pd.DataFrame([
        {"Bucket": "Boarding(Food)", "Expense Detail Claimed (Rs.)": boarding_claimed},
        {"Bucket": "Lodging(Hotel)", "Expense Detail Claimed (Rs.)": lodging_claimed},
        {"Bucket": "Conveyance(Local)", "Expense Detail Claimed (Rs.)": conveyance_claimed},
        {"Bucket": "Travel Ticket", "Expense Detail Claimed (Rs.)": ticket_claimed},
    ])
    recon = computed.merge(jv_grouped, on="Bucket", how="left")
    recon["JV Applied (Rs.)"] = recon["JV Applied (Rs.)"].fillna(0.0)
    recon["Match?"] = recon.apply(
        lambda r: "✅ Match" if abs(r["Expense Detail Claimed (Rs.)"] - r["JV Applied (Rs.)"]) < 0.01 else "⚠️ Mismatch",
        axis=1,
    )
    st.dataframe(recon.rename(columns={"Bucket": "Expense Type"}), use_container_width=True, hide_index=True)

st.divider()

# ---------------------- Grand totals ----------------------
grand_claimed = round(boarding_claimed + lodging_claimed + conveyance_claimed + ticket_claimed, 2)
grand_approved = round(boarding_approved + lodging_approved + conveyance_approved + ticket_approved, 2)
grand_delta = round(grand_approved - grand_claimed, 2)

st.subheader("🧮 Grand Total — Claimed vs Approved")
m1, m2, m3 = st.columns(3)
m1.metric("Grand Total Claimed (Rs.)", f"{grand_claimed:,.2f}")
m2.metric("Grand Total Approved (Rs.)", f"{grand_approved:,.2f}", delta=f"{grand_delta:,.2f}")
m3.metric("Policy Deduction (Rs.)", f"{round(grand_claimed - grand_approved, 2):,.2f}")

if header_info.get("Advance") is not None:
    balance = round(header_info["Advance"] - grand_approved, 2)
    st.info(f"**Advance Received:** ₹{header_info['Advance']:,.2f}  |  **Approved Claim:** ₹{grand_approved:,.2f}  |  **Balance to be {'returned by employee' if balance >= 0 else 'reimbursed to employee'}:** ₹{abs(balance):,.2f}")

if header_info.get("PDF Grand Total") is not None and abs(header_info["PDF Grand Total"] - grand_claimed) > 0.01:
    st.warning(f"⚠️ PDF's own Grand Total (₹{header_info['PDF Grand Total']:,.2f}) does not match the sum of parsed line items (₹{grand_claimed:,.2f}). Please verify manually.")
