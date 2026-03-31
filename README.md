# NSE/BSE AI Stock Analysis Agent

```bash
# Terminal 1 — Backend
cd ~/stock-agent/backend
source .venv/bin/activate
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd ~/stock-agent/frontend
npm run dev
# Opens at http://localhost:5173
```
