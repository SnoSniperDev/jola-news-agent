"""
Jola News Agent — news_agent.py  (v2 — reliable sources)
Uses RSS feeds that don't block scrapers.
Forex Factory replaced with investing.com RSS + marketwatch + reuters.
"""

import os, json, time, threading, logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests, feedparser, schedule
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TG_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT   = os.getenv("TELEGRAM_CHAT_ID", "")
TW_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")

UTC = ZoneInfo("UTC")

# ── Keywords ──────────────────────────────────────────────────────────────────
GOLD_KEYWORDS = [
    "gold","xau","inflation","cpi","pce","ppi","fed","fomc","powell",
    "interest rate","treasury","yield","dollar","dxy","tariff","china",
    "war","conflict","safe haven","precious","bullion","trump","sanction",
    "nato","middle east","israel","ukraine","russia","geopolit"
]
NASDAQ_KEYWORDS = [
    "nasdaq","ndx","qqq","tech","nvidia","amd","microsoft","apple","meta",
    "alphabet","google","amazon","ai","artificial intelligence","chip",
    "semiconductor","earnings","gdp","nfp","jobs","unemployment","fed",
    "rate","tariff","china","trade","trump","retail sales","consumer"
]
HIGH_IMPACT = [
    "nfp","non-farm payroll","cpi","fomc","fed rate","powell","gdp","pce",
    "ppi","retail sales","unemployment","interest rate decision","trump",
    "tariff","emergency","crisis","crash","collapse","war","attack"
]

# ── Shared state ──────────────────────────────────────────────────────────────
_lock  = threading.Lock()
_state = {
    "events":       [],
    "news":         [],
    "tweets":       [],
    "alerts":       [],
    "session_risk": "LOW",
    "last_update":  None
}

def state_get():
    with _lock:
        return json.loads(json.dumps(_state))

def state_set(key, value):
    with _lock:
        _state[key] = value
        _state["last_update"] = datetime.now(UTC).isoformat()

# ── Telegram ──────────────────────────────────────────────────────────────────
def tg_send(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        log.warning("Telegram not configured")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TG_CHAT, "text": msg}, timeout=10)
        log.info("Telegram sent")
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ── Helpers ───────────────────────────────────────────────────────────────────
def classify_impact(text: str) -> str:
    t = text.lower()
    if any(k in t for k in HIGH_IMPACT):   return "HIGH"
    if any(k in t for k in GOLD_KEYWORDS + NASDAQ_KEYWORDS): return "MEDIUM"
    return "LOW"

def affects_instruments(text: str) -> dict:
    t = text.lower()
    return {
        "gold":   any(k in t for k in GOLD_KEYWORDS),
        "nasdaq": any(k in t for k in NASDAQ_KEYWORDS)
    }

# ── RSS News feeds (reliable, no scraping needed) ─────────────────────────────
RSS_FEEDS = [
    ("https://feeds.reuters.com/reuters/businessNews",         "Reuters Business"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml",        "BBC Business"),
    ("https://www.federalreserve.gov/feeds/press_all.xml",     "Federal Reserve"),
    ("https://feeds.marketwatch.com/marketwatch/topstories",   "MarketWatch"),
    ("https://rss.cnn.com/rss/money_news_international.rss",   "CNN Money"),
    ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml",          "Wall Street Journal"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html",  "CNBC Markets"),
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html",   "CNBC Economy"),
]

def scrape_news_feeds() -> list:
    log.info("Fetching news RSS feeds...")
    articles = []
    seen = set()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JolaNewsBot/1.0)"}

    for url, source in RSS_FEEDS:
        try:
            feed = feedparser.parse(url, request_headers=headers)
            for entry in feed.entries[:20]:
                title   = entry.get("title", "").strip()
                summary = entry.get("summary", "").strip()
                link    = entry.get("link", "")
                pub     = entry.get("published", datetime.now(UTC).isoformat())
                full    = f"{title} {summary}"

                if not title or title in seen: continue
                seen.add(title)

                affected = affects_instruments(full)
                if not affected["gold"] and not affected["nasdaq"]:
                    continue

                impact = classify_impact(full)
                # Clean summary
                clean_summary = summary[:200] + "..." if len(summary) > 200 else summary

                articles.append({
                    "title":   title,
                    "summary": clean_summary,
                    "link":    link,
                    "source":  source,
                    "impact":  impact,
                    "affects": affected,
                    "time":    pub
                })
        except Exception as e:
            log.error(f"Feed error {source}: {e}")
            continue

    # Sort by impact then recency
    impact_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    articles.sort(key=lambda x: impact_order.get(x["impact"], 3))
    log.info(f"News: {len(articles)} relevant articles found")
    return articles[:30]

# ── Economic calendar via Investing.com RSS ───────────────────────────────────
CALENDAR_FEEDS = [
    "https://www.forexlive.com/feed/news",
    "https://www.fxstreet.com/rss/news",
    "https://www.dailyfx.com/feeds/all",
]

def scrape_economic_calendar() -> list:
    log.info("Fetching economic calendar...")
    events = []
    seen = set()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; JolaNewsBot/1.0)"}

    for url in CALENDAR_FEEDS:
        try:
            feed = feedparser.parse(url, request_headers=headers)
            for entry in feed.entries[:15]:
                title   = entry.get("title", "").strip()
                summary = entry.get("summary", "").strip()
                pub     = entry.get("published", "")
                full    = f"{title} {summary}"

                if not title or title in seen: continue
                seen.add(title)

                affected = affects_instruments(full)
                if not affected["gold"] and not affected["nasdaq"]:
                    continue

                impact = classify_impact(full)
                if impact == "LOW": continue  # Calendar only shows medium/high

                events.append({
                    "date":     datetime.now(UTC).strftime("%Y-%m-%d"),
                    "time":     pub[:16] if pub else "TBD",
                    "title":    title,
                    "currency": "USD",
                    "impact":   impact,
                    "actual":   "",
                    "forecast": "",
                    "previous": "",
                    "affects":  affected,
                    "source":   "FX Calendar"
                })
        except Exception as e:
            log.error(f"Calendar feed error: {e}")

    log.info(f"Calendar: {len(events)} events")
    return events[:20]

# ── Twitter / Trump tweets ────────────────────────────────────────────────────
TRUMP_USER_ID = "25073877"
TRUMP_KEYWORDS = [
    "gold","rate","fed","tariff","china","trade","market","stock",
    "nasdaq","economy","inflation","dollar","oil","sanction","nato",
    "ukraine","israel","ai","chip","nvidia","tech","interest"
]

def fetch_trump_tweets() -> list:
    if not TW_BEARER:
        log.warning("No Twitter bearer token")
        return []
    log.info("Fetching Trump tweets...")
    try:
        headers = {"Authorization": f"Bearer {TW_BEARER}"}
        url = f"https://api.twitter.com/2/users/{TRUMP_USER_ID}/tweets"
        params = {
            "max_results": 10,
            "tweet.fields": "created_at,text",
            "exclude": "retweets,replies"
        }
        r = requests.get(url, headers=headers, params=params, timeout=10)
        data = r.json()
        tweets = []
        for tw in data.get("data", []):
            text = tw.get("text", "")
            tl   = text.lower()
            relevant = any(k in tl for k in TRUMP_KEYWORDS)
            tweets.append({
                "id":      tw.get("id"),
                "text":    text,
                "time":    tw.get("created_at", ""),
                "impact":  "HIGH" if relevant else "LOW",
                "affects": affects_instruments(text),
                "url":     f"https://x.com/realDonaldTrump/status/{tw.get('id')}"
            })
        log.info(f"Tweets: {len(tweets)} fetched")
        return tweets
    except Exception as e:
        log.error(f"Twitter error: {e}")
        return []

# ── Session risk ──────────────────────────────────────────────────────────────
def calculate_session_risk(events: list, news: list, tweets: list) -> str:
    high_events  = sum(1 for e in events if e.get("impact") == "HIGH")
    high_news    = sum(1 for n in news   if n.get("impact") == "HIGH")
    high_tweets  = sum(1 for t in tweets if t.get("impact") == "HIGH")

    if high_events >= 1 or high_tweets >= 2 or high_news >= 3:
        return "HIGH"
    if high_news >= 1 or high_tweets >= 1:
        return "MEDIUM"
    return "LOW"

# ── Proactive alerts ──────────────────────────────────────────────────────────
_alerted = set()

def check_and_alert(events: list, news: list, tweets: list):
    # High impact news alert
    for item in news:
        if item.get("impact") != "HIGH": continue
        key = item["title"][:50]
        if key in _alerted: continue
        _alerted.add(key)

        affects_str = []
        if item["affects"].get("gold"):   affects_str.append("GOLD")
        if item["affects"].get("nasdaq"): affects_str.append("NASDAQ")

        msg = (
            f"HIGH IMPACT NEWS\n\n"
            f"{item['title']}\n\n"
            f"Source: {item['source']}\n"
            f"Affects: {', '.join(affects_str)}\n\n"
            f"{item.get('summary','')[:200]}\n\n"
            f"REVIEW BEFORE TRADING"
        )
        tg_send(msg)
        with _lock:
            _state["alerts"].insert(0, {
                "time": datetime.now(UTC).isoformat(),
                "type": "news",
                "msg":  item["title"][:100]
            })

    # Trump tweet alerts
    for tw in tweets[:5]:
        if tw.get("impact") != "HIGH": continue
        tid = str(tw.get("id", ""))
        if not tid or tid in _alerted: continue
        _alerted.add(tid)

        affects_str = []
        if tw["affects"].get("gold"):   affects_str.append("GOLD")
        if tw["affects"].get("nasdaq"): affects_str.append("NASDAQ")
        if not affects_str: affects_str = ["GOLD", "NASDAQ"]

        msg = (
            f"TRUMP TWEET — MARKET ALERT\n\n"
            f"{tw['text'][:300]}\n\n"
            f"Affects: {', '.join(affects_str)}\n\n"
            f"READ BEFORE TRADING: {tw['url']}"
        )
        tg_send(msg)
        with _lock:
            _state["alerts"].insert(0, {
                "time": datetime.now(UTC).isoformat(),
                "type": "tweet",
                "msg":  tw["text"][:100]
            })

# ── Master update ─────────────────────────────────────────────────────────────
def run_update():
    log.info("=== Running update ===")
    events = scrape_economic_calendar()
    news   = scrape_news_feeds()
    tweets = fetch_trump_tweets()
    risk   = calculate_session_risk(events, news, tweets)

    state_set("events",       events)
    state_set("news",         news)
    state_set("tweets",       tweets)
    state_set("session_risk", risk)

    check_and_alert(events, news, tweets)
    log.info(f"Done. Risk={risk} Events={len(events)} News={len(news)} Tweets={len(tweets)}")

# ── Scheduler ─────────────────────────────────────────────────────────────────
def start_scheduler():
    run_update()
    schedule.every(10).minutes.do(run_update)

    def loop():
        while True:
            schedule.run_pending()
            time.sleep(30)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    log.info("Scheduler started — updating every 10 minutes")
