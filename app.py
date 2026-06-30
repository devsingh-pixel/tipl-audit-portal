import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime


st.set_page_config(
    page_title="TIPL TE Audit Portal",
    layout="wide"
)


# ================= RULE MASTER =================

TE_RULES = {

    "Manager": {
        "boarding": 390,
        "lodging": 3000
    },

    "Engineer": {
        "boarding": 390,
        "lodging": 2500
    },

    "Executive": {
        "boarding": 300,
        "lodging": 1500
    }

}


# ================= PDF TEXT =================

def extract_text(file):

    text = ""

    with pdfplumber.open(file) as pdf:

        for page in pdf.pages:

            if page.extract_text():

                text += page.extract_text() + "\n"

    return text



# ================= DESIGNATION =================

def find_designation(text):

    for d in TE_RULES:

        if d.lower() in text.lower():

            return d


    return "Executive"




# ================= DATE CALCULATION =================

def get_days(text):

    pattern = r'(\d{2}/\d{2}/\d{4}\s\d{2}:\d{2}:\d{2}).*?(\d{2}/\d{2}/\d{4}\s\d{2}:\d{2}:\d{2})'


    data = re.search(
        pattern,
        text,
        re.DOTALL
    )


    if data:


        start = datetime.strptime(

            data.group(1),

            "%d/%m/%Y %H:%M:%S"

        )


        end = datetime.strptime(

            data.group(2),

            "%d/%m/%Y %H:%M:%S"

        )


        hours = (end-start).total_seconds()/3600


        days = int(hours/24)


        if hours % 24:

            days += 1


        return days,end



    return 0,None





# ================= AMOUNT FIND =================

def get_amount(text,word):


    result = re.search(

        word+r".{0,40}?(\d+[,\d]*)",

        text,

        re.I

    )


    if result:

        return int(
            result.group(1).replace(",","")
        )


    return 0





# ================= MAIN =================


st.title("📋 TIPL TE Audit Portal")


file = st.file_uploader(

    "Upload TE Claim PDF",

    type="pdf"

)



if file:


    text = extract_text(file)



    designation = find_designation(text)



    days,end_time = get_days(text)



    rules = TE_RULES[designation]



    # CLAIMED AMOUNT

    ticket_claim = get_amount(
        text,
        "ticket"
    )


    lodging_claim = get_amount(
        text,
        "lodging"
    )


    boarding_claim = get_amount(
        text,
        "boarding"
    )




    # ALLOWED AMOUNT


    allowed_lodging = rules["lodging"] * days


    allowed_boarding = rules["boarding"] * days




    # 10 AM CUT RULE

    if end_time and end_time.hour >= 10:


        allowed_boarding *= 0.70

        allowed_lodging *= 0.70




    summary = pd.DataFrame({

        "Expense Head":[

            "Travel Ticket",

            "Lodging",

            "Boarding"

        ],


        "Days":[

            "-",

            days,

            days

        ],


        "Claimed Amount":[

            ticket_claim,

            lodging_claim,

            boarding_claim

        ],


        "Allowed Amount":[

            ticket_claim,

            int(allowed_lodging),

            int(allowed_boarding)

        ]

    })



    summary["Status"] = summary.apply(

        lambda x:

        "PASS"

        if x["Claimed Amount"] <= x["Allowed Amount"]

        else "EXCESS",

        axis=1

    )




    st.subheader("📊 Audit Summary")


    st.write(
        f"Designation : {designation}"
    )


    st.write(
        f"Eligible Days : {days}"
    )


    st.table(summary)



    total_claim = summary["Claimed Amount"].sum()

    total_allowed = summary["Allowed Amount"].sum()



    st.metric(
        "Total Claim",
        f"₹ {total_claim}"
    )


    st.metric(
        "Allowed",
        f"₹ {total_allowed}"
    )



    if total_claim <= total_allowed:

        st.success("FINAL AUDIT : PASS")

    else:

        st.error("FINAL AUDIT : NEED REVIEW")



else:

    st.info("Upload TE Claim PDF")
