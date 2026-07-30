# =============================================================================
# Arkon Manufacturing AI - CV Module: NEU Surface Defect (Multi-class)
# =============================================================================
import streamlit as st

st.set_page_config(page_title="CV Surface | Arkon", page_icon="🔬", layout="wide")

st.title("🔬 Surface Defect Classification")
st.caption("Department: Rolling Mill | Dataset: NEU Surface | Task: 6-class defect type")

st.markdown("""
Steel surface images are classified into **6 defect types**:
crazing, inclusion, patches, pitted surface, rolled-in scale, scratches.
""")

st.divider()

uploaded_file = st.file_uploader("Upload a surface image", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, caption="Uploaded image", width=300)
    st.info("🚧 Model not loaded yet - connect models/cv_neu_model.pt")
else:
    st.info("👆 Upload a steel surface image to classify defect type.")

# TODO: Load model, show top-3 predictions with confidence bars
