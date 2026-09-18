"""Streamlit Cloud entry point (some apps are configured as streamlit_app.py)."""

from pathlib import Path
import os

os.chdir(Path(__file__).resolve().parent)

from app import main

main()
