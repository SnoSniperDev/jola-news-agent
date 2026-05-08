"""
Jola News Agent — app.py
Flask web server — serves dashboard + MT5 API endpoints
"""

from flask import Flask, jsonify, render_template_string
from news_agent import start_scheduler, state_get
import os

app = Flask(__name__)

# ── MT5 JSON endpoint (indicator polls this) ─────────────────────────────────
@app.route("/api/mt5")
def mt5_api():
    s = state_get()
    high_events = [e for e in s["events"] if e.get("impact") == "HIGH"]
    next_event  = high_events[0] if high_events else None
    return jsonify({
        "session_risk": s["session_risk"],
        "next_event": next_event,
        "high_event_count": len(high_events),
        "tweet_alert": len([t for t in s["tweets"] if t.get("impact") == "HIGH"]) > 0,
        "last_update": s["last_update"]
    })

# ── Full state endpoint ───────────────────────────────────────────────────────
@app.route("/api/all")
def api_all():
    return jsonify(state_get())

# ── Phone web dashboard ───────────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jola News Agent</title>
<style>
:root{--bg:#0d0d0d;--card:#161616;--border:#2a2a2a;--text:#e8e8e8;--muted:#888;
--high:#ff4d4d;--med:#f0a500;--low:#3fb950;--gold:#ffd700;--nasdaq:#58a6ff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,sans-serif;
font-size:14px;padding:12px;max-width:480px;margin:0 auto}
h1{font-size:16px;font-weight:600;margin-bottom:4px}
.sub{color:var(--muted);font-size:12px;margin-bottom:16px}
.risk-bar{padding:10px 14px;border-radius:10px;margin-bottom:16px;font-weight:600;font-size:15px;text-align:center}
.risk-HIGH{background:#2d0a0a;border:1px solid var(--high);color:var(--high)}
.risk-MEDIUM{background:#2d1f00;border:1px solid var(--med);color:var(--med)}
.risk-LOW{background:#0a2d14;border:1px solid var(--low);color:var(--low)}
.section{margin-bottom:20px}
.section-title{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;
letter-spacing:.08em;margin-bottom:8px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;
padding:12px;margin-bottom:8px}
.card-title{font-size:13px;font-weight:500;margin-bottom:4px}
.card-meta{font-size:11px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap}
.badge{display:inline-block;font-size:10px;font-weight:600;padding:2px 6px;
border-radius:4px;margin-left:6px}
.HIGH{background:#3d0a0a;color:var(--high);border:1px solid var(--high)}
.MEDIUM{background:#2d1f00;color:var(--med);border:1px solid var(--med)}
.LOW{background:#0a1f0a;color:var(--low);border:1px solid var(--low)}
.pill{display:inline-block;font-size:10px;padding:2px 6px;border-radius:4px;margin-right:4px}
.pill-gold{background:#2d2500;color:var(--gold);border:1px solid #4d3f00}
.pill-nasdaq{background:#0a1a2d;color:var(--nasdaq);border:1px solid #0d2d4d}
.tweet-text{font-size:12px;line-height:1.5;margin-bottom:6px;color:var(--text)}
.tweet-link{font-size:11px;color:var(--nasdaq)}
.update-time{font-size:10px;color:var(--muted);text-align:center;margin-top:16px}
.no-data{color:var(--muted);font-size:12px;padding:8px 0}
.forecast-row{display:flex;gap:16px;font-size:11px;color:var(--muted);margin-top:4px}
.forecast-row span b{color:var(--text)}
</style>
</head>
<body>
<h1>Jola News Agent</h1>
<div class="sub" id="update-time">Loading...</div>

<div id="risk-bar" class="risk-bar risk-LOW">Session Risk: LOW</div>

<div class="section">
  <div class="section-title">High Impact Events Today</div>
  <div id="events-list"><div class="no-data">Loading events...</div></div>
</div>

<div class="section">
  <div class="section-title">Trump / White House</div>
  <div id="tweets-list"><div class="no-data">Loading tweets...</div></div>
</div>

<div class="section">
  <div class="section-title">Latest Market News</div>
  <div id="news-list"><div class="no-data">Loading news...</div></div>
</div>

<div class="update-time" id="footer">Auto-refreshes every 60 seconds</div>

<script>
function badge(impact){return `<span class="badge ${impact}">${impact}</span>`}
function pills(affects){
  let p='';
  if(affects&&affects.gold)   p+=`<span class="pill pill-gold">GOLD</span>`;
  if(affects&&affects.nasdaq) p+=`<span class="pill pill-nasdaq">NASDAQ</span>`;
  return p;
}

async function load(){
  try{
    const r = await fetch('/api/all');
    const d = await r.json();

    // Risk bar
    const rb = document.getElementById('risk-bar');
    rb.className = `risk-bar risk-${d.session_risk}`;
    rb.textContent = `Session Risk: ${d.session_risk}`;

    // Update time
    if(d.last_update){
      const dt = new Date(d.last_update);
      document.getElementById('update-time').textContent =
        'Last updated: '+dt.toLocaleTimeString();
    }

    // Events
    const el = document.getElementById('events-list');
    const highEvs = (d.events||[]).filter(e=>e.impact==='HIGH'||e.impact==='MEDIUM');
    if(highEvs.length===0){
      el.innerHTML='<div class="no-data">No high-impact events scheduled</div>';
    } else {
      el.innerHTML = highEvs.slice(0,8).map(e=>`
        <div class="card">
          <div class="card-title">${e.title}${badge(e.impact)}</div>
          <div class="card-meta">
            <span>${e.time}</span>
            <span>${e.currency}</span>
            <span>${pills(e.affects)}</span>
          </div>
          <div class="forecast-row">
            <span>Forecast: <b>${e.forecast||'N/A'}</b></span>
            <span>Previous: <b>${e.previous||'N/A'}</b></span>
            ${e.actual?`<span>Actual: <b>${e.actual}</b></span>`:''}
          </div>
        </div>`).join('');
    }

    // Tweets
    const tl = document.getElementById('tweets-list');
    const tweets = (d.tweets||[]).slice(0,5);
    if(tweets.length===0){
      tl.innerHTML='<div class="no-data">No recent tweets (Twitter API needed)</div>';
    } else {
      tl.innerHTML = tweets.map(t=>`
        <div class="card">
          <div class="tweet-text">${t.text.substring(0,280)}</div>
          <div class="card-meta">
            <span>${new Date(t.time).toLocaleString()}</span>
            ${badge(t.impact)}
            ${pills(t.affects)}
          </div>
          <a class="tweet-link" href="${t.url}" target="_blank">View tweet</a>
        </div>`).join('');
    }

    // News
    const nl = document.getElementById('news-list');
    const news = (d.news||[]).slice(0,10);
    if(news.length===0){
      nl.innerHTML='<div class="no-data">No relevant news found</div>';
    } else {
      nl.innerHTML = news.map(n=>`
        <div class="card">
          <div class="card-title"><a href="${n.link}" target="_blank"
            style="color:inherit;text-decoration:none">${n.title}</a>${badge(n.impact)}</div>
          <div class="card-meta">
            <span>${n.source}</span>
            ${pills(n.affects)}
          </div>
          ${n.summary?`<div style="font-size:11px;color:#888;margin-top:4px">${n.summary}</div>`:''}
        </div>`).join('');
    }

  } catch(e){ console.error(e); }
}

load();
setInterval(load, 60000);
</script>
</body>
</html>"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)

if __name__ == "__main__":
    start_scheduler()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
