"""
Jola News Agent — app.py v3
Flask server with debug endpoint
"""
from flask import Flask, jsonify, render_template_string
from news_agent import start_scheduler, state_get
import os

app = Flask(__name__)

@app.route("/api/mt5")
def mt5_api():
    s = state_get()
    high = [e for e in s["events"] if e.get("impact") == "HIGH"]
    return jsonify({
        "session_risk":     s["session_risk"],
        "next_event":       high[0] if high else None,
        "high_event_count": len(high),
        "tweet_alert":      any(t.get("impact") == "HIGH" for t in s["tweets"]),
        "last_update":      s["last_update"]
    })

@app.route("/api/all")
def api_all():
    return jsonify(state_get())

@app.route("/api/debug")
def api_debug():
    s = state_get()
    return jsonify({
        "debug":        s.get("debug", ""),
        "news_count":   len(s["news"]),
        "event_count":  len(s["events"]),
        "tweet_count":  len(s["tweets"]),
        "session_risk": s["session_risk"],
        "last_update":  s["last_update"],
        "tg_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "tw_configured": bool(os.getenv("TWITTER_BEARER_TOKEN")),
        "sample_news":  s["news"][:2] if s["news"] else []
    })

DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jola News Agent</title>
<style>
:root{--bg:#0d0d0d;--card:#161616;--border:#2a2a2a;--text:#e8e8e8;--muted:#888;
--high:#ff4d4d;--med:#f0a500;--low:#3fb950;--gold:#ffd700;--nas:#58a6ff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,sans-serif;
font-size:14px;padding:14px;max-width:500px;margin:0 auto}
h1{font-size:17px;font-weight:700;margin-bottom:2px;color:var(--gold)}
.sub{color:var(--muted);font-size:11px;margin-bottom:14px}
.risk{padding:10px 14px;border-radius:10px;margin-bottom:14px;
font-weight:700;font-size:15px;text-align:center;letter-spacing:.02em}
.risk-HIGH{background:#2d0a0a;border:1px solid var(--high);color:var(--high)}
.risk-MEDIUM{background:#2d1f00;border:1px solid var(--med);color:var(--med)}
.risk-LOW{background:#0a2d14;border:1px solid var(--low);color:var(--low)}
.sec-title{font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;
letter-spacing:.1em;margin:14px 0 6px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;
padding:11px 13px;margin-bottom:7px}
.card-title{font-size:13px;font-weight:500;line-height:1.4;margin-bottom:4px}
.card-title a{color:var(--text);text-decoration:none}
.card-title a:hover{color:var(--nas)}
.meta{font-size:10px;color:var(--muted);display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.bdg{font-size:9px;font-weight:700;padding:2px 5px;border-radius:3px}
.HIGH{background:#3d0a0a;color:var(--high);border:1px solid #5d1010}
.MEDIUM{background:#2d1f00;color:var(--med);border:1px solid #4d3400}
.LOW{background:#0a1f0a;color:var(--low);border:1px solid #1a3d1a}
.pill{font-size:9px;padding:2px 5px;border-radius:3px}
.pg{background:#2d2500;color:var(--gold);border:1px solid #4d3f00}
.pn{background:#0a1a2d;color:var(--nas);border:1px solid #0d2d4d}
.summary{font-size:11px;color:#999;margin-top:5px;line-height:1.4}
.tweet{font-size:12px;line-height:1.5;margin-bottom:5px}
.tweet-link{font-size:10px;color:var(--nas)}
.empty{color:var(--muted);font-size:12px;padding:6px 0}
.footer{font-size:10px;color:var(--muted);text-align:center;margin-top:16px}
</style>
</head>
<body>
<h1>Jola News Agent</h1>
<div class="sub" id="sub">Loading...</div>
<div class="risk risk-LOW" id="risk">Session Risk: ---</div>

<div class="sec-title">High Impact Events</div>
<div id="events"><div class="empty">Loading...</div></div>

<div class="sec-title">Trump / White House</div>
<div id="tweets"><div class="empty">Loading...</div></div>

<div class="sec-title">Market News</div>
<div id="news"><div class="empty">Loading...</div></div>

<div class="footer">Auto-refreshes every 60s</div>

<script>
const bdg = i=>`<span class="bdg ${i}">${i}</span>`;
const pills = a=>{
  let p='';
  if(a&&a.gold)   p+='<span class="pill pg">GOLD</span> ';
  if(a&&a.nasdaq) p+='<span class="pill pn">NASDAQ</span>';
  return p;
};

async function load(){
  try{
    const r = await fetch('/api/all');
    const d = await r.json();

    // Risk
    const rb = document.getElementById('risk');
    rb.className = `risk risk-${d.session_risk||'LOW'}`;
    rb.textContent = `Session Risk: ${d.session_risk||'LOW'}`;

    // Subtitle
    if(d.last_update){
      const dt = new Date(d.last_update);
      document.getElementById('sub').textContent =
        'Updated: '+dt.toLocaleTimeString()+' | '+
        (d.news||[]).length+' articles | '+
        (d.tweets||[]).length+' tweets';
    }

    // Events
    const evs = (d.events||[]).filter(e=>e.impact==='HIGH'||e.impact==='MEDIUM');
    document.getElementById('events').innerHTML = evs.length===0
      ? '<div class="empty">No high-impact events — clear to trade</div>'
      : evs.slice(0,6).map(e=>`
        <div class="card">
          <div class="card-title">${e.title} ${bdg(e.impact)}</div>
          <div class="meta"><span>${e.time||'TBD'}</span>${pills(e.affects)}</div>
        </div>`).join('');

    // Tweets
    const tws = (d.tweets||[]);
    document.getElementById('tweets').innerHTML = tws.length===0
      ? '<div class="empty">No tweets yet — add Twitter Bearer Token in Render env vars</div>'
      : tws.slice(0,4).map(t=>`
        <div class="card">
          <div class="tweet">${t.text.substring(0,280)}</div>
          <div class="meta">
            <span>${new Date(t.time).toLocaleString()}</span>
            ${bdg(t.impact)} ${pills(t.affects)}
          </div>
          <a class="tweet-link" href="${t.url}" target="_blank">Open tweet →</a>
        </div>`).join('');

    // News
    const nws = (d.news||[]);
    document.getElementById('news').innerHTML = nws.length===0
      ? '<div class="empty">No relevant news found — feeds may be loading</div>'
      : nws.slice(0,12).map(n=>`
        <div class="card">
          <div class="card-title">
            <a href="${n.link}" target="_blank">${n.title}</a>
            ${bdg(n.impact)}
          </div>
          <div class="meta"><span>${n.source}</span>${pills(n.affects)}</div>
          ${n.summary?`<div class="summary">${n.summary}</div>`:''}
        </div>`).join('');

  }catch(e){
    document.getElementById('sub').textContent='Error loading data — retrying...';
    console.error(e);
  }
}
load();
setInterval(load,60000);
</script>
</body>
</html>"""

@app.route("/")
def dashboard():
    return render_template_string(DASHBOARD)

if __name__ == "__main__":
    start_scheduler()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
