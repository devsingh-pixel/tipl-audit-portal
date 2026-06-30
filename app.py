import streamlit as st
import pandas as pd
import pdfplumber

st.set_page_config(
    page_title="TIPL Audit Portal",
    layout="wide"
)

st.title("TIPL Audit Portal")

uploaded_file = st.file_uploader(
    "Upload Travel PDF",
    type=["pdf"]
)

if uploaded_file:

    st.success("PDF Uploaded Successfully")

    text = ""

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text


    st.subheader("Extracted Travel Details")

    st.text_area(
        "PDF Data",
        text,
        height=300
    )


    # Temporary audit calculation demo

    lodging_rate = 390
    eligible_days = 5

    total_amount = lodging_rate * eligible_days


    st.subheader("Audit Summary")


    audit_data = {

        "Particular": [
            "Lodging Eligible Days",
            "Lodging Rate",
            "Total Lodging Amount",
            "24 Hour Rule",
            "Rail Travel Rule"
        ],

        "Result": [
            f"{eligible_days} Days",
            f"₹ {lodging_rate}",
            f"₹ {total_amount}",
            "Verified",
            "Verified"
        ]
    }


    df = pd.DataFrame(audit_data)

    st.table(df)


else:

    st.info("Please upload PDF file")
