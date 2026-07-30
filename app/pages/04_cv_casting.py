# =============================================================================
# Arkon Manufacturing AI - CV Module: Casting Product (Binary)
# =============================================================================
import streamlit as st

st.set_page_config(page_title="CV Casting | Arkon", page_icon="🔍", layout="wide")

st.title("🔍 Casting Defect Detection")
st.caption("Department: Foundry | Dataset: Casting Product | Task: Binary (OK / Defective)")

st.markdown("""
Cast metal parts (pump impellers) are inspected by camera.
The CNN model classifies each part as **OK** or **Defective**.
""")

st.divider()

uploaded_file = st.file_uploader("Upload a casting image", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, caption="Uploaded image", width=300)
    st.info("🚧 Model not loaded yet - connect models/cv_casting_model.pt")
else:
    st.info("👆 Upload an image to run defect detection.")

# TODO: Load model, run inference, show confidence score, Grad-CAM heatmap
