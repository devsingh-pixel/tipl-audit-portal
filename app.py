import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="TIPL Audit Portal",
    layout="wide"
)

st.title("TIPL Audit Portal")


st.subheader("Audit Summary")

lodging_rate = 390
days = 5

total_lodging = lodging_rate * days


audit_data = {
    "Particular": [
        "Lodging Eligible Days",
        "Lodging Rate Per Day",
        "Total Lodging Amount",
        "24 Hour Rule Check",
        "Rail Travel Rule"
    ],

    "Result": [
        f"{days} Days",
        f"₹ {lodging_rate}",
        f"₹ {total_lodging}",
        "Checked",
        "Checked as per travel time"
    ]
}


df = pd.DataFrame(audit_data)

st.table(df)
