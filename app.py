def extract_text(uploaded_file):
    text = ""

    try:
        uploaded_file.seek(0)

        with pdfplumber.open(uploaded_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        if len(text.strip()) > 100:
            return text

    except:
        pass

    uploaded_file.seek(0)

    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")

        for page in doc:
            text += page.get_text()

        if len(text.strip()) > 100:
            return text

    except:
        pass

    uploaded_file.seek(0)

    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")

        for page in doc:

            pix = page.get_pixmap(dpi=300)

            img = Image.open(io.BytesIO(pix.tobytes("png")))

            text += pytesseract.image_to_string(img)

    except:
        pass

    return text
    if uploaded_file:
    file_text = extract_text(uploaded_file)
    Boarding(Food)
Taxi
Auto
import re

def smart_extract_amount(text, keywords):
    """
    Extracts all amounts associated with any keyword.
    Returns total amount.
    """

    total = 0.0

    patterns = [
        r"{}\s*[:\-]?\s*Rs\.?\s*([\d,]+\.\d{{2}})",
        r"{}\s*[:\-]?\s*([\d,]+\.\d{{2}})",
        r"Rs\.?\s*([\d,]+\.\d{{2}})\s*{}",
        r"{}\D{{0,20}}([\d,]+\.\d{{2}})"
    ]

    for key in keywords:

        for pattern in patterns:

            regex = pattern.format(re.escape(key))

            matches = re.findall(regex, text, re.IGNORECASE)

            for m in matches:

                try:

                    total += float(m.replace(",", ""))

                except:

                    pass

    return round(total,2)
    board_claim = fetch_strict_val(...)
    board_claim = smart_extract_amount(file_text,
[
"Boarding",
"Food",
"Meal",
"Meals",
"Breakfast",
"Lunch",
"Dinner",
"Food Charges",
"Refreshment"
])

lodg_claim = smart_extract_amount(file_text,
[
"Lodging",
"Hotel",
"Hotel Charges",
"Accommodation",
"Stay",
"Room Rent"
])

conv_claim = smart_extract_amount(file_text,
[
"Taxi",
"Cab",
"Uber",
"OLA",
"Rapido",
"Auto",
"Rickshaw",
"Metro",
"Bus",
"Parking",
"Toll",
"Fuel",
"Conveyance",
"Local Travel"
])

tkt_claim = smart_extract_amount(file_text,
[
"Flight",
"Air Ticket",
"Train",
"Rail",
"Bus Ticket",
"Travel Ticket",
"Ticket",
"Airfare"
])
def detect_documents(file_text):

    text = file_text.lower()

    documents = {
        "tour_summary": False,
        "hotel_bill": False,
        "food_bill": False,
        "taxi_bill": False,
        "flight_ticket": False,
        "train_ticket": False,
        "bus_ticket": False,
        "gst_invoice": False,
        "fuel_bill": False
    }

    # Tour Summary
    if any(x in text for x in [
        "tour no",
        "tour summary",
        "employee name",
        "designation",
        "start date",
        "end date"
    ]):
        documents["tour_summary"] = True

    # Hotel
    if any(x in text for x in [
        "hotel",
        "accommodation",
        "room",
        "check in",
        "check out",
        "room rent"
    ]):
        documents["hotel_bill"] = True

    # Food
    if any(x in text for x in [
        "food",
        "meal",
        "restaurant",
        "breakfast",
        "lunch",
        "dinner",
        "refreshment"
    ]):
        documents["food_bill"] = True

    # Taxi
    if any(x in text for x in [
        "taxi",
        "cab",
        "uber",
        "ola",
        "rapido",
        "auto",
        "rickshaw"
    ]):
        documents["taxi_bill"] = True

    # Flight
    if any(x in text for x in [
        "flight",
        "boarding pass",
        "pnr",
        "air ticket",
        "airfare"
    ]):
        documents["flight_ticket"] = True

    # Train
    if any(x in text for x in [
        "indian railways",
        "railway",
        "train",
        "irctc",
        "pnr"
    ]):
        documents["train_ticket"] = True

    # Bus
    if any(x in text for x in [
        "bus",
        "redbus",
        "volvo"
    ]):
        documents["bus_ticket"] = True

    # GST
    if any(x in text for x in [
        "gstin",
        "gst no",
        "tax invoice"
    ]):
        documents["gst_invoice"] = True

    # Fuel
    if any(x in text for x in [
        "petrol",
        "diesel",
        "fuel"
    ]):
        documents["fuel_bill"] = True

    return documents
    st.subheader("📂 Documents Detected")

for doc, status in documents.items():

    if status:
        st.success(f"✅ {doc.replace('_',' ').title()}")

    else:
        st.warning(f"❌ {doc.replace('_',' ').title()} Not Found")
        from datetime import datetime
import re

def audit_engine(file_text, gender="Male"):

    audit = {}

    text = file_text.lower()

    # -----------------------
    # Employee
    # -----------------------

    emp = re.search(r"employee\s*name[:\-]?\s*(.*)", file_text, re.IGNORECASE)

    audit["employee"] = emp.group(1).strip() if emp else "Unknown"

    des = re.search(r"designation[:\-]?\s*(.*)", file_text, re.IGNORECASE)

    audit["designation"] = des.group(1).strip() if des else "Unknown"

    # -----------------------
    # Dates
    # -----------------------

    dates = re.findall(r"\d{2}/\d{2}/\d{4}", file_text)

    if len(dates)>=2:

        start = datetime.strptime(dates[0],"%d/%m/%Y")

        end = datetime.strptime(dates[1],"%d/%m/%Y")

        audit["days"]=(end-start).days+1

        audit["nights"]=(end-start).days

    else:

        audit["days"]=0

        audit["nights"]=0

    # -----------------------
    # Time
    # -----------------------

    times=re.findall(r"\d{2}:\d{2}",file_text)

    audit["start_time"]=times[0] if len(times)>0 else "NA"

    audit["end_time"]=times[1] if len(times)>1 else "NA"

    # -----------------------
    # Boarding
    # -----------------------

    if audit["start_time"]!="NA":

        hr=int(audit["start_time"][:2])

        if hr<=10:

            audit["boarding_start"]="100 %"

        elif hr<=13:

            audit["boarding_start"]="70 %"

        else:

            audit["boarding_start"]="40 %"

    if audit["end_time"]!="NA":

        hr=int(audit["end_time"][:2])

        if hr>=19:

            audit["boarding_end"]="100 %"

        elif hr>=12:

            audit["boarding_end"]="70 %"

        else:

            audit["boarding_end"]="40 %"

    # -----------------------
    # Risks
    # -----------------------

    risks=[]

    if "gstin" not in text:

        risks.append("GST Number Missing")

    if "hotel" not in text:

        risks.append("Hotel Bill Missing")

    if "ticket" not in text and "flight" not in text and "train" not in text:

        risks.append("Travel Ticket Missing")

    if "taxi" not in text and "cab" not in text and "auto" not in text:

        risks.append("Conveyance Proof Missing")

    audit["risks"]=risks

    audit["risk_score"]=len(risks)*25

    if audit["risk_score"]>100:

        audit["risk_score"]=100

    return audit
audit = audit_engine(file_text, gender)
st.subheader("🤖 AI Audit")

st.write("Employee :",audit["employee"])

st.write("Designation :",audit["designation"])

st.write("Tour Days :",audit["days"])

st.write("Tour Nights :",audit["nights"])

st.write("Departure :",audit["start_time"])

st.write("Return :",audit["end_time"])

st.write("Risk Score :",audit["risk_score"],"%")

if audit["risk_score"]<25:

    st.success("🟢 LOW RISK")

elif audit["risk_score"]<60:

    st.warning("🟡 MEDIUM RISK")

else:

    st.error("🔴 HIGH RISK")

for r in audit["risks"]:

    st.write("❌",r)
