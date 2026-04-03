@echo off
title Stock Agent Backend
wsl bash -c "cd '/mnt/c/Users/TALLURI SAI ADITYA/OneDrive/Desktop/Projects/Trading Agent/stock-agent/backend' && source .venv/bin/activate && python -m uvicorn main:app --host 0.0.0.0 --port 8000"
pause
