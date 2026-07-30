# =============================================================================
# Arkon Manufacturing AI - Overview Dashboard
# =============================================================================
import streamlit as st

st.set_page_config(page_title="Overview | Arkon", page_icon="📊", layout="wide")

st.title("📊 Factory Overview")
st.markdown("Executive KPI dashboard - all departments at a glance.")

# Placeholder KPI cards - will be populated with real model outputs
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Engines at Risk", "-", help="Engines with RUL < 30 cycles (CMAPSS)")

with col2:
    st.metric("APS Fault Rate", "-", help="Trucks with predicted APS failure (Scania)")

with col3:
    st.metric("Casting Defect Rate", "-", help="Defective castings today (CV model)")

with col4:
    st.metric("Surface Defect Rate", "-", help="Surface defects detected (NEU model)")

st.divider()
st.info("🚧 Connect model outputs to populate KPIs.")
