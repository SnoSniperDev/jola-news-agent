# Jola News Agent

## Deploy to Render.com (free, 24/7)

### Step 1 — Push to GitHub
1. Create a free account at github.com
2. Create a new repository called `jola-news-agent`
3. Upload all files in this folder to that repo

### Step 2 — Deploy on Render
1. Go to render.com and sign up (free)
2. Click "New +" → "Web Service"
3. Connect your GitHub account and select `jola-news-agent`
4. Settings:
   - Name: jola-news-agent
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --preload --timeout 120`
   - Instance Type: Free
5. Click "Advanced" → "Add Environment Variable"
   Add these:
   - TELEGRAM_BOT_TOKEN = your token
   - TELEGRAM_CHAT_ID   = your chat id
   - TWITTER_BEARER_TOKEN = your bearer token
6. Click "Create Web Service"
7. Wait ~2 minutes for deploy
8. Your dashboard URL will be: https://jola-news-agent.onrender.com

### Step 3 — MT5 Integration
- Copy your Render URL
- Open Jola_News_MT5_Panel.mq5 in MetaEditor
- Set NewsAgentURL = your Render URL + "/api/mt5"
- Compile and attach to chart

## API Endpoints
- GET /           — Phone dashboard (open in browser)
- GET /api/mt5    — MT5 panel data (JSON)
- GET /api/all    — Full data dump (JSON)

## What it monitors
- Forex Factory economic calendar (USD events)
- BBC Business, Reuters, Investing.com, Federal Reserve RSS
- Trump/White House tweets via Twitter API
- Filters: Gold and Nasdaq relevant only
- Alerts: 30 min before HIGH impact events + Trump market tweets
