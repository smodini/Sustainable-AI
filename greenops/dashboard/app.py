import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from app.db.database import SessionLocal
from app.db.crud import get_findings, get_scan_history

st.set_page_config(
    page_title="GreenOps Dashboard",
    page_icon="🌿",
    layout="wide",
)

st.title("🌿 GreenOps — Multi-Cloud Energy Waste Platform")
st.caption("Detect idle cloud resources and calculate carbon waste")

db = SessionLocal()

# ── Scan history ─────────────────────────────────────────────────────────────
scans = get_scan_history(db)
findings = get_findings(db)

# ── Top metrics ──────────────────────────────────────────────────────────────
total_vms = sum(s.total_vms for s in scans[-1:]) if scans else 0
idle_vms = sum(s.idle_vms for s in scans[-1:]) if scans else 0
total_waste = sum(s.total_waste_kwh for s in scans[-1:]) if scans else 0.0
total_scans = len(scans)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Scans Run", total_scans)
col2.metric("Total VMs (last scan)", total_vms)
col3.metric("Idle VMs (last scan)", idle_vms)
col4.metric("Energy Waste (last scan)", f"{total_waste:.1f} kWh/month")

st.divider()

# ── Filters ───────────────────────────────────────────────────────────────────
st.subheader("Resource Findings")

col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    filter_provider = st.selectbox("Provider", ["All", "AWS", "Azure", "GCP"])
with col_f2:
    filter_idle = st.selectbox("Status", ["All", "Idle Only", "Active Only"])
with col_f3:
    filter_risk = st.selectbox("Risk", ["All", "LOW", "MEDIUM", "HIGH", "CRITICAL"])

# ── Build dataframe ───────────────────────────────────────────────────────────
if findings:
    df = pd.DataFrame([{
        "Resource ID": f.resource_id,
        "Name": f.name,
        "Provider": f.provider,
        "Region": f.region,
        "Type": f.instance_type,
        "CPU Max %": f.cpu_maximum,
        "Network MB/day": f.network_mb_day,
        "Idle": "✅ Yes" if f.idle else "❌ No",
        "Energy Waste kWh": f.energy_waste_kwh,
        "Risk": f.risk,
        "Detected At": f.detected_at,
    } for f in findings])

    if filter_provider != "All":
        df = df[df["Provider"] == filter_provider]
    if filter_idle == "Idle Only":
        df = df[df["Idle"] == "✅ Yes"]
    elif filter_idle == "Active Only":
        df = df[df["Idle"] == "❌ No"]
    if filter_risk != "All":
        df = df[df["Risk"] == filter_risk]

    st.dataframe(df, use_container_width=True)

    # ── Energy waste by provider ──────────────────────────────────────────────
    st.divider()
    st.subheader("Energy Waste by Provider")
    waste_by_provider = df.groupby("Provider")["Energy Waste kWh"].sum().reset_index()
    if not waste_by_provider.empty:
        st.bar_chart(waste_by_provider.set_index("Provider"))

else:
    st.info("No findings yet. Run a scan first: GET /api/v1/aws/scan")

st.divider()

# ── Scan history table ────────────────────────────────────────────────────────
st.subheader("Scan History")
if scans:
    scan_df = pd.DataFrame([{
        "Scan ID": s.id,
        "Provider": s.provider,
        "Total VMs": s.total_vms,
        "Idle VMs": s.idle_vms,
        "Waste kWh": s.total_waste_kwh,
        "Scanned At": s.scanned_at,
    } for s in scans])
    st.dataframe(scan_df, use_container_width=True)
else:
    st.info("No scans recorded yet.")

db.close()
