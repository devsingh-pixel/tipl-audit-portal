import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime


st.set_page_config(
    page_title="TIPL TE Audit Portal",
    layout="wide"
)


# ---------------- TIPL RULE MASTER ----------------

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


# ---------------- PDF TEXT ----------------

def extract_text(file):

    text = ""

    with pdfplumber.open(file) as pdf:

        for page in pdf.pages:

            page_text = page.extract_text()

            if page_text:
                text += page_text + "\n"

    return text



# ---------------- DESIGNATION ----------------

def get_designation(text):

    for designation in TE_RULES:

        if designation.lower() in text.lower():

            return designation


    return "Executive"



# ---------------- 24 HOUR RULE ----------------

def calculate_days(text):

    pattern = r'(\d{2}/\d{2}/\d{4}\s\d{2}:\d{2}:\d{2}).*?(\d{2}/\d{2}/\d{4}\s\d{2}:\d{2}:\d{2})'


    result = re.search(
        pattern,
        text,
        re.DOTALL
    )


    if result:


        start = datetime.strptime(

            result.group(1),

            "%d/%m/%Y %H:%M:%S"

        )


        end = datetime.strptime(

            result.group(2),

            "%d/%m/%Y %H:%M:%S"

        )


        total_hours = (end-start).total_seconds()/3600


        days = int(total_hours//24)


        if total_hours % 24 > 0:

            days += 1


        return days,total_hours,end



    return 0,0,None




# ---------------- AMOUNT FIND ----------------

def find_amount(text,keyword):

    result = re.search(

        keyword+r".{0,30}?(\d+[,\d]*)",

        text,

        re.IGNORECASE

    )


    if result:

        return int(
            result.group(1).replace(",","")
        )


    return 0




# ---------------- MAIN APP ----------------


st.title("📋 TIPL Travel Expense Audit Portal")


file = st.file_uploader(

    "Upload TE Claim PDF",

    type=["pdf"]

)



if file:


    text = extract_text(file)


    st.success("PDF Uploaded Successfully")



    designation = get_designation(text)



    days,hours,end_time = calculate_days(text)



    rule = TE_RULES[designation]



    ticket = find_amount(text,"ticket")



    # allowance calculation

    boarding_rate = rule["boarding"]

    lodging_rate = rule["lodging"]



    boarding = boarding_rate * days

    lodging = lodging_rate * days




    # 10 AM 30% cut rule

    cut_status = "No Cut"



    if end_time:


        if end_time.hour >= 10:


            boarding = boarding * 0.70

            lodging = lodging * 0.70

            cut_status = "30% Cut Applied"




    total = ticket + boarding + lodging




    col1,col2,col3 = st.columns(3)



    col1.metric(
        "Designation",
        designation
    )


    col2.metric(
        "Eligible Days",
        days
    )


    col3.metric(
        "Travel Hours",
        f"{hours:.2f}"
    )



    st.divider()



    st.subheader("📊 Audit Summary")



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



        "Amount":[

            f"₹ {ticket}",

            f"₹ {lodging:.0f}",

            f"₹ {boarding:.0f}"

        ]

    })



    st.table(summary)




    st.subheader("Rule Check")



    rule_df = pd.DataFrame({

        "Rule":[

            "24 Hour Rule",

            "Designation Limit",

            "10 AM Rule"

        ],


        "Status":[

            "✅ Applied",

            "✅ Applied",

            cut_status

        ]

    })


    st.table(rule_df)



    st.success(
        f"Final Claim Amount : ₹ {total:.0f}"
    )



else:

    st.info("Please upload TE PDF")
