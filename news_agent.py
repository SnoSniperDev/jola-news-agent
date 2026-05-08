"""
Jola News Agent — news_agent.py v3
Uses only proven reliable public RSS feeds.
Added debug logging to trace exactly what's happening.
"""

import os, json, time, threading, logging, re
from datetime import datetime
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
GOLD_WORDS = [
    "gold","xau","inflation","cpi","pce","ppi","fed","fomc","powell",
    "interest rate","treasury","yield","dollar","dxy","tariff","china",
    "war","safe haven","bullion","trump","sanction","ukraine","russia",
    "middle east","israel","nato","geopolit","commodity","precious"
]
NASDAQ_WORDS = [
    "nasdaq","ndx","tech","nvidia","amd","microsoft","apple","meta",
    "alphabet","google","amazon","ai","artificial intelligence","chip",
    "semiconductor","earnings","gdp","nfp","unemployment","fed",
    "rate","tariff","trade","trump","retail","consumer","qqq"
]
HIGH_WORDS = [
    "nfp","non-farm","cpi report","fomc","fed rate","powell","gdp",
    "pce","ppi","retail sales","unemployment","rate decision","trump",
    "tariff","emergency","crisis","crash","war","attack","sanction"
]

# ── State ─────────────────────────────────────────────────────────────────────
_lock  = threading.Lock()
_state = {
    "events":       [],
    "news":         [],
    "tweets":       [],
    "alerts":       [],
    "session_risk": "LOW",
    "last_update":  None,
    "debug":        ""
}

def state_get():
    with _lock:
        return json.loads(json.dumps(_state))

def state_update(key, value):
    with _lock:
        _state[key] = value
        _state["last_update"] = datetime.now(UTC).isoformat()

# ── Helpers ───────────────────────────────────────────────────────────────────
def clean_html(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text or '').strip()

def impact_of(text: str) -> str:
    t = text.lower()
    if any(k in t for k in HIGH_WORDS):                        return "HIGH"
    if any(k in t for k in GOLD_WORDS + NASDAQ_WORDS):        return "MEDIUM"
    return "LOW"

def affects(text: str) -> dict:
    t = text.lower()
    return {
        "gold":   any(k in t for k in GOLD_WORDS),
        "nasdaq": any(k in t for k in NASDAQ_WORDS)
    }

def is_relevant(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in GOLD_WORDS + NASDAQ_WORDS)

# ── RSS Feeds ─────────────────────────────────────────────────────────────────
# These are tested public RSS feeds — no auth, no scraping needed
FEEDS = [
    # Tier 1 — highest reliability
    ("https://feeds.reuters.com/reuters/businessNews",        "Reuters"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml",       "BBC Business"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html","CNBC Markets"),
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html", "CNBC Economy"),
    # Tier 2 — financial specific
    ("https://www.federalreserve.gov/feeds/press_all.xml",    "Federal Reserve"),
    ("https://www.forexlive.com/feed/news",                   "ForexLive"),
    ("https://www.fxstreet.com/rss/news",                     "FXStreet"),
    ("https://rss.app/feeds/K8YoRTuRv5xWlhvz.xml",           "Gold News"),
    # Tier 3 — broader market
    ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml",         "WSJ Markets"),
    ("https://rss.cnn.com/rss/money_news_international.rss",  "CNN Money"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*"
}

def fetch_news() -> list:
    log.info("Fetching news feeds...")
    articles = []
    seen     = set()
    feed_stats = []

    for url, source in FEEDS:
        try:
            # Use requests to get the feed then parse with feedparser
            r = requests.get(url, headers=HEADERS, timeout=12)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            count_relevant = 0

            for entry in feed.entries[:25]:
                title   = clean_html(entry.get("title",   "")).strip()
                summary = clean_html(entry.get("summary", "")).strip()
                link    = entry.get("link", "")
                pub     = entry.get("published", "")

                if not title or title in seen: continue
                seen.add(title)

                full = f"{title} {summary}"
                if not is_relevant(full): continue

                count_relevant += 1
                imp = impact_of(full)
                aff = affects(full)

                articles.append({
                    "title":   title,
                    "summary": (summary[:220] + "...") if len(summary) > 220 else summary,
                    "link":    link,
                    "source":  source,
                    "impact":  imp,
                    "affects": aff,
                    "time":    pub
                })

            feed_stats.append(f"{source}:{count_relevant}")
            log.info(f"  {source}: {len(feed.entries)} entries, {count_relevant} relevant")

        except Exception as e:
            log.error(f"  {source} FAILED: {e}")
            feed_stats.append(f"{source}:ERR")

    # Sort: HIGH first, then MEDIUM, then LOW
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    articles.sort(key=lambda x: order.get(x["impact"], 3))

    debug_str = " | ".join(feed_stats)
    state_update("debug", debug_str)
    log.info(f"Total relevant articles: {len(articles)}")
    return articles[:30]

# ── Economic events from FX news feeds ───────────────────────────────────────
EVENT_FEEDS = [
    "https://www.forexlive.com/feed/news",
    "https://www.fxstreet.com/rss/news",
    "https://www.dailyfx.com/feeds/all",
]

def fetch_events() -> list:
    log.info("Fetching economic events...")
    events = []
    seen   = set()

    for url in EVENT_FEEDS:
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            feed = feedparser.parse(r.content)
            for entry in feed.entries[:20]:
                title   = clean_html(entry.get("title", "")).strip()
                summary = clean_html(entry.get("summary", "")).strip()
                pub     = entry.get("published", "")
                full    = f"{title} {summary}"

                if not title or title in seen: continue
                seen.add(title)
                if not is_relevant(full): continue

                imp = impact_of(full)
                if imp == "LOW": continue

                events.append({
                    "date":     datetime.now(UTC).strftime("%Y-%m-%d"),
                    "time":     pub[:16] if pub else "TBD",
                    "title":    title,
                    "currency": "USD",
                    "impact":   imp,
                    "actual":   "",
                    "forecast": "",
                    "previous": "",
                    "affects":  affects(full),
                    "source":   "FX News"
                })
        except Exception as e:
            log.error(f"Event feed {url}: {e}")

    log.info(f"Events found: {len(events)}")
    return events[:15]

# ── Trump tweets ──────────────────────────────────────────────────────────────
TRUMP_ID = "25073877"
TRUMP_KW = [
    "gold","rate","fed","tariff","china","trade","market","stock",
    "nasdaq","economy","inflation","dollar","oil","sanction","nato",
    "ukraine","israel","ai","chip","tech","interest","tax","deal"
]

def fetch_tweets() -> list:
    if not TW_BEARER:
        log.warning("Twitter bearer token not set")
        return []
    try:
        r = requests.get(
            f"https://api.twitter.com/2/users/{TRUMP_ID}/tweets",
            headers={"Authorization": f"Bearer {TW_BEARER}"},
            params={
                "max_results": 10,
                "tweet.fields": "created_at,text",
                "exclude": "retweets,replies"
            },
            timeout=10
        )
        data = r.json()
        if "errors" in data:
            log.error(f"Twitter API error: {data['errors']}")
            return []
        tweets = []
        for tw in data.get("data", []):
            text = tw.get("text", "")
            tl   = text.lower()
            rel  = any(k in tl for k in TRUMP_KW)
            tweets.append({
                "id":     tw.get("id"),
                "text":   text,
                "time":   tw.get("created_at", ""),
                "impact": "HIGH" if rel else "LOW",
                "affects":affects(text),
                "url":    f"https://x.com/realDonaldTrump/status/{tw.get('id')}"
            })
        log.info(f"Tweets: {len(tweets)} fetched")
        return tweets
    except Exception as e:
        log.error(f"Twitter fetch failed: {e}")
        return []

# ── Session risk ──────────────────────────────────────────────────────────────
def session_risk(events, news, tweets) -> str:
    h_events = sum(1 for e in events if e["impact"] == "HIGH")
    h_news   = sum(1 for n in news   if n["impact"] == "HIGH")
    h_tweets = sum(1 for t in tweets if t["impact"] == "HIGH")
    if h_events >= 1 or h_tweets >= 2 or h_news >= 3: return "HIGH"
    if h_news >= 1 or h_tweets >= 1:                  return "MEDIUM"
    return "LOW"

# ── Telegram alerts ───────────────────────────────────────────────────────────
def tg_send(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": msg},
            timeout=10
        )
        log.info("Telegram sent")
    except Exception as e:
        log.error(f"Telegram error: {e}")

_alerted = set()

def check_alerts(news, tweets):
    for item in news:
        if item["impact"] != "HIGH": continue
        key = item["title"][:60]
        if key in _alerted: continue
        _alerted.add(key)
        aff = [k.upper() for k, v in item["affects"].items() if v]
        tg_send(
            f"HIGH IMPACT NEWS\n\n{item['title']}\n\n"
            f"Source: {item['source']}\n"
            f"Affects: {', '.join(aff) or 'GOLD/NASDAQ'}\n\n"
            f"{item.get('summary','')[:200]}\n\nREVIEW BEFORE TRADING"
        )

    for tw in tweets[:5]:
        if tw["impact"] != "HIGH": continue
        tid = str(tw.get("id", ""))
        if not tid or tid in _alerted: continue
        _alerted.add(tid)
        aff = [k.upper() for k, v in tw["affects"].items() if v] or ["GOLD", "NASDAQ"]
        tg_send(
            f"TRUMP TWEET ALERT\n\n{tw['text'][:300]}\n\n"
            f"Affects: {', '.join(aff)}\n\n"
            f"Link: {tw['url']}"
        )

# ── Master update ─────────────────────────────────────────────────────────────
def run_update():
    log.info("========== UPDATE START ==========")
    events = fetch_events()
    news   = fetch_news()
    tweets = fetch_tweets()
    risk   = session_risk(events, news, tweets)

    state_update("events",       events)
    state_update("news",         news)
    state_update("tweets",       tweets)
    state_update("session_risk", risk)

    check_alerts(news, tweets)
    log.info(f"UPDATE DONE — Risk:{risk} Events:{len(events)} News:{len(news)} Tweets:{len(tweets)}")

# ── Scheduler ─────────────────────────────────────────────────────────────────
def start_scheduler():
    run_update()
    schedule.every(10).minutes.do(run_update)
    def _loop():
        while True:
            schedule.run_pending()
            time.sleep(30)
    threading.Thread(target=_loop, daemon=True).start()
    log.info("Scheduler running — every 10 minutes")
