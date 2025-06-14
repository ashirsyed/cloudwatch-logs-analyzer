#!/bin/bash

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Install requirements if needed
pip3 install -r requirements.txt

# Run the Streamlit app
streamlit run src/app.py
