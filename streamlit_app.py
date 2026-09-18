"""Streamlit Cloud entry point (some apps are configured as streamlit_app.py)."""

from pathlib import Path
import os

_here = Path(__file__).resolve().parent
_mount = Path("/mount/src")
if (_mount / "app.py").is_file():
    os.chdir(_mount)
else:
    os.chdir(_here)

from app import main

main()
