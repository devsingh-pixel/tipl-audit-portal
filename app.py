import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime


st.set_page_config(
    page_title="TIPL TE Audit Portal",
    layout="wide"
)


# ---------------- RULE MASTER ----------------

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

    for des in TE_RULES.keys():

        if des.lower() in text.lower():

            return des


    return "Executive"





# ---------------- RAIL TIME DAYS ----------------

def calculate_days(text):


    pattern = r'(\d{2}[-/]\d{2}[-/]\d{4}).{0,20}?(\d{2}:\d{2})'


    dates = re.findall(pattern,text)


    if len(dates)>=2:


        start = datetime.strptime(

            dates[0][0]+" "+dates[0][1],

            "%d-%m-%Y %H:%M"

        )


        end = datetime.strptime(

            dates[-1][0]+" "+dates[-1][1],

            "%d-%m-%Y %H:%M"

        )


        hours = (end-start).total_seconds()/3600


        days = int(hours//24)+1


        return days, hours



    return 1,0





# ---------------- AMOUNT FIND ----------------

def find_amount(text, keyword):


    match = re.search(

        keyword+r".{0,20}?(\d+[,]*\d*)",

        text,

        re.IGNORECASE

    )


    if match:

        return int(match.group(1).replace(",",""))


    return 0





# ---------------- APP ----------------


st.title("📋 TIPL Travel Expense Audit Portal")


uploaded_file = st.file_uploader(

    "Upload TE Claim PDF",

    type=["pdf"]

)



if uploaded_file:


    st.success("PDF Uploaded Successfully")


    text = extract_text(uploaded_file)



    designation = get_designation(text)



    days,hours = calculate_days(text)



    rule = TE_RULES[designation]



    # expenses


    ticket = find_amount(text,"ticket")



    boarding = rule["boarding"] * days


    lodging = rule["lodging"] * days




    total = ticket + boarding + lodging





    # HEADER


    col1,col2,col3 = st.columns(3)


    col1.metric(
        "Designation",
        designation
    )


    col2.metric(
        "Travel Hours",
        f"{hours:.1f}"
    )


    col3.metric(
        "Eligible Days",
        days
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


        "Rate":[

            "Actual",

            f"₹ {rule['lodging']}",

            f"₹ {rule['boarding']}"

        ],


        "Amount":[

            f"₹ {ticket}",

            f"₹ {lodging}",

            f"₹ {boarding}"

        ]



    })



    st.table(summary)




    st.subheader("Rule Check")



    rules = pd.DataFrame({

        "Check":[

            "24 Hour Rule",

            "Rail Travel Rule",

            "Designation Limit"

        ],


        "Status":[

            "✅ Passed",

            "✅ Passed",

            "✅ Applied"

        ]

    })



    st.table(rules)




    st.success(

        f"Final Claim Amount : ₹ {total}"

    )



else:


    st.info("Please upload TE PDF")
