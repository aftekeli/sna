@echo off
echo Starting KG-Infused RAG frontend (dev mode) on http://127.0.0.1:3000 ...
cd /d "%~dp0frontend"
npm run dev -- --hostname 127.0.0.1 --port 3000
