import os
import sqlite3
import secrets
import hashlib
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify, session, redirect, render_template_string

PUBLIC_ACCESS_PRICE = "R400"
WHATSAPP_NUMBER = "27697343252"
INSTAGRAM_URL = "https://instagram.com/ashleysnowfx"
TIKTOK_URL = "https://tiktok.com/@snowFx3"
REQUEST_URL = "https://tw-trades-1.onrender.com/#request"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

DB = "tw_blueprint.db"

MAX_DAILY = 6
MAX_PER_SESSION = 2

SESSIONS = {
    "ASIAN": (0, 8),
    "LONDON": (7, 16),
    "NEW YORK": (12, 21)
}

ASSETS = {
    "XAU/USD": {"group":"METALS","td":"XAU/USD","news":"XAU"},
    "EUR/USD": {"group":"FOREX","td":"EUR/USD","news":"EUR,USD"},
    "GBP/USD": {"group":"FOREX","td":"GBP/USD","news":"GBP,USD"},
    "USD/JPY": {"group":"FOREX","td":"USD/JPY","news":"USD,JPY"},
    "GBP/JPY": {"group":"FOREX","td":"GBP/JPY","news":"GBP,JPY"},
    "EUR/JPY": {"group":"FOREX","td":"EUR/JPY","news":"EUR,JPY"},
    "EUR/AUD": {"group":"FOREX","td":"EUR/AUD","news":"EUR,AUD"},
    "GBP/AUD": {"group":"FOREX","td":"GBP/AUD","news":"GBP,AUD"},
    "USD/CHF": {"group":"FOREX","td":"USD/CHF","news":"USD,CHF"},
    "AUD/USD": {"group":"FOREX","td":"AUD/USD","news":"AUD,USD"},
    "USD/CAD": {"group":"FOREX","td":"USD/CAD","news":"USD,CAD"},

    "NASDAQ": {"group":"INDICES","td":"IXIC","news":"IXIC"},
    "US30": {"group":"INDICES","td":"DJI","news":"DJI"},
    "S&P 500": {"group":"INDICES","td":"SPX","news":"SPX"},
    "DAX40": {"group":"INDICES","td":"DAX","news":"DAX"},
    "FTSE100": {"group":"INDICES","td":"FTSE","news":"FTSE"},
    "VIX": {"group":"INDICES","td":"VIX","news":"VIX"},

    "BTC/USD": {"group":"CRYPTO","td":"BTC/USD","news":"BTC"},
    "ETH/USD": {"group":"CRYPTO","td":"ETH/USD","news":"ETH"},
    "SOL/USD": {"group":"CRYPTO","td":"SOL/USD","news":"SOL"},
    "XRP/USD": {"group":"CRYPTO","td":"XRP/USD","news":"XRP"},
    "ADA/USD": {"group":"CRYPTO","td":"ADA/USD","news":"ADA"},
    "DOGE/USD": {"group":"CRYPTO","td":"DOGE/USD","news":"DOGE"}
}

COURSES = [
    {
        "title":"Forex Foundation",
        "tag":"FOUNDATION",
        "desc":"Build a complete understanding of the foreign exchange market.",
        "lessons":[
            "What is Forex?",
            "Currency pairs",
            "Pips, lots and spreads",
            "Leverage and margin",
            "Trading sessions",
            "Order types",
            "Broker fundamentals",
            "Building your first trading plan"
        ]
    },
    {
        "title":"Technical Analysis",
        "tag":"TECHNICAL",
        "desc":"Learn to read price instead of depending on indicator overload.",
        "lessons":[
            "Market structure",
            "Support and resistance",
            "Candlestick anatomy",
            "Trend identification",
            "Breakouts",
            "Liquidity",
            "False breakouts",
            "Multi-timeframe analysis"
        ]
    },
    {
        "title":"TW Blueprint",
        "tag":"CORE",
        "desc":"The complete Indication → Correction → Continuation framework.",
        "lessons":[
            "Trading range",
            "No-trade zones",
            "Indication",
            "Body-based structure breaks",
            "Correction",
            "Continuation",
            "CRT integration",
            "4H markup",
            "1H confirmation",
            "15M setup",
            "5M execution"
        ]
    },
    {
        "title":"Fundamental Analysis",
        "tag":"MACRO",
        "desc":"Understand the economic forces behind market movement.",
        "lessons":[
            "Interest rates",
            "Inflation",
            "CPI",
            "NFP",
            "FOMC",
            "Central banks",
            "Employment data",
            "GDP",
            "Bond yields",
            "Dollar strength",
            "Geopolitical risk",
            "News sentiment"
        ]
    },
    {
        "title":"Gold Mastery",
        "tag":"XAU/USD",
        "desc":"A dedicated framework for understanding and trading gold.",
        "lessons":[
            "What drives gold?",
            "Gold and the US dollar",
            "Gold and yields",
            "Risk-off environments",
            "London gold behavior",
            "New York gold behavior",
            "Gold liquidity",
            "Gold structure",
            "Gold ICC setups"
        ]
    },
    {
        "title":"Trading Psychology",
        "tag":"MINDSET",
        "desc":"Build the discipline required to execute a trading plan.",
        "lessons":[
            "Discipline",
            "Patience",
            "Fear",
            "Greed",
            "Revenge trading",
            "Overtrading",
            "Loss acceptance",
            "Process over outcome",
            "Trading journal"
        ]
    },
    {
        "title":"Advanced Trader",
        "tag":"ADVANCED",
        "desc":"Combine structure, liquidity, fundamentals and execution.",
        "lessons":[
            "Advanced confluence",
            "Liquidity engineering",
            "Institutional behavior",
            "Market regime",
            "Volatility",
            "Session manipulation",
            "Trade management",
            "Risk architecture",
            "Building a systematic process"
        ]
    }
]

# ============================================================
# DATABASE
# ============================================================

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()

    c.execute("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS signals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created TEXT,
        symbol TEXT,
        session TEXT,
        direction TEXT,
        entry REAL,
        stop REAL,
        tp1 REAL,
        tp2 REAL,
        score REAL,
        reason TEXT
    )
    """)

    defaults = {
        "twelve_data_key":"",
        "marketaux_key":"",
        "openai_key":"",
        "openai_model":"gpt-5.6",
        "admin_password_hash":hashlib.sha256(
            b"change-me"
        ).hexdigest()
    }

    for k,v in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (k,v)
        )

    c.commit()
    c.close()

init_db()

def get_setting(key):
    c=db()
    r=c.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    c.close()
    return r["value"] if r else ""

def set_setting(key,value):
    c=db()
    c.execute("""
    INSERT INTO settings(key,value)
    VALUES(?,?)
    ON CONFLICT(key)
    DO UPDATE SET value=excluded.value
    """,(key,value))
    c.commit()
    c.close()

# ============================================================
# SESSION
# ============================================================

def current_session():
    hour=datetime.now(timezone.utc).hour

    for name,(start,end) in SESSIONS.items():
        if start <= hour < end:
            return name

    return "OFF-SESSION"

# ============================================================
# MARKET DATA
# ============================================================

def td(symbol,interval,size=100):
    key=get_setting("twelve_data_key")

    if not key:
        return None,"Twelve Data key not configured"

    try:
        r=requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol":symbol,
                "interval":interval,
                "outputsize":size,
                "apikey":key
            },
            timeout=15
        )

        data=r.json()

        if "values" not in data:
            return None,data.get(
                "message",
                "No market data returned"
            )

        values=[]

        for x in reversed(data["values"]):
            values.append({
                "time":x["datetime"],
                "open":float(x["open"]),
                "high":float(x["high"]),
                "low":float(x["low"]),
                "close":float(x["close"])
            })

        return values,None

    except Exception as e:
        return None,str(e)

# ============================================================
# MARKET AUX
# ============================================================

def news(symbol):
    key=get_setting("marketaux_key")

    if not key:
        return {
            "available":False,
            "sentiment":0,
            "articles":[]
        }

    try:
        entity=ASSETS[symbol]["news"]

        r=requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={
                "api_token":key,
                "symbols":entity,
                "filter_entities":"true",
                "language":"en",
                "limit":10
            },
            timeout=15
        )

        data=r.json()
        articles=data.get("data",[])

        scores=[]

        for article in articles:
            for ent in article.get("entities",[]):
                s=ent.get("sentiment_score")

                if isinstance(s,(int,float)):
                    scores.append(float(s))

        sentiment=(
            sum(scores)/len(scores)
            if scores else 0
        )

        return {
            "available":True,
            "sentiment":round(sentiment,3),
            "articles":articles[:6]
        }

    except Exception:
        return {
            "available":False,
            "sentiment":0,
            "articles":[]
        }

# ============================================================
# TECHNICAL INTELLIGENCE
# ============================================================

def atr(data,n=14):
    if len(data)<n+2:
        return 0

    tr=[]

    for i in range(1,len(data)):
        h=data[i]["high"]
        l=data[i]["low"]
        pc=data[i-1]["close"]

        tr.append(
            max(
                h-l,
                abs(h-pc),
                abs(l-pc)
            )
        )

    return sum(tr[-n:])/n

def trend(data):
    if len(data)<30:
        return "NEUTRAL"

    fast=sum(x["close"] for x in data[-10:])/10
    slow=sum(x["close"] for x in data[-30:])/30

    if fast>slow:
        return "BULLISH"

    if fast<slow:
        return "BEARISH"

    return "NEUTRAL"

def body_high(x):
    return max(x["open"],x["close"])

def body_low(x):
    return min(x["open"],x["close"])

def body_break(data,direction):
    if len(data)<25:
        return False

    if direction=="BUY":
        level=max(
            body_high(x)
            for x in data[-21:-1]
        )
        return data[-1]["close"]>level

    level=min(
        body_low(x)
        for x in data[-21:-1]
    )

    return data[-1]["close"]<level

def continuation(data,direction):
    if len(data)<3:
        return False

    a=data[-1]
    b=data[-2]

    if direction=="BUY":
        return (
            a["close"]>a["open"]
            and a["close"]>b["close"]
        )

    return (
        a["close"]<a["open"]
        and a["close"]<b["close"]
    )

def correction(data,direction):
    if len(data)<8:
        return False

    recent=data[-6:]

    if direction=="BUY":
        return min(
            x["low"] for x in recent
        ) < data[-7]["close"]

    return max(
        x["high"] for x in recent
    ) > data[-7]["close"]

# ============================================================
# FUNDAMENTAL INTELLIGENCE
# ============================================================

def fundamental_view(sent):
    if sent>=0.30:
        return {
            "bias":"POSITIVE",
            "impact":"HIGH",
            "description":
            "Recent MarketAux entity sentiment is materially positive."
        }

    if sent>=0.10:
        return {
            "bias":"SLIGHTLY POSITIVE",
            "impact":"MODERATE",
            "description":
            "News flow is leaning positive."
        }

    if sent<=-0.30:
        return {
            "bias":"NEGATIVE",
            "impact":"HIGH",
            "description":
            "Recent MarketAux entity sentiment is materially negative."
        }

    if sent<=-0.10:
        return {
            "bias":"SLIGHTLY NEGATIVE",
            "impact":"MODERATE",
            "description":
            "News flow is leaning negative."
        }

    return {
        "bias":"NEUTRAL",
        "impact":"LOW",
        "description":
        "Current entity news flow is not strongly directional."
    }

# ============================================================
# SIGNAL ENGINE
# ============================================================

def analyze(symbol):

    if symbol not in ASSETS:
        return {"status":"ERROR","message":"Unknown symbol"}

    sess=current_session()

    if sess=="OFF-SESSION":
        return {
            "symbol":symbol,
            "status":"NO TRADE",
            "message":"Outside configured trading sessions."
        }

    c=db()

    today=datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")

    rows=c.execute(
        "SELECT * FROM signals WHERE created LIKE ?",
        (today+"%",)
    ).fetchall()

    c.close()

    if len(rows)>=MAX_DAILY:
        return {
            "symbol":symbol,
            "status":"DAILY LIMIT",
            "message":"Maximum 6 signals reached."
        }

    session_count=sum(
        1 for x in rows
        if x["session"]==sess
    )

    if session_count>=MAX_PER_SESSION:
        return {
            "symbol":symbol,
            "status":"SESSION LIMIT",
            "message":f"{sess} has reached its 2-signal limit."
        }

    if any(x["symbol"]==symbol for x in rows):
        return {
            "symbol":symbol,
            "status":"ALREADY SCANNED",
            "message":"Asset already produced a signal today."
        }

    frames={}

    for interval in ["4h","1h","15min","5min"]:
        data,error=td(
            ASSETS[symbol]["td"],
            interval,
            100
        )

        if error:
            return {
                "symbol":symbol,
                "status":"DATA ERROR",
                "message":error
            }

        frames[interval]=data

    t4=trend(frames["4h"])
    t1=trend(frames["1h"])
    t15=trend(frames["15min"])
    m5=frames["5min"]

    technical_buy=0
    technical_sell=0

    buy=[]
    sell=[]

    if t4=="BULLISH":
        technical_buy+=20
        buy.append("4H bullish structure")

    if t4=="BEARISH":
        technical_sell+=20
        sell.append("4H bearish structure")

    if t1=="BULLISH":
        technical_buy+=15
        buy.append("1H bullish alignment")

    if t1=="BEARISH":
        technical_sell+=15
        sell.append("1H bearish alignment")

    if t15=="BULLISH":
        technical_buy+=15
        buy.append("15M bullish alignment")

    if t15=="BEARISH":
        technical_sell+=15
        sell.append("15M bearish alignment")

    if body_break(m5,"BUY"):
        technical_buy+=15
        buy.append("Body-based bullish indication")

    if body_break(m5,"SELL"):
        technical_sell+=15
        sell.append("Body-based bearish indication")

    if correction(m5,"BUY"):
        technical_buy+=8
        buy.append("Correction/retest")

    if correction(m5,"SELL"):
        technical_sell+=8
        sell.append("Correction/retest")

    if continuation(m5,"BUY"):
        technical_buy+=12
        buy.append("Bullish continuation")

    if continuation(m5,"SELL"):
        technical_sell+=12
        sell.append("Bearish continuation")

    n=news(symbol)
    fund=fundamental_view(n["sentiment"])

    if n["sentiment"]>0.10:
        technical_buy+=5
        buy.append("Positive fundamental/news flow")

    elif n["sentiment"]<-0.10:
        technical_sell+=5
        sell.append("Negative fundamental/news flow")

    if technical_buy>=technical_sell:
        direction="BUY"
        score=technical_buy
        reasons=buy
    else:
        direction="SELL"
        score=technical_sell
        reasons=sell

    if score<72:
        return {
            "symbol":symbol,
            "status":"NO TRADE",
            "score":score,
            "session":sess,
            "trend4h":t4,
            "trend1h":t1,
            "trend15m":t15,
            "fundamental":fund,
            "news_sentiment":n["sentiment"],
            "message":
            "Insufficient TW Blueprint confluence."
        }

    price=m5[-1]["close"]
    a=atr(m5)

    if not a:
        return {
            "symbol":symbol,
            "status":"NO TRADE",
            "message":"ATR unavailable."
        }

    if direction=="BUY":
        entry=price
        stop=price-a*1.2
        risk=entry-stop
        tp1=entry+risk*1.5
        tp2=entry+risk*2.5
    else:
        entry=price
        stop=price+a*1.2
        risk=stop-entry
        tp1=entry-risk*1.5
        tp2=entry-risk*2.5

    return {
        "symbol":symbol,
        "status":"QUALIFIED",
        "session":sess,
        "direction":direction,
        "score":score,
        "entry":round(entry,6),
        "stop":round(stop,6),
        "tp1":round(tp1,6),
        "tp2":round(tp2,6),
        "atr":round(a,6),
        "trend4h":t4,
        "trend1h":t1,
        "trend15m":t15,
        "fundamental":fund,
        "news_sentiment":n["sentiment"],
        "articles":n["articles"],
        "reasons":reasons
    }

# ============================================================
# AI ANALYST
# ============================================================

def ai_analysis(payload):

    key=get_setting("openai_key")

    if not key:
        return {
            "available":False,
            "text":
            "AI Analyst is not configured. Add an OpenAI API key in Admin."
        }

    model=get_setting("openai_model") or "gpt-5.6"

    prompt=f"""
You are the TW Trades Intelligence Analyst.

Analyze the following REAL market-analysis payload.

Do not invent prices, news, economic releases, technical levels,
or facts that are not contained in the payload.

Explain:
1. Technical structure
2. TW Blueprint ICC state
3. Fundamental/news environment
4. Session context
5. Why the setup qualifies or does not qualify
6. What would invalidate it
7. Main risks
8. Educational lesson for the trader

Never guarantee profit or accuracy.

PAYLOAD:
{payload}
"""

    try:
        r=requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization":f"Bearer {key}",
                "Content-Type":"application/json"
            },
            json={
                "model":model,
                "input":prompt
            },
            timeout=60
        )

        data=r.json()

        text=data.get("output_text")

        if text:
            return {
                "available":True,
                "text":text
            }

        return {
            "available":False,
            "text":"AI returned no text."
        }

    except Exception as e:
        return {
            "available":False,
            "text":f"AI connection error: {e}"
        }

# ============================================================
# API
# ============================================================

@app.route("/api/scan")
def api_scan():

    symbol=request.args.get("symbol")

    if symbol:
        return jsonify(analyze(symbol))

    results=[]

    for s in ASSETS:
        r=analyze(s)

        if r.get("status")=="QUALIFIED":
            results.append(r)

    results.sort(
        key=lambda x:x.get("score",0),
        reverse=True
    )

    return jsonify({
        "session":current_session(),
        "daily_maximum":MAX_DAILY,
        "results":results[:MAX_DAILY]
    })

@app.route("/api/news")
def api_news():

    symbol=request.args.get(
        "symbol",
        "XAU/USD"
    )

    return jsonify(news(symbol))

@app.route("/api/ai",methods=["POST"])
def api_ai():

    payload=request.get_json(
        force=True,
        silent=True
    ) or {}

    return jsonify(
        ai_analysis(payload)
    )

@app.route("/api/commit",methods=["POST"])
def commit():

    data=request.get_json(
        force=True,
        silent=True
    ) or {}

    symbol=data.get("symbol")
    sess=data.get("session")

    c=db()

    today=datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")

    count=c.execute(
        "SELECT COUNT(*) n FROM signals WHERE created LIKE ?",
        (today+"%",)
    ).fetchone()["n"]

    if count>=MAX_DAILY:
        c.close()
        return jsonify({
            "error":"Daily signal limit reached."
        }),400

    sc=c.execute(
        "SELECT COUNT(*) n FROM signals WHERE created LIKE ? AND session=?",
        (today+"%",sess)
    ).fetchone()["n"]

    if sc>=MAX_PER_SESSION:
        c.close()
        return jsonify({
            "error":"Session signal limit reached."
        }),400

    c.execute("""
    INSERT INTO signals(
        created,symbol,session,direction,
        entry,stop,tp1,tp2,score,reason
    )
    VALUES(?,?,?,?,?,?,?,?,?,?)
    """,(
        datetime.now(timezone.utc).isoformat(),
        symbol,
        sess,
        data.get("direction"),
        data.get("entry"),
        data.get("stop"),
        data.get("tp1"),
        data.get("tp2"),
        data.get("score"),
        "TW Blueprint ICC qualified"
    ))

    c.commit()
    c.close()

    return jsonify({"ok":True})

# ============================================================
# ADMIN
# ============================================================

@app.route("/admin/login",methods=["GET","POST"])
def login():

    if request.method=="POST":

        password=request.form.get(
            "password",""
        )

        hashed=hashlib.sha256(
            password.encode()
        ).hexdigest()

        if hashed==get_setting(
            "admin_password_hash"
        ):
            session["admin"]=True
            return redirect("/admin")

    return """
    <html>
    <meta name="viewport" content="width=device-width">
    <body style="
    background:#05070b;color:white;
    font-family:Arial;padding:35px">
    <h1>TW ADMIN</h1>
    <form method="post">
    <input name="password"
    type="password"
    placeholder="Admin password"
    style="padding:15px;width:90%;max-width:350px">
    <br><br>
    <button style="padding:14px 25px">
    LOGIN
    </button>
    </form>
    
<!-- TW TRADES PUBLIC ACCESS -->
<section id="request" style="
margin:60px auto;
max-width:1100px;
padding:45px 25px;
border:1px solid rgba(0,255,200,.25);
border-radius:28px;
background:linear-gradient(135deg,rgba(8,18,30,.98),rgba(5,10,20,.98));
box-shadow:0 0 45px rgba(0,255,200,.08);
text-align:center;
">
<div style="font-size:13px;letter-spacing:3px;color:#00ffd0;font-weight:800;">
TW TRADES PUBLIC ACCESS
</div>





<h2 style="font-size:42px;margin:12px 0 8px;">
PUBLIC ACCESS — <span style="color:#00ffd0;">R400</span>
</h2>

<p style="max-width:700px;margin:0 auto 25px;color:#aab7c8;line-height:1.7;">
Request access to the TW Trades ecosystem and receive the instructions directly through WhatsApp.
</p>

<a href="https://wa.me/27697343252?text=Hi%20Neo%2C%20I%20want%20to%20request%20TW%20Trades%20Public%20Access%20for%20R400.%20Please%20send%20me%20the%20payment%20and%20access%20instructions."
style="
display:inline-block;
padding:16px 32px;
border-radius:14px;
background:#00ffd0;
color:#03100e;
font-weight:900;
text-decoration:none;
margin:8px;
box-shadow:0 0 25px rgba(0,255,208,.25);
">
REQUEST ACCESS — R400
</a>

<div style="margin-top:28px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
<a href="https://instagram.com/ashleysnowfx"
target="_blank"
style="padding:12px 20px;border:1px solid #29384b;border-radius:12px;color:#fff;text-decoration:none;">
Instagram · @ashleysnowfx
</a>

<a href="https://tiktok.com/@snowFx3"
target="_blank"
style="padding:12px 20px;border:1px solid #29384b;border-radius:12px;color:#fff;text-decoration:none;">
TikTok · @snowFx3
</a>
</div>
</section>


<!-- TW TRADES MOBILE NAV -->
<div class="tw-mobile-nav">
<a href="#top" class="active"><span>⌂</span>Home</a>
<a href="#terminal"><span>◈</span>Terminal</a>
<a href="#intelligence"><span>◉</span>Intel</a>
<a href="#titan"><span>◆</span>Titan</a>
<a href="#yuki"><span>✦</span>Yuki</a>
<a href="#request"><span>↗</span>Access</a>
</div>


<script>
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js", {scope: "/"})
      .catch(function(error) {
        console.log("TW Trades service worker:", error);
      });
  });
}
</script>

</body>
    </html>
    """

@app.route("/admin",methods=["GET","POST"])
def admin():

    if not session.get("admin"):
        return redirect("/admin/login")

    if request.method=="POST":

        for key in [
            "twelve_data_key",
            "marketaux_key",
            "openai_key",
            "openai_model"
        ]:
            value=request.form.get(key,"").strip()

            if value and not value.startswith("********"):
                set_setting(key,value)

        password=request.form.get(
            "admin_password",""
        ).strip()

        if password:
            set_setting(
                "admin_password_hash",
                hashlib.sha256(
                    password.encode()
                ).hexdigest()
            )

    return render_template_string(
    ADMIN_HTML,
    td="********" if get_setting("twelve_data_key") else "",
    ma="********" if get_setting("marketaux_key") else "",
    ai="********" if get_setting("openai_key") else "",
    model=get_setting("openai_model")
    )

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/")

# ============================================================
# ADMIN HTML
# ============================================================

ADMIN_HTML="""
<!doctype html>
<html>
<meta name="viewport" content="width=device-width">
<title>TW Admin</title>

<style>
/* ============================================================
   TW TRADES PREMIUM UPGRADE
   ============================================================ */

.tw-upgrade{
max-width:1200px;
margin:35px auto;
padding:0 18px;
}

.tw-upgrade-head{
text-align:center;
margin-bottom:30px;
}

.tw-badge{
display:inline-block;
padding:7px 14px;
border:1px solid rgba(0,255,208,.35);
border-radius:999px;
color:#00ffd0;
font-size:12px;
font-weight:900;
letter-spacing:1.5px;
margin-bottom:12px;
}

.tw-upgrade-head h2{
font-size:clamp(30px,5vw,52px);
margin:5px 0 10px;
line-height:1.05;
}

.tw-upgrade-head p{
max-width:720px;
margin:auto;
color:#9eacbd;
line-height:1.7;
}

.tw-package-grid{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(270px,1fr));
gap:18px;
}

.tw-package{
position:relative;
padding:26px;
border:1px solid #253448;
border-radius:22px;
background:
linear-gradient(145deg,rgba(20,31,46,.96),rgba(5,8,14,.96));
box-shadow:0 18px 50px rgba(0,0,0,.25);
transition:.25s ease;
}

.tw-package:hover{
transform:translateY(-5px);
border-color:#00ffd0;
box-shadow:0 20px 60px rgba(0,255,208,.10);
}

.tw-package.featured{
border-color:rgba(0,255,208,.65);
box-shadow:0 0 45px rgba(0,255,208,.09);
}

.tw-package .tw-label{
font-size:12px;
font-weight:900;
letter-spacing:1.4px;
color:#00ffd0;
}

.tw-package h3{
font-size:24px;
margin:10px 0 5px;
}

.tw-price{
font-size:34px;
font-weight:950;
margin:12px 0 20px;
}

.tw-package ul{
list-style:none;
padding:0;
margin:0 0 22px;
}

.tw-package li{
padding:8px 0;
color:#c5d0dd;
}

.tw-package li:before{
content:"✓";
color:#00ffd0;
font-weight:900;
margin-right:9px;
}

.tw-package-btn{
display:block;
text-align:center;
padding:13px 18px;
border-radius:13px;
text-decoration:none;
font-weight:900;
border:1px solid #304158;
color:#fff;
}

.tw-package-btn.primary{
background:#00ffd0;
color:#03100e;
border-color:#00ffd0;
}

.tw-intelligence{
margin-top:25px;
display:grid;
grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
gap:14px;
}

.tw-intel{
padding:20px;
border-radius:18px;
border:1px solid #202e40;
background:rgba(12,18,28,.82);
}

.tw-intel strong{
display:block;
font-size:18px;
margin-bottom:7px;
}

.tw-intel span{
color:#93a2b5;
font-size:14px;
line-height:1.55;
}

.tw-contact-row{
display:flex;
flex-wrap:wrap;
justify-content:center;
gap:10px;
margin-top:24px;
}

.tw-contact{
padding:11px 16px;
border:1px solid #29384b;
border-radius:12px;
color:#fff;
text-decoration:none;
font-weight:700;
}

.tw-contact:hover{
border-color:#00ffd0;
color:#00ffd0;
}

@media(max-width:600px){
.tw-upgrade{
padding:0 12px;
}

.tw-package{
padding:21px;
}

.tw-price{
font-size:30px;
}
}

body{
background:#05070b;
color:#edf3fb;
font-family:Arial;
margin:0;
}
.wrap{
max-width:750px;
margin:auto;
padding:25px;
}
.card{
background:#0d131c;
border:1px solid #243044;
border-radius:20px;
padding:22px;
margin-bottom:15px;
}
input{
width:100%;
box-sizing:border-box;
background:#080d14;
border:1px solid #344257;
border-radius:10px;
padding:14px;
color:white;
margin:7px 0 15px;
}
button{
padding:14px 20px;
border:0;
border-radius:10px;
font-weight:bold;
}

/* ===== TW TRADES SAFE MOBILE UPGRADE ===== */
.tw-mobile-nav{
display:none;
}

.tw-mobile-nav a{
text-decoration:none;
color:#9aa8ba;
font-size:10px;
font-weight:800;
letter-spacing:.3px;
text-align:center;
min-width:54px;
}

.tw-mobile-nav a span{
display:block;
font-size:18px;
margin-bottom:3px;
}

@media(max-width:760px){
.navlinks{
display:none !important;
}

.menu{
display:block !important;
}

body{
padding-bottom:82px;
}

.tw-mobile-nav{
position:fixed;
left:10px;
right:10px;
bottom:10px;
z-index:9999;
display:flex;
align-items:center;
justify-content:space-around;
gap:4px;
padding:11px 7px;
border:1px solid rgba(0,255,208,.18);
border-radius:20px;
background:rgba(4,10,18,.94);
backdrop-filter:blur(18px);
box-shadow:0 10px 35px rgba(0,0,0,.45),0 0 25px rgba(0,255,208,.06);
}

.tw-mobile-nav a.active,
.tw-mobile-nav a:hover{
color:#00ffd0;
}

.hero{
padding-left:20px !important;
padding-right:20px !important;
}

h1{
font-size:clamp(42px,12vw,72px) !important;
}

.tw-upgrade{
margin-left:15px !important;
margin-right:15px !important;
}

#request{
margin-left:15px !important;
margin-right:15px !important;
}

#request h2{
font-size:32px !important;
}
}

</style>

<div class="wrap">

<div class="card">
<h1>TW CONTROL CENTER</h1>
<p>Platform configuration</p>

<form method="post">

<label>Twelve Data API Key</label>
<input name="twelve_data_key"
value="{{td}}"
type="password">

<label>MarketAux API Key</label>
<input name="marketaux_key"
value="{{ma}}"
type="password">

<label>OpenAI API Key</label>
<input name="openai_key"
value="{{ai}}"
type="password">

<label>AI Model</label>
<input name="openai_model"
value="{{model}}">

<label>New Admin Password</label>
<input name="admin_password"
type="password">

<button>SAVE PLATFORM SETTINGS</button>

</form>
</div>

<div class="card">
<h2>Platform modules</h2>
<p>✓ TW Blueprint</p>
<p>✓ Titan X</p>
<p>✓ Yuki</p>
<p>✓ Autonomy of Success Academy</p>
<p>✓ Fundamental Intelligence</p>
<p>✓ AI Analyst</p>
<p>✓ MarketAux News</p>
<p>✓ Twelve Data</p>
<p>✓ 6-signal daily engine</p>
</div>

<a href="/" style="color:white">← Back to platform</a>

</div>
</html>
"""

# ============================================================
# FULL PLATFORM
# ============================================================


@app.route("/manifest.json")
def pwa_manifest():
    return app.send_static_file("manifest.json")

@app.route("/sw.js")
def pwa_service_worker():
    response = app.send_static_file("sw.js")
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Service-Worker-Allowed"] = "/"
    return response

PAGE="""
<!doctype html>
<html>
<head>

<meta name="viewport"
content="width=device-width,initial-scale=1">

<title>TW Trades | The Autonomy of Success</title>

<style>

*{box-sizing:border-box}

html{
scroll-behavior:smooth;
}

body{
margin:0;
background:
radial-gradient(circle at 20% 0%,#152033 0,#05070b 32%),
#05070b;
color:#edf3fb;
font-family:Inter,Arial,sans-serif;
overflow-x:hidden;
}

body:before{
content:"";
position:fixed;
inset:0;
pointer-events:none;
opacity:.18;
background-image:
linear-gradient(#ffffff08 1px,transparent 1px),
linear-gradient(90deg,#ffffff08 1px,transparent 1px);
background-size:55px 55px;
}

nav{
position:sticky;
top:0;
z-index:100;
backdrop-filter:blur(20px);
background:#05070bdd;
border-bottom:1px solid #ffffff12;
display:flex;
align-items:center;
justify-content:space-between;
padding:14px 5%;
}

.logo{
font-size:22px;
font-weight:1000;
letter-spacing:2px;
}

.logo span{
color:#91a8ff;
}

.navlinks{
display:flex;
gap:18px;
align-items:center;
}

.navlinks a{
color:#aeb9ca;
text-decoration:none;
font-size:13px;
}

.navlinks a:hover{
color:white;
}

.menu{
display:none;
}

.hero{
min-height:92vh;
display:flex;
align-items:center;
padding:70px 7%;
position:relative;
}

.hero-content{
max-width:850px;
animation:rise 1s ease;
}

.eyebrow{
letter-spacing:4px;
font-size:11px;
color:#9caeff;
font-weight:bold;
}

h1{
font-size:clamp(48px,8vw,100px);
line-height:.92;
margin:18px 0;
letter-spacing:-5px;
}

.gradient{
background:linear-gradient(
90deg,#fff,#9daeff,#ffffff
);
-webkit-background-clip:text;
color:transparent;
}

.hero p{
font-size:18px;
line-height:1.7;
color:#9ba8ba;
max-width:680px;
}

.buttons{
display:flex;
gap:12px;
flex-wrap:wrap;
margin-top:30px;
}

.btn{
padding:15px 22px;
border-radius:12px;
border:1px solid #ffffff20;
color:white;
text-decoration:none;
background:#111927;
font-weight:bold;
}

.btn.primary{
background:white;
color:#05070b;
}

.glow{
position:absolute;
width:500px;
height:500px;
border-radius:50%;
right:-150px;
top:100px;
background:#546dff30;
filter:blur(90px);
animation:pulse 5s infinite alternate;
}

section{
padding:90px 6%;
position:relative;
}

.section-head{
max-width:750px;
margin-bottom:35px;
}

.kicker{
color:#8299ff;
font-size:11px;
font-weight:bold;
letter-spacing:3px;
}

h2{
font-size:clamp(32px,5vw,60px);
margin:10px 0;
letter-spacing:-2px;
}

.muted{
color:#8d9aae;
line-height:1.7;
}

.cards{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(260px,1fr));
gap:15px;
}

.card{
background:
linear-gradient(145deg,#101824dd,#080c13dd);
border:1px solid #ffffff12;
border-radius:22px;
padding:24px;
position:relative;
overflow:hidden;
transition:.35s;
}

.card:hover{
transform:translateY(-7px);
border-color:#8299ff55;
box-shadow:0 20px 60px #0008;
}

.card:after{
content:"";
position:absolute;
width:100px;
height:100px;
right:-50px;
top:-50px;
border-radius:50%;
background:#7286ff22;
filter:blur(20px);
}

.big-card{
min-height:300px;
}

.icon{
font-size:32px;
margin-bottom:15px;
}

.card h3{
font-size:24px;
margin:5px 0 10px;
}

.tag{
display:inline-block;
padding:6px 9px;
border-radius:7px;
background:#172135;
color:#a8b6ff;
font-size:10px;
font-weight:bold;
letter-spacing:1px;
}

.terminal{
background:#060b11;
border:1px solid #263449;
border-radius:25px;
overflow:hidden;
box-shadow:0 30px 100px #0009;
}

.term-top{
padding:15px;
display:flex;
gap:10px;
align-items:center;
border-bottom:1px solid #1c2838;
}

.dot{
width:9px;
height:9px;
border-radius:50%;
background:#8299ff;
}

.ticker{
overflow:hidden;
white-space:nowrap;
border-bottom:1px solid #182334;
padding:10px;
color:#92a1b6;
font-size:12px;
}

.ticker span{
display:inline-block;
margin-right:35px;
animation:scroll 25s linear infinite;
}

.terminal-body{
padding:18px;
}

.controls{
display:flex;
gap:10px;
flex-wrap:wrap;
margin-bottom:18px;
}

button{
background:#101824;
border:1px solid #29374b;
color:white;
padding:12px 16px;
border-radius:10px;
cursor:pointer;
}

button:hover{
border-color:#8299ff;
}

.signal-grid{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(280px,1fr));
gap:12px;
}

.signal{
background:#0b111a;
border:1px solid #1c293b;
border-radius:18px;
padding:18px;
}

.buy{
color:#63dfa0;
}

.sell{
color:#ff8b8b;
}

.price{
font-size:27px;
font-weight:900;
margin:10px 0;
}

.line{
display:flex;
justify-content:space-between;
padding:7px 0;
border-bottom:1px solid #172231;
font-size:13px;
}

.news{
display:grid;
grid-template-columns:
repeat(auto-fit,minmax(280px,1fr));
gap:12px;
}

.news-item{
padding:18px;
border-radius:16px;
background:#0c121b;
border:1px solid #1d2a3c;
}

.news-item a{
color:white;
text-decoration:none;
}

.academy{
background:
radial-gradient(
circle at 80% 20%,
#384b9a25,
transparent 35%
);
}

.course{
min-height:260px;
}

.lesson{
display:block;
padding:8px 0;
color:#8f9caf;
font-size:13px;
border-bottom:1px solid #ffffff08;
}

.progress{
height:5px;
background:#182131;
border-radius:99px;
margin-top:18px;
overflow:hidden;
}

.progress i{
display:block;
width:20%;
height:100%;
background:#93a6ff;
}

.ai-box{
background:
linear-gradient(135deg,#101a30,#0a0f18);
border:1px solid #5168c855;
border-radius:24px;
padding:25px;
}

.ai-output{
white-space:pre-wrap;
line-height:1.7;
color:#aeb9ca;
margin-top:20px;
}

.footer{
border-top:1px solid #ffffff12;
padding:50px 6%;
color:#697689;
}

.mobile-bottom{
display:none;
}

@keyframes rise{
from{
opacity:0;
transform:translateY(35px)
}
to{
opacity:1;
transform:translateY(0)
}
}

@keyframes pulse{
from{transform:scale(.8);opacity:.3}
to{transform:scale(1.2);opacity:.7}
}

@keyframes scroll{
from{transform:translateX(0)}
to{transform:translateX(-100%)}
}

@media(max-width:750px){

.navlinks{
display:none;
}

.menu{
display:block;
}

.hero{
padding:65px 6%;
min-height:85vh;
}

h1{
letter-spacing:-3px;
}

section{
padding:65px 5%;
}

.mobile-bottom{
display:flex;
position:fixed;
bottom:12px;
left:10px;
right:10px;
z-index:200;
background:#080d15ee;
border:1px solid #ffffff18;
border-radius:18px;
padding:10px;
justify-content:space-around;
backdrop-filter:blur(20px);
}

.mobile-bottom a{
color:#aab6c8;
text-decoration:none;
font-size:10px;
text-align:center;
}

.mobile-bottom b{
display:block;
font-size:17px;
}

}

</style>

<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#00ffd0">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="TW Trades">

</head>

<body>

<nav>

<div class="logo">
TW<span>TRADES</span>
</div>

<div class="navlinks">
<a href="#top">Home</a>
<a href="#terminal">Terminal</a>
<a href="#intelligence">Intelligence</a>
<a href="#titan">Titan X</a>
<a href="#yuki">Yuki</a>
<a href="#academy">Academy</a>
<a href="#request">Access</a>
<a href="/admin">Admin</a>
</div>

<div class="menu">☰</div>

</nav>

<div class="glow"></div>

<!-- HERO -->

<section class="hero" id="top">

<div class="hero-content">

<div class="eyebrow">
TW TRADES • THE AUTONOMY OF SUCCESS
</div>

<h1>
Trade With
<span class="gradient">
Structure.
</span>
</h1>

<p>
A complete trading intelligence ecosystem combining
TW Blueprint execution, fundamental intelligence,
market sentiment, Titan X technology, Yuki AI and
The Autonomy of Success education.
</p>

<div class="buttons">

<a class="btn primary" href="#terminal">
LAUNCH TERMINAL
</a>

<a class="btn" href="#academy">
EXPLORE ACADEMY
</a>

</div>

</div>

</section>

<!-- LIVE TICKER -->

<div class="ticker">
<span>
XAU/USD • EUR/USD • GBP/USD • NASDAQ • US30 •
BTC/USD • ETH/USD • DAX40 • TW BLUEPRINT • TITAN X • YUKI
</span>
</div>

<!-- ECOSYSTEM -->

<section>

<div class="section-head">
<div class="kicker">THE ECOSYSTEM</div>
<h2>One platform. Four intelligence layers.</h2>
<p class="muted">
Everything is connected around one objective:
developing a structured, informed trading process.
</p>
</div>

<div class="cards">

<div class="card big-card">
<div class="icon">◈</div>
<span class="tag">TW BLUEPRINT</span>
<h3>Price Structure</h3>
<p class="muted">
Indication. Correction. Continuation.
Multi-timeframe structure from 4H to 5M.
</p>
</div>

<div class="card big-card">
<div class="icon">✦</div>
<span class="tag">TITAN X</span>
<h3>Market Intelligence</h3>
<p class="muted">
A higher-level intelligence layer connecting
technical structure, market context and
fundamental information.
</p>
</div>

<div class="card big-card">
<div class="icon">◉</div>
<span class="tag">YUKI</span>
<h3>AI Assistant</h3>
<p class="muted">
Your intelligent workspace for understanding
market conditions, setups and educational concepts.
</p>
</div>

<div class="card big-card">
<div class="icon">△</div>
<span class="tag">AUTONOMY</span>
<h3>Education</h3>
<p class="muted">
A structured learning environment for developing
your own market knowledge and decision process.
</p>
</div>

</div>

</section>

<!-- TERMINAL -->

<section id="terminal">

<div class="section-head">
<div class="kicker">LIVE MARKET TERMINAL</div>
<h2>TW Blueprint.</h2>
<p class="muted">
Real market data. Real news. No manufactured signals.
Maximum six qualified setups per day.
</p>
</div>

<div class="terminal">

<div class="term-top">
<div class="dot"></div>
<div class="dot"></div>
<div class="dot"></div>
<strong>TW BLUEPRINT TERMINAL</strong>
</div>

<div class="terminal-body">

<div class="controls">

<button onclick="scan()">
SCAN MARKET
</button>

<button onclick="scanSymbol('XAU/USD')">
GOLD
</button>

<button onclick="scanSymbol('EUR/USD')">
EUR/USD
</button>

<button onclick="scanSymbol('NASDAQ')">
NASDAQ
</button>

<button onclick="scanSymbol('BTC/USD')">
BTC
</button>

</div>

<div id="terminalResults"
class="signal-grid">

<div class="signal">
<strong>READY</strong>
<p class="muted">
Press Scan Market to analyze the current session.
</p>
</div>

</div>

</div>

</div>

</section>

<!-- INTELLIGENCE -->

<section id="intelligence">

<div class="section-head">
<div class="kicker">FUNDAMENTAL INTELLIGENCE</div>
<h2>Understand what moves the market.</h2>
<p class="muted">
Technical structure is only one part of the picture.
TW Trades combines price structure with real news
and entity sentiment.
</p>
</div>

<div class="news" id="news">

<div class="news-item">
<h3>MarketAux Intelligence</h3>
<p class="muted">
Select an instrument to load current financial
news and sentiment.
</p>
</div>

</div>

</section>

<!-- AI -->

<section>

<div class="section-head">
<div class="kicker">AI INTELLIGENCE</div>
<h2>Ask the market a better question.</h2>
</div>

<div class="ai-box">

<strong>TW INTELLIGENCE ANALYST</strong>

<p class="muted">
The AI analyst explains the supplied market evidence.
It does not invent prices or guarantee outcomes.
</p>

<div class="buttons">

<button onclick="runAI()">
ANALYZE CURRENT MARKET
</button>

</div>

<div id="aiOutput"
class="ai-output">
AI analyst waiting for a market scan.
</div>

</div>

</section>

<!-- TITAN X -->

<section id="titan">

<div class="section-head">
<div class="kicker">TITAN X</div>
<h2>The intelligence layer.</h2>
<p class="muted">
Titan X is positioned as the premium market-analysis
system within the TW ecosystem.
</p>
</div>

<div class="cards">

<div class="card">
<h3>Multi-Market Scanner</h3>
<p class="muted">
Forex, gold, indices and crypto in one workspace.
</p>
</div>

<div class="card">
<h3>Confluence Engine</h3>
<p class="muted">
Structure, volatility, session and fundamental
context are evaluated together.
</p>
</div>

<div class="card">
<h3>Market Context</h3>
<p class="muted">
Understand what is happening before focusing
on an individual entry.
</p>
</div>

<div class="card">
<h3>Setup Intelligence</h3>
<p class="muted">
Every qualified setup includes its reasoning,
levels and invalidation framework.
</p>
</div>

</div>

</section>

<!-- YUKI -->

<section id="yuki">

<div class="section-head">
<div class="kicker">YUKI</div>
<h2>Your intelligent workspace.</h2>
<p class="muted">
Yuki can sit alongside the TW Blueprint and Titan X
systems as the conversational intelligence layer.
</p>
</div>

<div class="cards">

<div class="card big-card">
<h3>Market Assistant</h3>
<p class="muted">
Ask questions about structure, sessions,
fundamentals and trading education.
</p>
</div>

<div class="card big-card">
<h3>TW Blueprint Companion</h3>
<p class="muted">
Use the ICC framework as the educational foundation
for interpreting setups.
</p>
</div>

<div class="card big-card">
<h3>Research Workspace</h3>
<p class="muted">
Connect the Yuki API/webhook endpoint through
the administrator configuration when available.
</p>
</div>

</div>

</section>

<!-- ACADEMY -->

<section id="academy" class="academy">

<div class="section-head">

<div class="kicker">
THE AUTONOMY OF SUCCESS
</div>

<h2>Learn. Build. Execute.</h2>

<p class="muted">
A structured trading education system covering
technical analysis, fundamentals, TW Blueprint,
gold, psychology and advanced execution.
</p>

</div>

<div class="cards">

{% for course in courses %}

<div class="card course">

<span class="tag">
{{course.tag}}
</span>

<h3>
{{course.title}}
</h3>

<p class="muted">
{{course.desc}}
</p>

{% for lesson in course.lessons[:5] %}

<span class="lesson">
{{loop.index}}. {{lesson}}
</span>

{% endfor %}

<div class="progress">
<i></i>
</div>

</div>

{% endfor %}

</div>

</section>

<!-- LEARNING SYSTEM -->

<section>

<div class="section-head">

<div class="kicker">
LEARNING DASHBOARD
</div>

<h2>Build your own autonomy.</h2>

</div>

<div class="cards">

<div class="card">
<h3>Course Progress</h3>
<p class="muted">
Track modules and lessons as you develop your
knowledge.
</p>
</div>

<div class="card">
<h3>Trading Journal</h3>
<p class="muted">
Record your setup, reasoning, execution and review.
</p>
</div>

<div class="card">
<h3>Psychology</h3>
<p class="muted">
Build consistency around process rather than
individual outcomes.
</p>
</div>

<div class="card">
<h3>Knowledge Base</h3>
<p class="muted">
Keep your concepts organized from beginner
through advanced levels.
</p>
</div>

</div>

</section>

<footer class="footer">

<strong>TW TRADES</strong>

<p>
TW Blueprint • Titan X • Yuki •
The Autonomy of Success
</p>

<p>
Educational purposes only. Market analysis involves
risk. No signal or AI analysis guarantees a profitable
outcome.
</p>

</footer>

<div class="mobile-bottom">

<a href="#terminal">
<b>⌁</b>
Terminal
</a>

<a href="#intelligence">
<b>◈</b>
News
</a>

<a href="#titan">
<b>✦</b>
Titan X
</a>

<a href="#yuki">
<b>◉</b>
Yuki
</a>

<a href="#academy">
<b>△</b>
Academy
</a>

</div>

<script>

let lastScan=null;

async function scan(){

const box=document.getElementById(
"terminalResults"
);

box.innerHTML=
'<div class="signal">SCANNING REAL DATA...</div>';

try{

const r=await fetch("/api/scan");
const data=await r.json();

lastScan=data;

renderSignals(data.results||[]);

}catch(e){

box.innerHTML=
'<div class="signal">DATA CONNECTION ERROR</div>';

}

}

async function scanSymbol(symbol){

const box=document.getElementById(
"terminalResults"
);

box.innerHTML=
'<div class="signal">ANALYZING '+symbol+'...</div>';

try{

const r=await fetch(
"/api/scan?symbol="+encodeURIComponent(symbol)
);

const data=await r.json();

lastScan={
results:data.status==="QUALIFIED"
?[data]:[]
};

renderSignals(lastScan.results);

loadNews(symbol);

}catch(e){

box.innerHTML=
'<div class="signal">ERROR</div>';

}

}

function renderSignals(results){

const box=document.getElementById(
"terminalResults"
);

if(!results.length){

box.innerHTML=`
<div class="signal">
<h3>NO QUALIFIED SETUPS</h3>
<p class="muted">
TW Blueprint did not find enough
confluence to issue a signal.
</p>
</div>`;

return;

}

box.innerHTML=results.map(x=>`

<div class="signal">

<div>
<strong>${x.symbol}</strong>
<span class="${x.direction==="BUY"?"buy":"sell"}">
${x.direction}
</span>
</div>

<div class="price">
${x.score}/100
</div>

<div class="line">
<span>Session</span>
<b>${x.session}</b>
</div>

<div class="line">
<span>Entry</span>
<b>${x.entry}</b>
</div>

<div class="line">
<span>Stop</span>
<b>${x.stop}</b>
</div>

<div class="line">
<span>TP1</span>
<b>${x.tp1}</b>
</div>

<div class="line">
<span>TP2</span>
<b>${x.tp2}</b>
</div>

<div class="line">
<span>4H</span>
<b>${x.trend4h}</b>
</div>

<div class="line">
<span>1H</span>
<b>${x.trend1h}</b>
</div>

<div class="line">
<span>15M</span>
<b>${x.trend15m}</b>
</div>

<div class="line">
<span>Fundamental</span>
<b>${x.fundamental?.bias||"N/A"}</b>
</div>

<p class="muted">
${(x.reasons||[]).map(r=>"✓ "+r).join("<br>")}
</p>

</div>

`).join("");

}

async function loadNews(symbol){

const r=await fetch(
"/api/news?symbol="+encodeURIComponent(symbol)
);

const data=await r.json();

const box=document.getElementById("news");

if(!data.articles?.length){

box.innerHTML=`
<div class="news-item">
<h3>No current articles</h3>
<p class="muted">
MarketAux returned no matching articles.
</p>
</div>`;

return;

}

box.innerHTML=data.articles.map(a=>`

<div class="news-item">

<span class="tag">
MARKETAUX
</span>

<h3>
<a href="${a.url||"#"}"
target="_blank">
${a.title||"Financial news"}
</a>
</h3>

<p class="muted">
${a.description||a.snippet||""}
</p>

</div>

`).join("");

}

async function runAI(){

const output=document.getElementById(
"aiOutput"
);

if(!lastScan){

output.innerText=
"Run a market scan first.";

return;

}

output.innerText=
"AI ANALYST IS PROCESSING THE MARKET EVIDENCE...";

try{

const r=await fetch(
"/api/ai",
{
method:"POST",
headers:{
"Content-Type":"application/json"
},
body:JSON.stringify(lastScan)
}
);

const data=await r.json();

output.innerText=data.text;

}catch(e){

output.innerText=
"AI connection failed.";

}

}

</script>


<!-- ==========================================================
     TW TRADES PREMIUM PLATFORM UPGRADE
     ========================================================== -->

<section class="tw-upgrade" id="systems">

<div class="tw-upgrade-head">

<span class="tw-badge">TW TRADES INTELLIGENCE ECOSYSTEM</span>

<h2>
Trade With More <span style="color:#00ffd0;">Intelligence.</span>
</h2>

<p>
Access the TW Trades ecosystem built around market intelligence,
technical analysis, fundamental analysis, sentiment, scanning and
the TW Blueprint approach.
</p>

</div>

<div class="tw-package-grid">

<div class="tw-package">

<span class="tw-label">EDUCATION</span>

<h3>TW Trades Mentorship</h3>

<div class="tw-price">
R300 <small style="font-size:14px;color:#8f9daf;">/ month</small>
</div>

<ul>
<li>Technical analysis</li>
<li>Fundamental analysis</li>
<li>Support &amp; resistance</li>
<li>ICC / TW Blueprint education</li>
<li>Trading guidance</li>
</ul>

<a class="tw-package-btn"
href="https://wa.me/27697343252?text=Hi%20Neo%2C%20I%20want%20TW%20Trades%20Mentorship%20for%20R300%20per%20month.">
Request Mentorship
</a>

</div>


<div class="tw-package featured">

<span class="tw-label">PREMIUM SYSTEMS</span>

<h3>Titan X + Yuki</h3>

<div class="tw-price">
R1,500
</div>

<ul>
<li>Titan X intelligence system</li>
<li>Yuki Scanner ecosystem</li>
<li>Real-market intelligence</li>
<li>Technical analysis</li>
<li>Fundamental analysis</li>
<li>Market sentiment intelligence</li>
<li>Scanner and systems access</li>
</ul>

<a class="tw-package-btn primary"
href="https://wa.me/27697343252?text=Hi%20Neo%2C%20I%20want%20TW%20Trades%20Premium%20Systems%20Access%20for%20R1500.">
Request Systems Access
</a>

</div>


<div class="tw-package">

<span class="tw-label">PUBLIC ACCESS</span>

<h3>TW Trades Platform</h3>

<div class="tw-price">
R400
</div>

<ul>
<li>TW Trades platform access</li>
<li>Market dashboard</li>
<li>Live market intelligence</li>
<li>Financial news</li>
<li>Trading tools</li>
<li>TW Trades ecosystem</li>
</ul>

<a class="tw-package-btn"
href="https://wa.me/27693118405?text=Hi%20Neo%2C%20I%20want%20TW%20Trades%20Public%20Access%20for%20R400.">
Request Public Access
</a>

</div>

</div>


<div class="tw-intelligence">

<div class="tw-intel">
<strong>◈ Live Markets</strong>
<span>
Monitor supported forex, metals and other market instruments
through the connected market-data infrastructure.
</span>
</div>

<div class="tw-intel">
<strong>◈ Market News</strong>
<span>
Financial-news intelligence powered by the connected MarketAux
news service.
</span>
</div>

<div class="tw-intel">
<strong>◈ Titan X</strong>
<span>
Premium TW Trades intelligence layer for users with systems access.
</span>
</div>

<div class="tw-intel">
<strong>◈ Yuki Scanner</strong>
<span>
Scanner ecosystem designed to help identify market opportunities
and organize analysis.
</span>
</div>

</div>


<div class="tw-contact-row">

<a class="tw-contact"
href="https://wa.me/27697343252"
target="_blank">
WhatsApp · +27 697 343 252
</a>

<a class="tw-contact"
href="https://wa.me/27693118405"
target="_blank">
WhatsApp · +27 693 118 405
</a>

<a class="tw-contact"
href="https://instagram.com/ashleysnowfx"
target="_blank">
Instagram · @ashleysnowfx
</a>

<a class="tw-contact"
href="https://instagram.com/topwavetradesalltime"
target="_blank">
Instagram · @topwavetradesalltime
</a>

</div>

</section>

<!-- TW TRADES PUBLIC ACCESS -->
<section id="request" style="
margin:60px auto;
max-width:1100px;
padding:45px 25px;
border:1px solid rgba(0,255,200,.25);
border-radius:28px;
background:linear-gradient(135deg,rgba(8,18,30,.98),rgba(5,10,20,.98));
box-shadow:0 0 45px rgba(0,255,200,.08);
text-align:center;
">
<div style="font-size:13px;letter-spacing:3px;color:#00ffd0;font-weight:800;">
TW TRADES PUBLIC ACCESS
</div>

<h2 style="font-size:42px;margin:12px 0 8px;">
PUBLIC ACCESS — <span style="color:#00ffd0;">R400</span>
</h2>

<p style="max-width:700px;margin:0 auto 25px;color:#aab7c8;line-height:1.7;">
Request access to the TW Trades ecosystem and receive the instructions directly through WhatsApp.
</p>

<a href="https://wa.me/27697343252?text=Hi%20Neo%2C%20I%20want%20to%20request%20TW%20Trades%20Public%20Access%20for%20R400.%20Please%20send%20me%20the%20payment%20and%20access%20instructions."
style="
display:inline-block;
padding:16px 32px;
border-radius:14px;
background:#00ffd0;
color:#03100e;
font-weight:900;
text-decoration:none;
margin:8px;
box-shadow:0 0 25px rgba(0,255,208,.25);
">
REQUEST ACCESS — R400
</a>

<div style="margin-top:28px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
<a href="https://instagram.com/ashleysnowfx"
target="_blank"
style="padding:12px 20px;border:1px solid #29384b;border-radius:12px;color:#fff;text-decoration:none;">
Instagram · @ashleysnowfx
</a>

<a href="https://tiktok.com/@snowFx3"
target="_blank"
style="padding:12px 20px;border:1px solid #29384b;border-radius:12px;color:#fff;text-decoration:none;">
TikTok · @snowFx3
</a>
</div>
</section>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(
        PAGE,
        courses=COURSES
    )

@app.route("/health")
def health():
    return jsonify({
        "status":"ok",
        "platform":"TW Trades",
        "blueprint":"TW Blueprint",
        "titan":"Titan X",
        "yuki":"Yuki",
        "academy":"The Autonomy of Success",
        "daily_signal_limit":6
    })

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
