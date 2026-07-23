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
import os
import pickle
import re
import uuid
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

# ----------------------------------------------------------------------
# ON-DISK TOUR CACHE — lets a Tour No. link open in a NEW browser tab.
# Streamlit's session_state is per-connection, so a new tab starts a blank
# session and would lose the uploaded PDF's results entirely. Instead, each
# audited tour is pickled to disk (shared by the one running app instance)
# keyed by a random tour_id; the link is "?tour_id=<id>", and any tab/session
# that loads with that query param renders ONLY that tour's report.
# ----------------------------------------------------------------------
CACHE_DIR = "/tmp/tipl_tour_cache"


def save_tour_cache(tour_id, entry):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, f"{tour_id}.pkl"), "wb") as f:
            pickle.dump(entry, f)
    except OSError:
        pass


def load_tour_cache(tour_id):
    path = os.path.join(CACHE_DIR, f"{tour_id}.pkl")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (OSError, pickle.PickleError):
        return None


# ----------------------------------------------------------------------
# HARD-CODED POLICY TABLE — TIPL TE Rules w.e.f. 1st April 2025
# ----------------------------------------------------------------------
# caps = {"Metro": (lodging, boarding), "State Capital": (lodging, boarding), "Other": (lodging, boarding)}
SLAB_TABLE = [
    {"category": 1, "name": "Workmen", "keywords": ["workmen", "workman"],
     "caps": {"Metro": (550, 330), "State Capital": (500, 305), "Other": (450, 305)}},
    {"category": 2, "name": "Trainees / Jr. Executive / Executive / Jr. Tech. Asst. / Tech. Asst. / Jr. Engineer",
     "keywords": ["trainee", "junior executive", "jr. tech. assistant", "jr tech assistant",
                  "tech. assistant", "tech assistant", "jr engineer", "jr. engineer", "junior engineer",
                  "technician"],
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
    "Lodging(Relative)": ["relative"],
    "Lodging(Hotel)": ["lodging", "hotel"],
    "Conveyance(Local)": ["conveyance", "taxi", "auto"],
    "Travel Ticket": ["travel ticket", "ticket", "train", "rail"],
}

# TE Rules I.11 "Minimum Lodging": when an employee stays with a relative
# instead of a Hotel/Guest House, Lodging is capped at 40% of the applicable
# maximum daily Lodging rate, subject to an overall ceiling of Rs. 400/day.
# This uses the GENERAL designation-table Lodging cap (Metro/State Capital/
# Other), even on a DSIC tour - Note 3 only revises the Hotel lodging rate,
# not this separate no-hotel/relative provision.
LODGING_RELATIVE_PERCENT = 0.40
LODGING_RELATIVE_MAX_CAP = 400

AMOUNT_PATTERN = re.compile(r"\d+\.\d{2}")
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
HEADER_DATE_FMT = "%d/%m/%Y %H:%M:%S"
FILENAME_DATE_PATTERN = re.compile(r"(\d{4})[-_](\d{2})[-_](\d{2})")
SUSPICIOUS_FILENAME_WORDS = ["blank", "dummy", "placeholder", "sample", "test"]

# Per TE Rules, Boarding can be claimed WITHOUT bills (Rule II.1). Lodging,
# Conveyance and Travel Ticket all require a submitted bill/voucher/ticket.
BUCKETS_REQUIRING_BILL = {"Lodging(Hotel)", "Lodging(Relative)", "Conveyance(Local)", "Travel Ticket"}


def extract_filename_date(filename):
    """Best-effort: pull a YYYY-MM-DD (or YYYY_MM_DD) token out of an
    attachment filename (common in phone-export names like
    'whatsapp_image_2026-06-27_at...' or '...2026_03_16-11_40_00...').
    NOTE: this is usually just the photo/export timestamp, not the actual
    service date, so a mismatch is only an advisory signal, not proof."""
    if not filename:
        return None
    match = FILENAME_DATE_PATTERN.search(filename)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else None


def is_suspicious_filename(filename):
    """Flags filenames that literally look like placeholders (e.g. containing
    'blank', 'dummy', 'sample') rather than a genuine bill photo/scan."""
    if not filename:
        return False
    low = filename.lower()
    return any(word in low for word in SUSPICIOUS_FILENAME_WORDS)

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
# SIDEBAR — POLICY REFERENCE ONLY (per-tour overrides live inside each
# tour's own expander now, since multiple tours can be audited at once)
# ----------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Policy Reference")
    st.caption("Place Category (Metro / State Capital / Other) is auto-detected per tour from its Place names.")
    st.caption("Metros: " + ", ".join(METRO_CITIES))
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
    """Classify by the EARLIEST-occurring category keyword in the text, with
    one override: 'relative' always wins over the generic 'lodging'/'hotel'
    keywords, because a Lodging(Relative) row's text still literally contains
    the word 'lodging' (e.g. 'Lodging(Relative)Lodging 300.00') earlier in
    the string than the word 'relative' - a plain earliest-position scan
    would otherwise misclassify it as Lodging(Hotel).
    Beyond that override, free-text remarks can contain a rival keyword later
    in the string (e.g. a Conveyance remark 'Hotel to BSP Plant' contains the
    word 'hotel') - the real Expense Type keyword always sits at the very
    start of the row, before any remark text, so earliest-position wins
    rather than a fixed Boarding->Lodging->Conveyance->Ticket scan order."""
    if "relative" in text_lower:
        return "Lodging(Relative)"
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


# TE Rules Note 3 / practical DSIC audit convention: the DSIC Conveyance cap
# applies ONLY to the daily Home/Hotel/Room <-> Site commute (the two trips
# an on-site employee makes every work day). Any OTHER same-day conveyance
# (fetching material, visiting another location, a side errand, etc.) is
# approved on ACTUALS regardless of the DSIC cap.
COMMUTE_TRIP_PATTERNS = [
    r"hotel\s*to\s*site", r"site\s*to\s*hotel",
    r"room\s*to\s*site", r"site\s*to\s*room",
    r"home\s*to\s*site", r"site\s*to\s*home",
]


def is_commute_trip(raw_row_text):
    low = (raw_row_text or "").lower()
    return any(re.search(pattern, low) for pattern in COMMUTE_TRIP_PATTERNS)


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
    # NOTE: some PDFs mis-render their table grid so the Amount column simply
    # never shows up in the extracted cells at all (column boundary detection
    # failure). Rather than discard the whole line item here, leave amount as
    # None - parse_tr_pdf() has a raw-text fallback keyed on SN that recovers
    # these before finally dropping anything still unresolved.
    amount = None
    for c in reversed(cells):
        c_clean = c.replace("\n", "").strip()
        if AMOUNT_PATTERN.fullmatch(c_clean):
            amount = float(c_clean)
            break

    distance = None
    for c in cells[1:]:
        cs = c.strip()
        cs_clean = cs.replace("\n", "").replace(" ", "")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", cs_clean):
            continue
        if cs.isdigit() and len(cs) <= 4:
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

    # Mode of travel: a cell that is exactly one of the known travel modes
    mode = None
    for c in cells:
        cs = c.replace("\n", " ").strip().lower()
        if cs in ("auto", "taxi", "bus", "train", "flight", "own vehicle") or cs.startswith("taxi("):
            mode = c.replace("\n", " ").strip()
            break

    # Route (Origin -> Destination): the remark cell containing " to " as a
    # standalone word, e.g. "Hotel to Plant." or "Vijayawada to nellore."
    # Only meaningful for Conveyance/Travel Ticket - a Lodging row's Hotel
    # Name cell can coincidentally contain " to " (e.g. "Hotel to Kaushalya")
    # and would otherwise be misread as a route.
    route_origin, route_destination = None, None
    if bucket in ("Conveyance(Local)", "Travel Ticket"):
        for c in cells:
            cs = c.replace("\n", " ").strip()
            m = re.search(r"^(.*?)\bto\b(.*?)[\.\s]*$", cs, re.IGNORECASE)
            if m and len(cs) < 120 and " to " in f" {cs.lower()} ":
                origin_raw = m.group(1).strip(" .")
                dest_raw = m.group(2).strip(" .")
                # strip leading mode-of-travel / filler words from the origin
                origin_clean = re.sub(r"^(bus|auto|taxi|train)\s+(from\s+)?|^from\s+", "", origin_raw, flags=re.IGNORECASE).strip()
                if origin_clean and dest_raw:
                    route_origin, route_destination = origin_clean, dest_raw
                    break

    # Hotel Name: for Lodging(Hotel) rows, the "Name of Hotel/Rest." column is
    # typically the LAST non-empty cell (after SN/Date/Place/Bucket/Remark).
    # Used to detect when one bill actually covers several consecutive nights
    # at the same hotel (so only the first night needs its own bill listed).
    hotel_name = None
    if bucket == "Lodging(Hotel)" and len(cells) > 4:
        candidate = cells[-1].replace("\n", " ").strip()
        if candidate and candidate != "-" and not candidate.isdigit():
            hotel_name = candidate

    # Bill Copy filename: the cell (if any) ending in a recognizable file extension
    bill_filename = None
    for c in cells:
        c_clean = c.replace("\n", "").strip()
        if re.search(r"\.(jpe?g|png|gif|pdf|txt|docx?|xlsx?)$", c_clean.lower()):
            bill_filename = c_clean
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
        "Mode": mode,
        "Route Origin": route_origin,
        "Route Destination": route_destination,
        "Hotel Name": hotel_name,
        "Distance (Km)": distance,
        "Claimed Amount": amount,
        "Bill Filename": bill_filename,
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


RAW_TEXT_RECORD_PATTERN = re.compile(
    r"(\d{4}-\d{2}-)\s*\n\s*(\d{1,3})\s+(.+?)\s+(\d+\.\d{2})\s*\n\s*(\d{2})\b",
    re.S,
)


def extract_amounts_from_raw_text(full_text):
    """Fallback for PDFs whose table grid mis-detects the Amount column (the
    cell comes back empty/None even though the value is clearly printed in
    the page text). Recovers {SN: (date, amount)} straight from the text
    stream, using the same 'YYYY-MM-\\n...\\nDD' line-wrapping pattern the
    underlying PDF layout produces for every Expense Detail record."""
    recovered = {}
    for year_month, sn, _middle, amount_str, day in RAW_TEXT_RECORD_PATTERN.findall(full_text):
        try:
            recovered[sn] = (f"{year_month}{day}", float(amount_str))
        except ValueError:
            continue
    return recovered


def extract_amounts_positional(full_text, count_needed):
    """Second-tier fallback for PDFs where even the SN-keyed raw-text pattern
    can't match (this specific export's text stream doesn't keep the SN
    adjacent to its date/amount at all - only a page number is). Recovers
    every currency-shaped amount within the 'Expenses Detail' section (never
    the JV Detail summary above it or the Grand Total below it) and returns
    them in document order. Only usable when the count matches EXACTLY the
    number of rows needing recovery - otherwise a 1:1 positional assumption
    would silently misassign amounts, so this returns None instead of guessing."""
    lower_text = full_text.lower()
    idx_start = lower_text.find("expenses detail")
    if idx_start == -1:
        idx_start = lower_text.find("expense detail")
    idx_end = full_text.find("Grand Total")
    if idx_end == -1 or idx_end < idx_start:
        idx_end = len(full_text)
    section = full_text[idx_start:idx_end] if idx_start != -1 else full_text
    amounts = [float(a) for a in AMOUNT_PATTERN.findall(section)]
    if len(amounts) == count_needed:
        return amounts
    return None


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

    # Fallback recovery: some PDFs' table grid never captures the Amount
    # cell at all (it comes back None even though the row is otherwise
    # intact). Fill those in from the raw text stream instead of losing
    # the whole line item.
    if any(r["Claimed Amount"] is None for r in expense_rows):
        fallback_map = extract_amounts_from_raw_text(full_text)
        for r in expense_rows:
            if r["Claimed Amount"] is None:
                recovered = fallback_map.get(r["SN"])
                if recovered:
                    recovered_date, recovered_amount = recovered
                    r["Claimed Amount"] = recovered_amount
                    if not r.get("Date"):
                        r["Date"] = recovered_date
                        try:
                            r["Date_Parsed"] = datetime.strptime(recovered_date, "%Y-%m-%d")
                        except ValueError:
                            pass

    # Anything still unresolved after the SN-keyed fallback: try the
    # positional fallback (only safe when EVERY row still needs an amount,
    # since that's the only case where a strict 1:1 in-order mapping holds).
    still_missing = [r for r in expense_rows if r["Claimed Amount"] is None]
    if still_missing and len(still_missing) == len(expense_rows):
        positional_amounts = extract_amounts_positional(full_text, len(expense_rows))
        if positional_amounts:
            for r, amt in zip(expense_rows, positional_amounts):
                r["Claimed Amount"] = amt

    # Anything still unresolved after both fallbacks can't be audited reliably - drop it.
    expense_rows = [r for r in expense_rows if r["Claimed Amount"] is not None]

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


def audit_lodging_relative(df_bucket, general_lodging_cap, start_dt, end_dt):
    """TE Rules I.11 Minimum Lodging: 40% of the applicable GENERAL max
    Lodging rate per day, subject to an overall ceiling of Rs. 400/day.
    Always uses the general designation-table Lodging cap, even on DSIC
    tours (Note 3 does not revise this no-hotel/relative provision)."""
    rows = []
    if df_bucket.empty:
        return pd.DataFrame(rows), 0

    start_date = start_dt.date() if start_dt else None
    end_date = end_dt.date() if end_dt else None

    if isinstance(general_lodging_cap, str):  # Director slab -> Actuals, no % cap applies
        day_cap = "Actuals"
    else:
        day_cap = round(min(general_lodging_cap * LODGING_RELATIVE_PERCENT, LODGING_RELATIVE_MAX_CAP), 2)

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
        elif day_cap == "Actuals":
            approved, deduction, flag = claimed, 0.0, "On actuals (Director slab)"
        else:
            approved = round(min(claimed, day_cap), 2)
            deduction = round(max(claimed - day_cap, 0.0), 2)
            flag = "⚠️ Over 40%-of-lodging / Rs.400 cap" if deduction > 0 else "✅ Within cap"

        rows.append({
            "Date": date_str, "Claimed (Rs.)": claimed,
            "Cap (Rs.)": day_cap, "Approved (Rs.)": approved,
            "Deduction (Rs.)": deduction, "Flag": flag,
        })

    actual_nights = df_bucket["Date"].nunique()
    return pd.DataFrame(rows), actual_nights


def audit_lodging_dsic(df_bucket, start_dt, end_dt, tier_index):
    """DSIC Lodging.
    The bracket is chosen ONCE from the TOTAL number of Lodging nights
    claimed on this tour (0-5 / 6-12 / 13-25 / 26-30 / 30+), and that single
    flat per-night rate is then applied uniformly to EVERY night. This
    matches how the >30-night Rental-equivalent case already worked - it is
    a claim-level bracket, not a per-night progression based on calendar
    elapsed time. e.g. 8 nights claimed -> falls in the "06-12" bracket ->
    every night is capped at that bracket's rate (not a mix of 0-5/6-12
    rates depending on which calendar day each night happened to fall on)."""
    rows = []
    if df_bucket.empty or start_dt is None:
        return pd.DataFrame(rows), 0, None

    start_date = start_dt.date()
    end_date = end_dt.date() if end_dt else None
    expected_nights = (end_date - start_date).days if end_date else None
    total_lodging_days = df_bucket["Date"].nunique()

    if total_lodging_days > RENTAL_BRACKET_DAYS:
        cap = round(RENTAL_LODGING_PER_DAY, 2)
        bracket_label = f">{RENTAL_BRACKET_DAYS} nights total — flat Rental-equivalent rate (10000/30)"
    else:
        bracket = get_dsic_bracket_for_day(total_lodging_days)
        raw_cap = bracket["lodging_tiers"][tier_index]
        if isinstance(raw_cap, str):
            cap = round(RENTAL_LODGING_PER_DAY, 2)
            bracket_label = f"{bracket['label']} total ({total_lodging_days} nights) — Rental-equivalent (10000/30)"
        else:
            cap = raw_cap
            bracket_label = f"{bracket['label']} total ({total_lodging_days} nights claimed)"

    for date_str, group in df_bucket.groupby("Date", sort=True):
        claimed = round(group["Claimed Amount"].sum(), 2)
        try:
            this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if end_date and (this_date < start_date or this_date > end_date):
            rows.append({"Date": date_str, "Bracket": "-", "Claimed (Rs.)": claimed,
                         "Cap (Rs.)": "-", "Approved (Rs.)": 0.0, "Deduction (Rs.)": claimed,
                         "Flag": "⛔ Outside tour date range — NOT approved"})
            continue

        approved = round(min(claimed, cap), 2)
        deduction = round(max(claimed - cap, 0.0), 2)
        rows.append({
            "Date": date_str, "Bracket": bracket_label,
            "Claimed (Rs.)": claimed, "Cap (Rs.)": cap, "Approved (Rs.)": approved,
            "Deduction (Rs.)": deduction, "Flag": "⚠️ Over DSIC cap" if deduction > 0 else "✅ Within cap",
        })

    return pd.DataFrame(rows), total_lodging_days, expected_nights


def audit_conveyance_dsic(df_bucket, start_dt, end_dt, tier_index):
    """DSIC Conveyance.
    The DSIC cap applies ONLY to the daily Home/Hotel/Room <-> Site commute.
    Any other same-day trip (material pickup, another location, a side
    errand, etc.) is always approved on actuals, uncapped, regardless of
    the DSIC bracket or tier.
    The bracket is chosen ONCE from the TOTAL number of Conveyance days
    claimed on this tour (0-5 / 6-12 / 13-25 / 26-30 / 30+), and that single
    flat per-day commute cap is then applied uniformly to every day's
    commute portion - the same claim-level bracket logic used for Lodging,
    not a per-day progression based on calendar elapsed time."""
    rows = []
    if df_bucket.empty or start_dt is None:
        return pd.DataFrame(rows)

    start_date = start_dt.date()
    end_date = end_dt.date() if end_dt else None
    total_conveyance_days = df_bucket["Date"].nunique()

    if total_conveyance_days > RENTAL_BRACKET_DAYS:
        cap = round(RENTAL_CONVEYANCE_PER_DAY, 2)
        bracket_label = f">{RENTAL_BRACKET_DAYS} days total — flat Rental-equivalent rate (6000/30), commute only"
    else:
        bracket = get_dsic_bracket_for_day(total_conveyance_days)
        raw_cap = bracket["conveyance_tiers"][tier_index]
        if isinstance(raw_cap, str) and raw_cap.startswith("Rental"):
            cap = round(RENTAL_CONVEYANCE_PER_DAY, 2)
            bracket_label = f"{bracket['label']} total ({total_conveyance_days} days claimed) — Rental-equivalent (6000/30), commute only"
        elif raw_cap == "Actuals":
            cap = "Actuals"
            bracket_label = f"{bracket['label']} total ({total_conveyance_days} days claimed) — commute on actuals"
        else:
            cap = raw_cap
            bracket_label = f"{bracket['label']} total ({total_conveyance_days} days claimed), commute only"

    for date_str, group in df_bucket.groupby("Date", sort=True):
        claimed = round(group["Claimed Amount"].sum(), 2)
        try:
            this_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if end_date and (this_date < start_date or this_date > end_date):
            rows.append({"Date": date_str, "Bracket": "-",
                         "Commute Claimed (Rs.)": claimed, "Commute Cap (Rs.)": "-",
                         "Other Trips - Actuals (Rs.)": 0.0, "Total Claimed (Rs.)": claimed,
                         "Total Approved (Rs.)": 0.0, "Deduction (Rs.)": claimed,
                         "Flag": "⛔ Outside tour date range — NOT approved"})
            continue

        is_commute = group["Raw Row"].apply(is_commute_trip) if "Raw Row" in group.columns else pd.Series([False] * len(group))
        commute_claimed = round(group.loc[is_commute, "Claimed Amount"].sum(), 2)
        other_claimed = round(group.loc[~is_commute, "Claimed Amount"].sum(), 2)

        if cap == "Actuals":
            commute_approved = commute_claimed
        else:
            commute_approved = round(min(commute_claimed, cap), 2)

        total_claimed = round(commute_claimed + other_claimed, 2)
        total_approved = round(commute_approved + other_claimed, 2)
        deduction = round(total_claimed - total_approved, 2)

        rows.append({
            "Date": date_str, "Bracket": bracket_label,
            "Commute Claimed (Rs.)": commute_claimed,
            "Commute Cap (Rs.)": cap,
            "Other Trips - Actuals (Rs.)": other_claimed,
            "Total Claimed (Rs.)": total_claimed, "Total Approved (Rs.)": total_approved,
            "Deduction (Rs.)": deduction,
            "Flag": "⚠️ Commute over DSIC cap" if deduction > 0 else "✅ Within cap",
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


def build_bill_verification_table(expense_df):
    """Bill-presence + filename-date sanity check for Lodging, Conveyance and
    Travel Ticket claims (Boarding is exempt - Rule II.1 needs no bill).
    This can only check what's IN the PDF text: whether a Bill Copy filename
    was listed, and whether any date embedded in that filename lines up with
    the claimed date. It cannot see or read the actual bill image/PDF content
    (those files are not embedded in this PDF, only referenced by name)."""
    rows = []
    df = expense_df[expense_df["Bucket"].isin(BUCKETS_REQUIRING_BILL)]
    for _, r in df.iterrows():
        filename_raw = r.get("Bill Filename")
        filename = filename_raw if isinstance(filename_raw, str) and filename_raw.strip() else None
        filename_date = extract_filename_date(filename) if filename else None

        if not filename:
            flag = "⛔ No bill/attachment listed"
        elif is_suspicious_filename(filename):
            flag = "⚠️ Filename looks like a placeholder (e.g. 'blank'/'dummy') — verify manually"
        elif filename_date and filename_date != r["Date"]:
            flag = f"⚠️ Filename date ({filename_date}) differs from claim date — verify manually"
        else:
            flag = "✅ Bill attached"

        rows.append({
            "Date": r["Date"], "Expense Type": r["Bucket"], "Place": r.get("Place"),
            "Amount (Rs.)": r["Claimed Amount"], "Bill Filename": filename or "(none)",
            "Filename Date Found": filename_date or "-", "Status": flag,
        })
    return pd.DataFrame(rows)


def build_route_table(df_conveyance):
    """Origin -> Destination + Rate/Km view for Conveyance claims, so a human
    reviewer can quickly sanity-check whether the claimed distance/amount look
    reasonable for the stated route. Extreme Rate/Km outliers are flagged for
    manual review - this is a heuristic, not a verified real-world distance
    (no map/geocoding service is queried)."""
    rows = []
    if df_conveyance.empty:
        return pd.DataFrame(rows)
    for _, r in df_conveyance.iterrows():
        distance = r.get("Distance (Km)")
        amount = r["Claimed Amount"]
        try:
            distance_val = float(distance) if distance not in (None, "") and pd.notna(distance) else None
        except (TypeError, ValueError):
            distance_val = None
        rate_per_km = round(amount / distance_val, 2) if distance_val and distance_val > 0 else None
        flag = "⚠️ Unusually high Rs./km — verify manually" if (rate_per_km and rate_per_km > 50) else "✅ Looks reasonable"

        origin_raw = r.get("Route Origin")
        dest_raw = r.get("Route Destination")
        mode_raw = r.get("Mode")
        origin = origin_raw if isinstance(origin_raw, str) and origin_raw.strip() else "-"
        destination = dest_raw if isinstance(dest_raw, str) and dest_raw.strip() else "-"
        mode = mode_raw if isinstance(mode_raw, str) and mode_raw.strip() else "-"

        rows.append({
            "Date": r["Date"], "Origin": origin, "Destination": destination,
            "Mode": mode, "Distance (Km)": distance_val if distance_val is not None else "-",
            "Amount (Rs.)": amount, "Rate (Rs./Km)": rate_per_km if rate_per_km is not None else "-",
            "Flag": flag if rate_per_km is not None else "ℹ️ No distance listed",
        })
    return pd.DataFrame(rows)





# ----------------------------------------------------------------------
# PURE COMPUTATION LAYER (no Streamlit calls) — lets one tour's audit be
# computed independently of how many other tours are queued at once.
# ----------------------------------------------------------------------
def resolve_policy_params(header_info, expense_df, category_override=None, place_override=None, dsic_tier_override=None):
    """category_override: int category number or None.
       place_override: 'Metro' / 'State Capital' / 'Other' or None.
       dsic_tier_override: 0 / 1 / 2 or None."""
    if category_override is not None:
        slab = next((s for s in SLAB_TABLE if s["category"] == category_override), None)
    else:
        slab = match_designation_slab(header_info.get("Designation"))

    detected_place_category, matched_place_names = auto_detect_place_category(
        expense_df["Place"].dropna().unique().tolist()
    )
    place_category = place_override or detected_place_category

    dsic_active = is_dsic_tour(header_info)
    dsic_tier = None
    if dsic_active and slab is not None:
        dsic_tier = dsic_tier_override if dsic_tier_override is not None else dsic_tier_index(slab["category"])

    return {
        "slab": slab,
        "detected_place_category": detected_place_category,
        "matched_place_names": matched_place_names,
        "place_category": place_category,
        "dsic_active": dsic_active,
        "dsic_tier": dsic_tier,
    }


def compute_audit(header_info, expense_df, jv_df, policy_params):
    """Pure computation: runs the full policy engine for one tour and returns
    a results dict. No Streamlit calls happen in here, so this can run for as
    many queued tours as needed without touching the UI."""
    slab = policy_params["slab"]

    if slab is None:
        return {
            "error": "Could not auto-match this Designation to a TE Rules slab. Use the override controls below.",
            "header_info": header_info, "expense_df": expense_df, "jv_df": jv_df,
        }

    place_category = policy_params["place_category"]
    dsic_active = policy_params["dsic_active"]
    dsic_tier = policy_params["dsic_tier"]

    start_dt = header_info.get("Start Date")
    end_dt = header_info.get("End Date")
    lodging_cap, boarding_cap = slab["caps"][place_category]

    df_boarding = expense_df[expense_df["Bucket"] == "Boarding(Food)"].copy()
    df_lodging = expense_df[expense_df["Bucket"] == "Lodging(Hotel)"].copy()
    df_lodging_relative = expense_df[expense_df["Bucket"] == "Lodging(Relative)"].copy()
    df_conveyance = expense_df[expense_df["Bucket"] == "Conveyance(Local)"].copy()
    df_ticket = expense_df[expense_df["Bucket"] == "Travel Ticket"].copy()

    boarding_day_summary = audit_boarding(df_boarding, boarding_cap, start_dt, end_dt)
    ticket_detail = audit_actuals(df_ticket, start_dt, end_dt)
    lodging_relative_day_summary, lodging_relative_nights = audit_lodging_relative(df_lodging_relative, lodging_cap, start_dt, end_dt)

    if dsic_active and dsic_tier is not None:
        lodging_day_summary, lodging_actual_nights, lodging_expected_nights = audit_lodging_dsic(df_lodging, start_dt, end_dt, dsic_tier)
        conveyance_day_summary = audit_conveyance_dsic(df_conveyance, start_dt, end_dt, dsic_tier)
        conveyance_detail = audit_actuals(df_conveyance, start_dt, end_dt)
    else:
        lodging_day_summary, lodging_actual_nights, lodging_expected_nights = audit_lodging(df_lodging, lodging_cap, start_dt, end_dt)
        conveyance_detail = audit_actuals(df_conveyance, start_dt, end_dt)
        conveyance_day_summary = pd.DataFrame()

    boarding_claimed = round(df_boarding["Claimed Amount"].sum(), 2) if not df_boarding.empty else 0.0
    boarding_approved = round(boarding_day_summary["Approved (Rs.)"].sum(), 2) if not boarding_day_summary.empty else 0.0
    lodging_claimed = round(df_lodging["Claimed Amount"].sum(), 2) if not df_lodging.empty else 0.0
    lodging_approved = round(lodging_day_summary["Approved (Rs.)"].sum(), 2) if not lodging_day_summary.empty else 0.0
    lodging_relative_claimed = round(df_lodging_relative["Claimed Amount"].sum(), 2) if not df_lodging_relative.empty else 0.0
    lodging_relative_approved = round(lodging_relative_day_summary["Approved (Rs.)"].sum(), 2) if not lodging_relative_day_summary.empty else 0.0
    conveyance_claimed = round(conveyance_detail["Claimed Amount"].sum(), 2) if not conveyance_detail.empty else 0.0
    if dsic_active and not conveyance_day_summary.empty:
        conveyance_approved = round(conveyance_day_summary["Total Approved (Rs.)"].sum(), 2)
    else:
        conveyance_approved = round(conveyance_detail["Approved Amount"].sum(), 2) if not conveyance_detail.empty else 0.0
    ticket_claimed = round(ticket_detail["Claimed Amount"].sum(), 2) if not ticket_detail.empty else 0.0
    ticket_approved = round(ticket_detail["Approved Amount"].sum(), 2) if not ticket_detail.empty else 0.0

    summary_rows = [
        {"Expense Type": "Boarding(Food)", "Total Days / Units": df_boarding["Date"].nunique() if not df_boarding.empty else 0,
         "Total Claimed Amount (Rs.)": boarding_claimed, "Total Approved Amount (Rs.)": boarding_approved,
         "Verdict": "✅ Compliant" if boarding_claimed == boarding_approved else "⚠️ Deduction Applied"},
        {"Expense Type": "Lodging(Hotel)", "Total Days / Units": df_lodging["Date"].nunique() if not df_lodging.empty else 0,
         "Total Claimed Amount (Rs.)": lodging_claimed, "Total Approved Amount (Rs.)": lodging_approved,
         "Verdict": "✅ Compliant" if lodging_claimed == lodging_approved else "⚠️ Deduction Applied"},
    ]
    if not df_lodging_relative.empty:
        summary_rows.append(
            {"Expense Type": "Lodging(Relative)", "Total Days / Units": df_lodging_relative["Date"].nunique(),
             "Total Claimed Amount (Rs.)": lodging_relative_claimed, "Total Approved Amount (Rs.)": lodging_relative_approved,
             "Verdict": "✅ Compliant" if lodging_relative_claimed == lodging_relative_approved else "⚠️ Deduction Applied"}
        )
    summary_rows.extend([
        {"Expense Type": "Conveyance(Local)", "Total Days / Units": len(df_conveyance),
         "Total Claimed Amount (Rs.)": conveyance_claimed, "Total Approved Amount (Rs.)": conveyance_approved,
         "Verdict": "✅ Compliant" if conveyance_claimed == conveyance_approved else "⚠️ Deduction Applied"},
        {"Expense Type": "Travel Ticket", "Total Days / Units": len(df_ticket),
         "Total Claimed Amount (Rs.)": ticket_claimed, "Total Approved Amount (Rs.)": ticket_approved,
         "Verdict": "✅ Compliant" if ticket_claimed == ticket_approved else "⚠️ Deduction Applied"},
    ])
    summary_df = pd.DataFrame(summary_rows)

    bill_table = build_bill_verification_table(expense_df)
    route_table = build_route_table(df_conveyance)

    grand_claimed = round(boarding_claimed + lodging_claimed + lodging_relative_claimed + conveyance_claimed + ticket_claimed, 2)
    grand_approved = round(boarding_approved + lodging_approved + lodging_relative_approved + conveyance_approved + ticket_approved, 2)

    # ---- Overall pass/fail flags for the Tour Audit AI summary row ----
    issues = []
    if grand_claimed != grand_approved:
        issues.append(f"Policy deduction of Rs.{round(grand_claimed - grand_approved, 2):,.2f}")
    if not bill_table.empty:
        missing_bills = int(bill_table["Status"].str.contains("No bill").sum())
        if missing_bills:
            issues.append(f"{missing_bills} missing bill(s)")
        suspicious_bills = int(bill_table["Status"].str.contains("placeholder").sum())
        if suspicious_bills:
            issues.append(f"{suspicious_bills} bill(s) with a placeholder-looking filename")
    if not jv_df.empty:
        jv_grouped = jv_df.groupby("Bucket").agg(**{"JV Applied": ("JV Applied", "sum")}).reset_index()
        computed_map = {
            "Boarding(Food)": boarding_claimed, "Lodging(Hotel)": lodging_claimed,
            "Lodging(Relative)": lodging_relative_claimed, "Conveyance(Local)": conveyance_claimed,
            "Travel Ticket": ticket_claimed,
        }
        for _, jv_row in jv_grouped.iterrows():
            if abs(computed_map.get(jv_row["Bucket"], 0.0) - jv_row["JV Applied"]) > 0.01:
                issues.append(f"JV mismatch in {jv_row['Bucket']}")
    for df_check, label in [(boarding_day_summary, "Boarding"), (lodging_day_summary, "Lodging"),
                             (conveyance_detail, "Conveyance"), (ticket_detail, "Travel Ticket")]:
        if not df_check.empty and "Flag" in df_check.columns:
            oob = int(df_check["Flag"].astype(str).str.contains("Outside").sum())
            if oob:
                issues.append(f"{oob} {label} item(s) outside tour dates")

    return {
        "error": None,
        "header_info": header_info, "expense_df": expense_df, "jv_df": jv_df,
        "slab": slab, "place_category": place_category, "dsic_active": dsic_active, "dsic_tier": dsic_tier,
        "lodging_cap": lodging_cap, "boarding_cap": boarding_cap,
        "detected_place_category": policy_params["detected_place_category"],
        "matched_place_names": policy_params["matched_place_names"],
        "df_boarding": df_boarding, "df_lodging": df_lodging, "df_lodging_relative": df_lodging_relative,
        "df_conveyance": df_conveyance, "df_ticket": df_ticket,
        "boarding_day_summary": boarding_day_summary, "lodging_day_summary": lodging_day_summary,
        "lodging_relative_day_summary": lodging_relative_day_summary, "lodging_relative_nights": lodging_relative_nights,
        "lodging_actual_nights": lodging_actual_nights, "lodging_expected_nights": lodging_expected_nights,
        "conveyance_day_summary": conveyance_day_summary, "conveyance_detail": conveyance_detail, "ticket_detail": ticket_detail,
        "boarding_claimed": boarding_claimed, "boarding_approved": boarding_approved,
        "lodging_claimed": lodging_claimed, "lodging_approved": lodging_approved,
        "lodging_relative_claimed": lodging_relative_claimed, "lodging_relative_approved": lodging_relative_approved,
        "conveyance_claimed": conveyance_claimed, "conveyance_approved": conveyance_approved,
        "ticket_claimed": ticket_claimed, "ticket_approved": ticket_approved,
        "summary_df": summary_df, "bill_table": bill_table, "route_table": route_table,
        "grand_claimed": grand_claimed, "grand_approved": grand_approved,
        "issues": issues, "is_clean": len(issues) == 0,
    }


def render_results(r, key_prefix):
    """All the st.* display for ONE tour's computed results, matching the
    company portal's own 'Expense Detail' page format: Information header,
    then JV Detail (with added Days / AI Approved Amount columns, row
    highlighted red wherever the AI-approved amount doesn't match TE Rules),
    then Expenses Detail (amount highlighted red wherever a required bill
    is missing). No separate summary/tabs - this mirrors show_expense.pdf."""
    header_info = r["header_info"]
    expense_df = r["expense_df"]
    slab = r["slab"]
    place_category = r["place_category"]
    dsic_active = r["dsic_active"]
    dsic_tier = r["dsic_tier"]
    boarding_cap = r["boarding_cap"]
    start_dt = header_info.get("Start Date")
    end_dt = header_info.get("End Date")

    df_boarding, df_lodging, df_lodging_relative = r["df_boarding"], r["df_lodging"], r["df_lodging_relative"]
    df_conveyance, df_ticket = r["df_conveyance"], r["df_ticket"]
    boarding_claimed, boarding_approved = r["boarding_claimed"], r["boarding_approved"]
    lodging_claimed, lodging_approved = r["lodging_claimed"], r["lodging_approved"]
    lodging_relative_claimed, lodging_relative_approved = r["lodging_relative_claimed"], r["lodging_relative_approved"]
    conveyance_claimed, conveyance_approved = r["conveyance_claimed"], r["conveyance_approved"]
    ticket_claimed, ticket_approved = r["ticket_claimed"], r["ticket_approved"]
    grand_claimed, grand_approved = r["grand_claimed"], r["grand_approved"]

    # ---------------------- Header card (mirrors the portal's "Information" block) ----------------------
    st.subheader("🗂️ Information")
    h1, h2, h3, h4, h5 = st.columns(5)
    h1.metric("Tour No.", header_info.get("Tour No") or "—")
    h2.metric("Employee", header_info.get("Employee Name") or "—")
    h3.metric("Designation", header_info.get("Designation") or "—")
    h4.metric("Days", header_info.get("Days") or "—")
    h5.metric("Department", header_info.get("Employee Department") or "—")
    d1, d2 = st.columns(2)
    d1.info(f"**Start Date:** {start_dt.strftime('%d/%m/%Y %H:%M:%S') if start_dt else header_info.get('Start Date Raw', 'Not detected')}")
    d2.info(f"**End Date:** {end_dt.strftime('%d/%m/%Y %H:%M:%S') if end_dt else header_info.get('End Date Raw', 'Not detected')}")
    if dsic_active:
        st.caption(f"🔧 DSIC tour — Lodging/Conveyance audited under TE Rules Note 3 (Tier {dsic_tier + 1} of 3, {place_category}); Boarding uses the general table (₹{boarding_cap}/day).")

    # ---------------------- JV Detail: Days + AI Approved Amount, red row on mismatch ----------------------
    st.subheader("JV Detail")
    st.caption("Row highlighted red = TE Rules Auto-Audit does not match the Applied Amount (a policy deduction was found).")

    jv_rows = []
    if not df_boarding.empty:
        jv_rows.append({"Account Code": "3443", "Expense Type": "Boarding(Food)", "Days": df_boarding["Date"].nunique(),
                         "Applied Amount": boarding_claimed, "AI Approved Amount": boarding_approved})
    if not df_lodging.empty:
        jv_rows.append({"Account Code": "3442", "Expense Type": "Lodging(Hotel)", "Days": df_lodging["Date"].nunique(),
                         "Applied Amount": lodging_claimed, "AI Approved Amount": lodging_approved})
    if not df_lodging_relative.empty:
        jv_rows.append({"Account Code": "3442", "Expense Type": "Lodging(Relative)", "Days": df_lodging_relative["Date"].nunique(),
                         "Applied Amount": lodging_relative_claimed, "AI Approved Amount": lodging_relative_approved})
    if not df_conveyance.empty:
        jv_rows.append({"Account Code": "3207/3505", "Expense Type": "Conveyance(Local)", "Days": df_conveyance["Date"].nunique(),
                         "Applied Amount": conveyance_claimed, "AI Approved Amount": conveyance_approved})
    if not df_ticket.empty:
        jv_rows.append({"Account Code": "3441", "Expense Type": "Travel Ticket", "Days": len(df_ticket),
                         "Applied Amount": ticket_claimed, "AI Approved Amount": ticket_approved})

    jv_summary_df = pd.DataFrame(jv_rows)
    if not jv_summary_df.empty:
        jv_summary_df["TE Rules Check"] = jv_summary_df.apply(
            lambda row: "✅ Matches TE Rules" if abs(row["Applied Amount"] - row["AI Approved Amount"]) < 0.01
            else f"✕ Deduction ₹{row['Applied Amount'] - row['AI Approved Amount']:,.2f}",
            axis=1,
        )

        def _highlight_mismatch(row):
            is_mismatch = abs(row["Applied Amount"] - row["AI Approved Amount"]) >= 0.01
            return ["background-color: #fdecec; color: #6b2320" if is_mismatch else "" for _ in row]

        styled_jv = jv_summary_df.style.apply(_highlight_mismatch, axis=1).format(
            {"Applied Amount": "₹{:,.2f}", "AI Approved Amount": "₹{:,.2f}"}
        )
        st.dataframe(styled_jv, use_container_width=True, hide_index=True)
        st.markdown(f"**Grand Total** — Applied: ₹{grand_claimed:,.2f}  |  AI Approved: ₹{grand_approved:,.2f}")
    else:
        st.caption("No JV Detail line items found.")

    if header_info.get("Advance") is not None:
        balance = round(header_info["Advance"] - grand_approved, 2)
        st.info(f"**Advance Received:** ₹{header_info['Advance']:,.2f}  |  **AI Approved Claim:** ₹{grand_approved:,.2f}  |  **Balance to be {'returned by employee' if balance >= 0 else 'reimbursed to employee'}:** ₹{abs(balance):,.2f}")

    # ---------------------- Expenses Detail: red amount where a bill is missing OR the rate looks abnormally high ----------------------
    st.subheader("Expenses Detail")
    st.caption(
        "Amount highlighted red = either the required bill/voucher is missing (Boarding is exempt per Rule II.1), "
        "or - for Conveyance - the claimed Rs./Km looks unusually high and needs manual review. "
        "Note: if ONE night of a multi-night hotel stay has a bill attached, the other consecutive nights of that "
        "same stay are treated as covered by it, not flagged as missing."
    )

    def _lodging_bill_coverage(df_bucket):
        """Consecutive calendar dates (no gap) count as ONE stay. If any date
        in that stay has a bill, every date in the same stay is covered -
        hotels commonly issue one invoice for a multi-night stay, attached
        to only one of the claim rows."""
        covered = set()
        if df_bucket.empty:
            return covered
        dates_sorted = sorted(df_bucket["Date"].unique())
        has_bill_by_date = {d: bool(df_bucket.loc[df_bucket["Date"] == d, "Bill Filename"].notna().any()) for d in dates_sorted}
        run, prev_date = [], None
        for d in dates_sorted:
            this_date = datetime.strptime(d, "%Y-%m-%d").date()
            if prev_date is not None and (this_date - prev_date).days > 1:
                if any(has_bill_by_date[x] for x in run):
                    covered.update(run)
                run = []
            run.append(d)
            prev_date = this_date
        if any(has_bill_by_date[x] for x in run):
            covered.update(run)
        return covered

    lodging_covered_dates = _lodging_bill_coverage(df_lodging) | _lodging_bill_coverage(df_lodging_relative)

    detail_cols = ["SN", "Date", "Place", "Bucket", "Mode", "Route Origin", "Route Destination", "Distance (Km)", "Claimed Amount", "Bill Filename"]
    detail_df = expense_df[detail_cols].copy().sort_values("SN", key=lambda s: s.astype(int))
    detail_df["Particulars / Remark"] = detail_df.apply(
        lambda row: f"{row['Route Origin']} to {row['Route Destination']}" if pd.notna(row.get("Route Origin")) else "", axis=1
    )
    detail_df["Bill Copy"] = detail_df["Bill Filename"].apply(lambda v: v if pd.notna(v) else "-")

    def _is_missing_bill(row):
        if row["Bucket"] not in BUCKETS_REQUIRING_BILL or pd.notna(row["Bill Filename"]):
            return False
        if row["Bucket"] in ("Lodging(Hotel)", "Lodging(Relative)") and row["Date"] in lodging_covered_dates:
            return False
        return True

    def _conveyance_rate(row):
        if row["Bucket"] != "Conveyance(Local)":
            return None
        try:
            distance = float(row["Distance (Km)"]) if pd.notna(row["Distance (Km)"]) else None
        except (TypeError, ValueError):
            distance = None
        if not distance or distance <= 0:
            return None
        return row["Claimed Amount"] / distance

    detail_df["Missing Bill"] = detail_df.apply(_is_missing_bill, axis=1)
    detail_df["Rate Per Km"] = detail_df.apply(_conveyance_rate, axis=1)
    detail_df["High Rate"] = detail_df["Rate Per Km"].apply(lambda v: v is not None and v > 50)

    def _flag_text(row):
        parts = []
        if row["Missing Bill"]:
            parts.append("⛔ No bill/voucher")
        if row["High Rate"]:
            parts.append(f"⚠️ High rate (₹{row['Rate Per Km']:.1f}/km)")
        return " | ".join(parts)

    detail_df["Flag"] = detail_df.apply(_flag_text, axis=1)

    display_df = detail_df[["SN", "Date", "Place", "Bucket", "Particulars / Remark", "Mode", "Distance (Km)", "Claimed Amount", "Bill Copy", "Flag", "Missing Bill", "High Rate"]].rename(
        columns={"Bucket": "Expense Type", "Claimed Amount": "Amount (Rs.)"}
    )

    plot_df = display_df.drop(columns=["Missing Bill", "High Rate"])
    amount_col_idx = plot_df.columns.get_loc("Amount (Rs.)")

    def _highlight_row(row_index):
        styles = [""] * len(plot_df.columns)
        if display_df.loc[row_index, "Missing Bill"] or display_df.loc[row_index, "High Rate"]:
            styles[amount_col_idx] = "background-color: #fdecec; color: #b3261e; font-weight: 700;"
        return styles

    styled_detail = plot_df.style.apply(
        lambda row: _highlight_row(row.name), axis=1
    ).format({"Amount (Rs.)": "₹{:,.2f}"})
    st.dataframe(styled_detail, use_container_width=True, hide_index=True, height=min(35 * len(display_df) + 40, 900))

    st.caption(
        "⚠️ Note on bill verification: this only checks whether a filename was listed and whether consecutive-night "
        "lodging is covered by a nearby bill - it cannot open, fetch, or visually inspect the actual bill image/PDF, "
        "since those files are referenced by name only and are not embedded in or downloadable from this document."
    )


# ----------------------------------------------------------------------
# PORTAL-STYLE UI — mirrors the company's live.tipl.com "View Tour Report"
# screen (Fresh / Pending For DSIC CEO Office Approval / Pending For Document
# Received / stages...), with a new "Tour Audit AI" stage inserted right
# after "Pending For Document Received" that auto-audits every tour in the
# queue and marks each row ✅ / ❌ automatically.
# ----------------------------------------------------------------------
st.markdown(
    """
    <style>
    div[data-testid="stExpander"] details summary {
        background: linear-gradient(180deg, #f5f5f5, #e2e2e2);
        border: 1px solid #c8c8c8;
        border-radius: 6px;
        padding: 6px 14px;
        font-weight: 600;
        color: #222;
    }
    div[data-testid="stExpander"] details summary:hover { background: #e8e8e8; }
    div[data-testid="stExpander"] { border: none; }
    </style>
    """,
    unsafe_allow_html=True,
)

query_tour_id = st.query_params.get("tour_id")
if query_tour_id:
    cached_entry = load_tour_cache(query_tour_id)
    st.markdown("[← Back to Tour Audit AI queue](/)")
    if cached_entry is None:
        st.error("This report link has expired or the app was restarted. Please reopen the tour from the Tour Audit AI queue.")
        st.stop()
    if cached_entry.get("error"):
        st.error(cached_entry["error"])
        st.stop()
    render_results(cached_entry, key_prefix="standalone")
    st.stop()

st.markdown("### Tour Audit AI")
st.caption("TIPL Travel Expense Auto-Audit Engine — TE Rules w.e.f. 1-Apr-2025 built in. This is only the 'Tour Audit AI' stage — your IT team will insert this as one row into the live portal, directly under the existing 'Pending For Document Received' stage.")

# ---------------------- Tour Audit AI (the functional stage) ----------------------
if "tour_audit_results" not in st.session_state:
    st.session_state.tour_audit_results = []
if "tour_audit_filenames" not in st.session_state:
    st.session_state.tour_audit_filenames = set()

with st.expander(f"🤖 Tour Audit AI ({len(st.session_state.tour_audit_results)})", expanded=True):
    st.caption("Add one or more Tour Expense (TR) PDFs below — each is auto-audited immediately and appears as a row here. In production this stage would instead read tours directly from the database (fed by your existing 'Pending For Document Received' stage), with no upload step at all.")
    uploaded_files = st.file_uploader(
        "Add Tour Expense (TR) PDFs to the audit queue", type=["pdf"], accept_multiple_files=True, key="tour_audit_uploader"
    )

    if uploaded_files:
        for f in uploaded_files:
            if f.name in st.session_state.tour_audit_filenames:
                continue
            try:
                file_bytes = f.read()
                header_info, expense_df, jv_df = parse_tr_pdf(file_bytes)
                if expense_df.empty:
                    entry = {"error": "No valid line items found in 'Expenses Detail'.", "header_info": header_info, "filename": f.name}
                else:
                    policy_params = resolve_policy_params(header_info, expense_df)
                    entry = compute_audit(header_info, expense_df, jv_df, policy_params)
                    entry["filename"] = f.name
            except Exception as exc:
                entry = {"error": f"Could not parse this PDF: {exc}", "header_info": {}, "filename": f.name}

            tour_no_raw = (entry.get("header_info") or {}).get("Tour No") or f.name
            tour_id = re.sub(r"[^A-Za-z0-9_-]", "_", tour_no_raw)
            entry["tour_id"] = tour_id
            save_tour_cache(tour_id, entry)

            st.session_state.tour_audit_results.append(entry)
            st.session_state.tour_audit_filenames.add(f.name)

    if not st.session_state.tour_audit_results:
        st.info("No tours in the audit queue yet. Add PDF(s) above to see them auto-audited below.")
    else:
        st.markdown(
            """
            <style>
            div[data-testid="stButton"] > button {
                background: none;
                border: none;
                padding: 0;
                color: #1a5fb4;
                font-weight: 600;
                text-decoration: none;
            }
            div[data-testid="stButton"] > button:hover {
                text-decoration: underline;
                color: #0d3d75;
            }
            div[data-testid="stButton"] > button:focus:not(:active) {
                color: #1a5fb4;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        hc1, hc2, hc3, hc4, hc5 = st.columns([1.3, 1.6, 1.2, 1.2, 1.2])
        hc1.markdown("**Tour No.**")
        hc2.markdown("**Employee Name**")
        hc3.markdown("**Start Date**")
        hc4.markdown("**End Date**")
        hc5.markdown("**Tour Type**")
        st.divider()

        for idx, r in enumerate(st.session_state.tour_audit_results):
            hi = r.get("header_info") or {}
            tour_no = hi.get("Tour No") or r.get("filename") or f"Tour {idx + 1}"
            tour_id = r.get("tour_id")
            rc1, rc2, rc3, rc4, rc5 = st.columns([1.3, 1.6, 1.2, 1.2, 1.2])
            with rc1:
                if tour_id:
                    st.markdown(
                        f'<a href="?tour_id={tour_id}" target="_blank" '
                        f'style="color:#1a5fb4;font-weight:600;text-decoration:none;">{tour_no}</a>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.write(tour_no)
            rc2.write(hi.get("Employee Name") or "—")
            rc3.write(hi.get("Start Date Raw") or "—")
            rc4.write(hi.get("End Date Raw") or "—")
            rc5.write(hi.get("Employee Department") or "—")

        st.caption("Click a Tour No. above to open its full report in a new tab (JV Detail + Expenses Detail).")

        st.markdown("---")
        if st.button("🗑️ Clear Audit Queue"):
            st.session_state.tour_audit_results = []
            st.session_state.tour_audit_filenames = set()
            st.rerun()
