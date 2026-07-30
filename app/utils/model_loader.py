# =============================================================================
# Arkon Manufacturing AI - Model Loader Utility
# Centralised model loading with caching
# =============================================================================
import streamlit as st


@st.cache_resource
def load_cv_casting_model(model_path: str):
    """Load Casting Product CNN model (binary classification)."""
    # import torch
    # model = torch.load(model_path, map_location="cpu")
    # model.eval()
    # return model
    raise NotImplementedError("Connect model path in models/cv_casting_model.pt")


@st.cache_resource
def load_cv_neu_model(model_path: str):
    """Load NEU Surface Defect model (6-class classification)."""
    raise NotImplementedError("Connect model path in models/cv_neu_model.pt")


@st.cache_resource
def load_timeseries_model(model_path: str):
    """Load CMAPSS RUL prediction model."""
    raise NotImplementedError("Connect model path in models/timeseries_model.pkl")


@st.cache_resource
def load_scania_model(model_path: str):
    """Load Scania APS XGBoost model."""
    # import joblib
    # return joblib.load(model_path)
    raise NotImplementedError("Connect model path in models/scania_model.pkl")
