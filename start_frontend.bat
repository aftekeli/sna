@echo off
echo Starting KG-Infused RAG frontend on http://127.0.0.1:3000 ...
cd /d "%~dp0frontend"
npm run start -- --hostname 127.0.0.1 --port 3000
