import streamlit as st
import requests

# Configuration
API_URL = "http://localhost:8000/process"

st.set_page_config(page_title="Maya AI Interface", page_icon="🤖")

st.title("🤖 Maya Smart Home Assistant")
st.markdown("---")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("Message Maya..."):
    # Display user message
    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    try:
        # Prepare the form data for FastAPI
        # Note: We send return_audio=False for the text UI
        payload = {"text_input": prompt, "return_audio": "false"}
        
        with st.spinner("Maya is thinking..."):
            response = requests.post(API_URL, data=payload)
            
        if response.status_code == 200:
            data = response.json()
            maya_response = data.get("response", "I'm sorry, I couldn't process that.")
            
            # Display Maya's response
            with st.chat_message("assistant"):
                st.markdown(maya_response)
            
            st.session_state.messages.append(
                {"role": "assistant", "content": maya_response}
            )
        else:
            st.error(f"Error: {response.status_code} - {response.text}")

    except Exception as e:
        st.error(f"Failed to connect to backend: {e}")

# Sidebar for additional info
with st.sidebar:
    st.header("Settings")
    st.info("Maya is currently connected to your Govee Smart Lights.")
    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.rerun()