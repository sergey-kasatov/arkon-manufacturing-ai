# =============================================================================
# Arkon Manufacturing AI - CV Module: Anomaly Detection (MVTec AD) [v2.0]
# =============================================================================
import streamlit as st

st.set_page_config(page_title="CV Anomaly | Arkon", page_icon="🚨", layout="wide")

st.title("🚨 Visual Anomaly Detection")
st.caption("Department: Assembly | Dataset: MVTec AD | Task: Unsupervised anomaly detection")

st.markdown("""
Unlike classification, this model is trained **only on normal parts**.
It learns what "normal" looks like - any deviation is flagged as anomaly.
Uses autoencoder-based reconstruction error.
""")

st.divider()
st.warning("🔒 v2.0 module - requires study of autoencoders and anomaly detection.")
st.info("🚧 Placeholder - will be implemented after completing anomaly detection module.")

# TODO: PatchCore or autoencoder model, anomaly score heatmap, threshold slider
