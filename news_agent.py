"""
Jola News Agent — news_agent.py
Scrapes economic calendar, news, and Trump tweets.
Filters for Gold + Nasdaq relevance.
Serves data to web dashboard and MT5 panel.
Sends Telegram alerts 30min before high-impact events.
"""

import os, json, time, threading, logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests, feedparser, schedule
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT    = os.getenv("TELEGRAM_CHAT_ID", "")
TW_BEARER  = os.getenv("TWITTER_BEARER_TOKEN", "")

UTC = ZoneInfo("UTC")

# ── Impact keywords for Gold and Nasdaq ──────────────────────────────────────
GOLD_KEYWORDS = [
    "gold","xau","inflation","cpi","pce","ppi","fed","fomc","powell","rate",
    "interest rate","treasury","yield","dxy","dollar","tariff","china",
    "war","conflict","geopolit","safe haven","precious metal","bullion",
    "trump","white house","sanctions","nato","middle east","israel","ukraine"
]
NASDAQ_KEYWORDS = [
    "nasdaq","ndx","qqq","tech","nvidia","amd","microsoft","apple","meta",
    "alphabet","google","amazon","ai","artificial intelligence","chip","semiconductor",
    "earnings","gdp","nfp","jobs","unemployment","retail sales","consumer",
    "trump","tariff","china","trade war","export","import","fed","rate"
]
HIGH_IMPACT_EVENTS = [
    "nfp","non-farm","cpi","fomc","fed rate","powell","gdp","pce","ppi",
    "retail sales","unemployment","interest rate decision","trump","tariff"
]

# ── Shared state (thread-safe via lock) ─────────────────────────────────────
_lock  = threading.Lock()
_state = {
    "events":    [],   # economic calendar events
    "news":      [],   # filtered news items
    "tweets":    [],   # trump tweets
    "alerts":    [],   # alert log
    "session_risk": "LOW",
    "last_update": None
}

def state_get():
    with _lock:
        return json.loads(json.dumps(_state))

def state_set(key, value):
    with _lock:
        _state[key] = value
        _state["last_update"] = datetime.now(UTC).isoformat()

# ── Telegram ─────────────────────────────────────────────────────────────────
def tg_send(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        log.warning("Telegram not configured")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        encoded = msg.replace("\n", "%0A").replace(" ", "%20").replace(":", "%3A")
        requests.get(f"{url}?chat_id={TG_CHAT}&text={encoded}", timeout=10)
        log.info("Telegram sent")
    except Exception as e:
        log.error(f"Telegram error: {e}")

# ── Impact classification ────────────────────────────────────────────────────
def classify_impact(text: str) -> str:
    t = text.lower()
    for kw in HIGH_IMPACT_EVENTS:
        if kw in t:
            return "HIGH"
    for kw in GOLD_KEYWORDS + NASDAQ_KEYWORDS:
        if kw in t:
            return "MEDIUM"
    return "LOW"

def affects_instruments(text: str) -> dict:
    t = text.lower()
    return {
        "gold":   any(k in t for k in GOLD_KEYWORDS),
        "nasdaq": any(k in t for k in NASDAQ_KEYWORDS)
    }

# ── Forex Factory calendar scraper ───────────────────────────────────────────
def scrape_forex_factory() -> list:
    log.info("Scraping Forex Factory...")
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; JolaBot/1.0)"}
        r = requests.get("https://www.forexfactory.com/calendar", headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        events = []
        rows = soup.select("tr.calendar__row")
        current_date = datetime.now(UTC).strftime("%Y-%m-%d")

        for row in rows[:40]:
            try:
                time_el  = row.select_one(".calendar__time")
                title_el = row.select_one(".calendar__event-title")
                impact_el= row.select_one(".calendar__impact span")
                curr_el  = row.select_one(".calendar__currency")
                actual_el= row.select_one(".calendar__actual")
                fore_el  = row.select_one(".calendar__forecast")
                prev_el  = row.select_one(".calendar__previous")

                if not title_el: continue
                title    = title_el.get_text(strip=True)
                currency = curr_el.get_text(strip=True) if curr_el else ""
                impact_cls = impact_el.get("class", []) if impact_el else []
                raw_impact = "HIGH" if "high" in " ".join(impact_cls).lower() else \
                             "MEDIUM" if "medium" in " ".join(impact_cls).lower() else "LOW"

                # Only USD events affect Gold and Nasdaq
                if currency not in ("USD", ""):
                    continue

                affected = affects_instruments(title)
                if not affected["gold"] and not affected["nasdaq"]:
                    affected["gold"] = True  # USD events default affect gold

                events.append({
                    "date":       current_date,
                    "time":       time_el.get_text(strip=True) if time_el else "All Day",
                    "title":      title,
                    "currency":   currency,
                    "impact":     raw_impact,
                    "actual":     actual_el.get_text(strip=True) if actual_el else "",
                    "forecast":   fore_el.get_text(strip=True) if fore_el else "",
                    "previous":   prev_el.get_text(strip=True) if prev_el else "",
                    "affects":    affected,
                    "source":     "Forex Factory"
                })
            except Exception:
                continue

        log.info(f"FF: {len(events)} events")
        return events
    except Exception as e:
        log.error(f"FF scrape error: {e}")
        return []

# ── Investing.com news RSS ───────────────────────────────────────────────────
RSS_FEEDS = [
    ("https://www.investing.com/rss/news.rss",           "Investing.com"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml",   "BBC Business"),
    ("https://www.federalreserve.gov/feeds/press_all.xml","Federal Reserve"),
    ("https://feeds.reuters.com/reuters/businessNews",    "Reuters Business"),
]

def scrape_news_feeds() -> list:
    log.info("Scraping news feeds...")
    articles = []
    seen = set()

    for url, source in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title   = entry.get("title", "")
                summary = entry.get("summary", "")
                link    = entry.get("link", "")
                full    = f"{title} {summary}".lower()

                if title in seen: continue
                seen.add(title)

                affected = affects_instruments(full)
                if not affected["gold"] and not affected["nasdaq"]:
                    continue

                impact = classify_impact(full)
                pub = entry.get("published", datetime.now(UTC).isoformat())

                articles.append({
                    "title":    title,
                    "summary":  summary[:200] + "..." if len(summary) > 200 else summary,
                    "link":     link,
                    "source":   source,
                    "impact":   impact,
                    "affects":  affected,
                    "time":     pub
                })
        except Exception as e:
            log.error(f"Feed {source} error: {e}")

    articles.sort(key=lambda x: x["impact"] == "HIGH", reverse=True)
    log.info(f"News: {len(articles)} relevant articles")
    return articles[:30]

# ── Trump / White House tweets ───────────────────────────────────────────────
TRUMP_KEYWORDS = [
    "gold","rate","fed","tariff","china","trade","market","stock",
    "nasdaq","economy","inflation","dollar","oil","sanction","nato",
    "ukraine","israel","ai","chip","nvidia","microsoft","tech"
]
TRUMP_USER_ID = "25073877"  # @realDonaldTrump

def fetch_trump_tweets() -> list:
    if not TW_BEARER:
        log.warning("No Twitter bearer token — skipping tweets")
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
            market_relevant = any(k in tl for k in TRUMP_KEYWORDS)
            impact = "HIGH" if market_relevant else "LOW"
            tweets.append({
                "id":       tw.get("id"),
                "text":     text,
                "time":     tw.get("created_at", ""),
                "impact":   impact,
                "affects":  affects_instruments(text),
                "url":      f"https://x.com/realDonaldTrump/status/{tw.get('id')}"
            })

        market_tweets = [t for t in tweets if t["impact"] == "HIGH"]
        log.info(f"Tweets: {len(tweets)} total, {len(market_tweets)} market-relevant")
        return tweets
    except Exception as e:
        log.error(f"Twitter error: {e}")
        return []

# ── Session risk calculator ──────────────────────────────────────────────────
def calculate_session_risk(events: list, tweets: list) -> str:
    high_count = sum(1 for e in events if e.get("impact") == "HIGH")
    recent_tweets = [t for t in tweets if t.get("impact") == "HIGH"]

    if high_count >= 2 or len(recent_tweets) >= 2:
        return "HIGH"
    if high_count == 1 or len(recent_tweets) == 1:
        return "MEDIUM"
    return "LOW"

# ── Proactive alerts ─────────────────────────────────────────────────────────
_alerted_events = set()

def check_and_alert(events: list, tweets: list):
    now = datetime.now(UTC)

    # Alert 30 min before high-impact events
    for ev in events:
        if ev.get("impact") != "HIGH": continue
        eid = f"{ev['date']}_{ev['title']}"
        if eid in _alerted_events: continue

        try:
            t_str = ev.get("time", "")
            if not t_str or t_str in ("All Day", "Tentative", ""):
                continue
            # Parse time like "8:30am"
            ev_time = datetime.strptime(
                f"{ev['date']} {t_str.upper().replace('AM','AM').replace('PM','PM')}",
                "%Y-%m-%d %I:%M%p"
            ).replace(tzinfo=ZoneInfo("America/New_York")).astimezone(UTC)

            diff_min = (ev_time - now).total_seconds() / 60
            if 25 <= diff_min <= 35:
                affects_str = []
                if ev["affects"].get("gold"):   affects_str.append("GOLD")
                if ev["affects"].get("nasdaq"): affects_str.append("NASDAQ")

                msg = (
                    f"NEWS ALERT — 30 MIN WARNING\n\n"
                    f"Event: {ev['title']}\n"
                    f"Time:  {t_str} NY / {ev_time.strftime('%H:%M')} UTC\n"
                    f"Impact: HIGH\n"
                    f"Affects: {', '.join(affects_str)}\n\n"
                    f"Forecast: {ev.get('forecast','N/A')}\n"
                    f"Previous: {ev.get('previous','N/A')}\n\n"
                    f"CONSIDER CLOSING TRADES OR WAITING"
                )
                tg_send(msg)
                _alerted_events.add(eid)
                with _lock:
                    _state["alerts"].insert(0, {
                        "time": now.isoformat(),
                        "type": "event",
                        "msg":  msg[:100]
                    })
        except Exception:
            continue

    # Alert on new market-relevant tweets
    for tw in tweets[:3]:
        if tw.get("impact") != "HIGH": continue
        tid = tw.get("id")
        if not tid or tid in _alerted_events: continue

        affects_str = []
        if tw["affects"].get("gold"):   affects_str.append("GOLD")
        if tw["affects"].get("nasdaq"): affects_str.append("NASDAQ")
        if not affects_str:             affects_str = ["GOLD", "NASDAQ"]

        msg = (
            f"TRUMP TWEET ALERT\n\n"
            f"{tw['text'][:300]}\n\n"
            f"Affects: {', '.join(affects_str)}\n"
            f"Time: {tw['time']}\n\n"
            f"READ BEFORE TRADING: {tw['url']}"
        )
        tg_send(msg)
        _alerted_events.add(tid)
        with _lock:
            _state["alerts"].insert(0, {
                "time": now.isoformat(),
                "type": "tweet",
                "msg":  tw["text"][:100]
            })

# ── Master update cycle ──────────────────────────────────────────────────────
def run_update():
    log.info("Running full update...")
    events = scrape_forex_factory()
    news   = scrape_news_feeds()
    tweets = fetch_trump_tweets()
    risk   = calculate_session_risk(events, tweets)

    state_set("events",       events)
    state_set("news",         news)
    state_set("tweets",       tweets)
    state_set("session_risk", risk)

    check_and_alert(events, tweets)
    log.info(f"Update complete. Risk: {risk} | Events: {len(events)} | News: {len(news)} | Tweets: {len(tweets)}")

# ── Scheduler ────────────────────────────────────────────────────────────────
def start_scheduler():
    run_update()  # immediate first run
    schedule.every(10).minutes.do(run_update)
    schedule.every().hour.at(":00").do(run_update)  # extra sync on the hour

    def loop():
        while True:
            schedule.run_pending()
            time.sleep(30)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    log.info("Scheduler started — updates every 10 minutes")
