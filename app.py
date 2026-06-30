import streamlit as st
import pandas as pd
import pdfplumber
import re


st.set_page_config(
    page_title="TIPL TE Audit Portal",
    layout="wide"
)


st.title("📋 TIPL TE Audit Portal")


# ---------- PDF TEXT EXTRACTION ----------

def extract_text(file):

    text = ""

    with pdfplumber.open(file) as pdf:

        for page in pdf.pages:

            page_text = page.extract_text()

            if page_text:

                text += page_text + "\n"

    return text



# ---------- FIND TOUR DETAILS ----------

def find_days(text):

    match = re.search(
        r'Days\s+(\d+)',
        text,
        re.IGNORECASE
    )

    if match:

        return int(match.group(1))

    return 0



def find_designation(text):

    match = re.search(
        r'Designation:\s*(.*)',
        text,
        re.IGNORECASE
    )

    if match:

        return match.group(1).strip()

    return "Not Found"



# ---------- JV DETAIL READING ----------

def expense_amount(text):


    data = []


    pattern = r'\d+\s+\d+\s+([A-Za-z()]+).*?(\d+\.\d+)'

    rows = re.findall(
        pattern,
        text,
        re.DOTALL
    )


    for name,amount in rows:


        if name.lower() in [
            "conveyance",
            "lodging",
            "boarding"
        ]:


            data.append({

                "Expense Head": name,

                "Amount": float(amount)

            })


    return data





# ---------- APP ----------


file = st.file_uploader(
    "Upload TE PDF",
    type=["pdf"]
)



if file:


    text = extract_text(file)



    designation = find_designation(text)

    days = find_days(text)



    st.success("PDF Read Successfully")



    col1,col2 = st.columns(2)


    col1.metric(
        "Designation",
        designation
    )


    col2.metric(
        "Tour Days",
        days
    )



    expenses = expense_amount(text)



    if expenses:


        df = pd.DataFrame(expenses)



        df["Days"] = df.apply(

            lambda x: days
            if x["Expense Head"].lower()
            in ["lodging","boarding"]
            else "-",

            axis=1

        )



        df["Status"] = "Checked"



        st.subheader("📊 Audit Summary")


        st.table(

            df[
            [
            "Expense Head",
            "Days",
            "Amount",
            "Status"
            ]
            ]

        )



        total = df["Amount"].sum()



        st.success(
            f"Total Claim Amount : ₹ {total:.0f}"
        )



    else:


        st.warning(
            "JV Detail not detected"
        )



else:


    st.info(
        "Please upload TE PDF"
    )
