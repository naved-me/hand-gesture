import streamlit as st
import subprocess
import os
import sys

# Set up page configuration
st.set_page_config(
    page_title="Hand Gesture OS Controller",
    page_icon="🖐️",
    layout="centered"
)

st.title("🖐️ Hand Gesture OS Controller")
st.markdown("Use this dashboard to launch and manage the Hand Gesture OS Controller.")

# Initialize session state to keep track of the background process
if 'process' not in st.session_state:
    st.session_state.process = None

def start_controller():
    if st.session_state.process is None or st.session_state.process.poll() is not None:
        # Launch main.py using the current Python executable
        st.session_state.process = subprocess.Popen([sys.executable, "main.py"], cwd=os.getcwd())
    else:
        st.warning("Controller is already running!")

def stop_controller():
    if st.session_state.process is not None and st.session_state.process.poll() is None:
        st.session_state.process.terminate()
        st.session_state.process.wait()
        st.session_state.process = None
    else:
        st.info("Controller is not running.")

# Create a clean UI with two columns for buttons
col1, col2 = st.columns(2)

with col1:
    st.button("🚀 Launch Controller", on_click=start_controller, use_container_width=True, type="primary")
    
with col2:
    st.button("🛑 Stop Controller", on_click=stop_controller, use_container_width=True)

# Display status
if st.session_state.process is not None and st.session_state.process.poll() is None:
    st.success("🟢 Controller is currently RUNNING.")
else:
    st.error("🔴 Controller is STOPPED.")

st.divider()

# Load and display learn.md documentation
st.subheader("📖 Project Documentation")
try:
    with open("learn.md", "r", encoding="utf-8") as f:
        st.markdown(f.read())
except FileNotFoundError:
    st.info("Documentation (learn.md) could not be found.")
