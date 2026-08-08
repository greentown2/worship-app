@echo off
set PYTHON="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist %PYTHON% set PYTHON=python
%PYTHON% -m streamlit run app.py
pause
