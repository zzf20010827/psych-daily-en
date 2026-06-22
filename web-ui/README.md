# PsychLit Daily — Web App

Full-featured web interface for automated psychology literature tracking and email push.

## Deploy to Render (free)

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your repo
4. Set:
   - **Build Command:** `pip install -r web-ui/requirements-web.txt`
   - **Start Command:** `cd web-ui && gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
   - **Root Directory:** leave blank (or set to repo root)
5. Deploy

## Deploy to Railway / Fly.io / VPS

Same pattern — install deps from `requirements-web.txt`, run the web service.

## Local Dev

```bash
cd web-ui
pip install -r requirements-web.txt
python app.py
# Open http://localhost:5000
```
