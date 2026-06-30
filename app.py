import streamlit as st
import pandas as pd
import pdfplumber

st.set_page_config(
    page_title="TIPL Audit Portal",
    layout="wide"
)

st.title("TIPL Audit Portal")

st.write("Upload PDF file for audit review")

uploaded_file = st.file_uploader(
    "Upload PDF",
    type=["pdf"]
)

if uploaded_file:

    st.success("PDF uploaded successfully")

    text = ""

    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text

    st.subheader("Extracted Data")

    st.text_area(
        "PDF Content",
        text,
        height=400
    )

    st.subheader("Audit Summary")

    data = {
        "Status": ["Document Read"],
        "Pages Extracted": [len(text)]
    }

    df = pd.DataFrame(data)

    st.table(df)

else:
    st.info("Please upload PDF file to start audit")
