# =============================================================================
# Arkon Manufacturing AI - RAG Chatbot (LLM)
# =============================================================================
import streamlit as st

st.set_page_config(page_title="AI Chatbot | Arkon", page_icon="🤖", layout="wide")

st.title("🤖 Arkon AI Assistant")
st.caption("Ask questions about factory performance, model results, and anomalies.")

st.markdown("""
The assistant uses **RAG (Retrieval-Augmented Generation)** -
it searches through all module results and reports before answering.
""")

st.divider()

# Chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Input
if prompt := st.chat_input("Ask about factory data..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        st.info("🚧 RAG pipeline not connected yet - implement in chatbot.py")

# Example questions
with st.expander("💡 Example questions"):
    st.markdown("""
    - How many engines are predicted to fail within 20 cycles?
    - What is the current APS fault rate in the truck fleet?
    - Show me the most common defect type in the rolling mill today.
    - Which department has the highest defect rate this week?
    """)
