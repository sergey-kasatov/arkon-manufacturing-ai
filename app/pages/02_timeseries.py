# =============================================================================
# Arkon Manufacturing AI - Time Series Module (NASA CMAPSS)
# =============================================================================
import streamlit as st

st.set_page_config(page_title="Time Series | Arkon", page_icon="⏱️", layout="wide")

st.title("⏱️ Engine RUL Prediction")
st.caption("Department: Engine Testing | Dataset: NASA CMAPSS | Task: Remaining Useful Life")

st.markdown("""
Turbofan engines are monitored across operational cycles. The model predicts
**Remaining Useful Life (RUL)** - how many cycles remain before failure.
""")

st.divider()
st.info("🚧 Module under construction - connect notebooks/models/timeseries.py")

# TODO: Add engine selector, RUL prediction chart, degradation plot
