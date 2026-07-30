# =============================================================================
# Arkon Manufacturing AI - Main Streamlit App
# =============================================================================
import streamlit as st

st.set_page_config(
    page_title="Arkon Manufacturing AI",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏭 Arkon Manufacturing AI Platform")
st.markdown("""
Welcome to the **Arkon Manufacturing AI** - an integrated AI quality control
platform combining Predictive Maintenance, Fault Detection, and Visual Quality
Control across all factory departments.

---

### Modules

| Module | Department | Dataset | Task |
|--------|-----------|---------|------|
| ⏱️ Time Series | Engine Testing | NASA CMAPSS | RUL Prediction |
| 🔧 ML Classification | Truck Fleet | Scania APS | Fault Detection |
| 🔍 CV - Casting | Foundry | Casting Product | Defect Detection (binary) |
| 🔍 CV - Surface | Rolling Mill | NEU Surface | Defect Type (6 classes) |
| 🤖 AI Chatbot | All Departments | RAG | Natural Language Queries |

---

Use the **sidebar** to navigate between modules.
""")

st.info("👈 Select a module from the sidebar to get started.")
