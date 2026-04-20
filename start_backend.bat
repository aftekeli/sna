@echo off
echo Starting KG-Infused RAG backend on http://127.0.0.1:8000 ...
cd /d "%~dp0"
uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 8000
