st.subheader("Audit Summary")

# Example audit calculation

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
