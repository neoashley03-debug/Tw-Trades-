import os
import json
import sqlite3
import urllib.parse
import urllib.request
import statistics
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
DB = "twtrades.db"

# ---------------------------------------------------------
# DEFAULT SETTINGS
# ---------------------------------------------------------

DEFAULT_ADMIN_EMAIL = "admin@twtrades.local"
DEFAULT_ADMIN_PASSWORD = "ChangeMe123!"

DEFAULT_OWNER_EMAIL = "neoashley03@gmail.com"
DEFAULT_INSTAGRAM = "@ashleysnowfx"
DEFAULT_WHATSAPP = ""

PLANS = {
    "TW Trades Mentorship": 300,
    "Titan X": 1500,
    "Titan X + Yuki": 2500
}

WATCHLIST = [
    "XAU/USD",
    "XAG/USD",
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
    "GBP/JPY",
    "EUR/JPY",
    "EUR/AUD",
    "GBP/AUD",
    "NAS100",
    "US30"
]

SYMBOL_MAP = {
    "XAU/USD": "XAU/USD",
    "XAG/USD": "XAG/USD",
    "EUR/USD": "EUR/USD",
    "GBP/USD": "GBP/USD",
    "USD/JPY": "USD/JPY",
    "GBP/JPY": "GBP/JPY",
    "EUR/JPY": "EUR/JPY",
    "EUR/AUD": "EUR/AUD",
    "GBP/AUD": "GBP/AUD",
    "NAS100": "IXIC",
    "US30": "DJI"
}

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = get_db()

    con.executescript("""
    CREATE TABLE IF NOT EXISTS settings(
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS visitors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        whatsapp TEXT,
        instagram TEXT,
        tiktok TEXT,
        experience TEXT,
        created TEXT
    );

    CREATE TABLE IF NOT EXISTS payments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        visitor_id INTEGER,
        email TEXT,
        plan TEXT,
        reference TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created TEXT
    );

    CREATE TABLE IF NOT EXISTS journal(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        direction TEXT,
        entry REAL,
        sl REAL,
        tp1 REAL,
        tp2 REAL,
        notes TEXT,
        created TEXT
    );
    """)

    defaults = {
        "owner_email": DEFAULT_OWNER_EMAIL,
        "owner_instagram": DEFAULT_INSTAGRAM,
        "owner_whatsapp": DEFAULT_WHATSAPP,
        "twelve_data_key": "",
        "news_api_key": ""
    }

    for key, value in defaults.items():
        con.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (key, value)
        )

    con.commit()
    con.close()

init_db()

# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def setting(key, default=""):
    con = get_db()
    row = con.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    con.close()

    if row:
        return row["value"]

    return default

def save_setting(key, value):
    con = get_db()
    con.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
        (key, value)
    )
    con.commit()
    con.close()

def now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

def esc(value):
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def form_value(form, key):
    return form.get(key, [""])[0].strip()

def parse_form(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length).decode("utf-8")
    return urllib.parse.parse_qs(raw)

def html(handler, content, code=200):
    data = content.encode("utf-8")

    handler.send_response(code)
    handler.send_header(
        "Content-Type",
        "text/html; charset=utf-8"
    )
    handler.send_header(
        "Content-Length",
        str(len(data))
    )
    handler.end_headers()
    handler.wfile.write(data)

def json_out(handler, data, code=200):
    raw = json.dumps(data).encode("utf-8")

    handler.send_response(code)
    handler.send_header(
        "Content-Type",
        "application/json"
    )
    handler.send_header(
        "Content-Length",
        str(len(raw))
    )
    handler.end_headers()
    handler.wfile.write(raw)

# ---------------------------------------------------------
# CONTACT LINKS
# ---------------------------------------------------------

def clean_whatsapp(number):
    """
    Converts common South African formats into
    WhatsApp international format.
    """
    n = "".join(c for c in number if c.isdigit() or c == "+")

    if n.startswith("+"):
        return n[1:]

    if n.startswith("27"):
        return n

    if n.startswith("0"):
        return "27" + n[1:]

    return n

def whatsapp_link(customer=None):
    owner = clean_whatsapp(
        setting("owner_whatsapp", DEFAULT_WHATSAPP)
    )

    if not owner:
        return "#"

    if customer:
        message = (
            "TW TRADES ACCESS REQUEST\n\n"
            f"Name: {customer.get('name','')}\n"
            f"Email: {customer.get('email','')}\n"
            f"Customer WhatsApp: {customer.get('whatsapp','')}\n"
            f"Instagram: {customer.get('instagram','')}\n"
            f"TikTok: {customer.get('tiktok','')}\n"
            f"Trading Experience: {customer.get('experience','')}\n"
            f"Package: {customer.get('plan','')}\n"
            f"Payment Reference: {customer.get('reference','')}\n"
            f"Amount: R{customer.get('amount','')}\n\n"
            "Please assist this customer with their TW Trades access."
        )
    else:
        message = (
            "Hi TW Trades, I would like to learn more "
            "about your trading services."
        )

    return (
        "https://wa.me/"
        + owner
        + "?text="
        + urllib.parse.quote(message)
    )

def instagram_link():
    handle = setting(
        "owner_instagram",
        DEFAULT_INSTAGRAM
    ).strip()

    handle = handle.replace("@", "").strip()

    if not handle:
        return "#"

    return "https://instagram.com/" + urllib.parse.quote(handle)

def email_link(customer=None):
    owner = setting(
        "owner_email",
        DEFAULT_OWNER_EMAIL
    ).strip()

    if customer:
        subject = (
            "TW Trades Access Request - "
            + customer.get("name", "")
        )

        body = (
            "TW TRADES ACCESS REQUEST\n\n"
            f"Name: {customer.get('name','')}\n"
            f"Email: {customer.get('email','')}\n"
            f"WhatsApp: {customer.get('whatsapp','')}\n"
            f"Instagram: {customer.get('instagram','')}\n"
            f"TikTok: {customer.get('tiktok','')}\n"
            f"Trading Experience: {customer.get('experience','')}\n"
            f"Package: {customer.get('plan','')}\n"
            f"Payment Reference: {customer.get('reference','')}\n"
            f"Amount: R{customer.get('amount','')}\n"
        )
    else:
        subject = "TW Trades Enquiry"
        body = "Hi Neo, I would like to enquire about TW Trades."

    return (
        "mailto:"
        + urllib.parse.quote(owner)
        + "?subject="
        + urllib.parse.quote(subject)
        + "&body="
        + urllib.parse.quote(body)
    )

# ---------------------------------------------------------
# TWELVE DATA
# ---------------------------------------------------------

def twelve(endpoint, params):
    key = setting("twelve_data_key")

    if not key:
        return None

    params = dict(params)
    params["apikey"] = key

    url = (
        "https://api.twelvedata.com/"
        + endpoint
        + "?"
        + urllib.parse.urlencode(params)
    )

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "TW-Trades/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=12
        ) as response:

            return json.loads(
                response.read().decode()
            )

    except Exception as error:
        return {
            "status": "error",
            "message": str(error)
        }

def get_quote(symbol):
    mapped = SYMBOL_MAP.get(symbol, symbol)

    data = twelve(
        "quote",
        {"symbol": mapped}
    )

    if not data or "close" not in data:
        return {
            "symbol": symbol,
            "available": False,
            "price": None,
            "change": None
        }

    try:
        price = float(data["close"])
        change = float(
            data.get("percent_change", 0)
        )
    except Exception:
        return {
            "symbol": symbol,
            "available": False,
            "price": None,
            "change": None
        }

    return {
        "symbol": symbol,
        "available": True,
        "price": price,
        "change": change,
        "open": data.get("open"),
        "high": data.get("high"),
        "low": data.get("low")
    }

def get_candles(symbol, interval="5min", size=150):
    mapped = SYMBOL_MAP.get(symbol, symbol)

    data = twelve(
        "time_series",
        {
            "symbol": mapped,
            "interval": interval,
            "outputsize": size
        }
    )

    if not data or "values" not in data:
        return []

    result = []

    for candle in reversed(data["values"]):
        try:
            result.append({
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(
                    candle.get("volume", 0) or 0
                )
            })
        except Exception:
            continue

    return result

# ---------------------------------------------------------
# TECHNICAL ANALYSIS
# ---------------------------------------------------------

def calculate_ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)

    result = statistics.mean(
        values[:period]
    )

    for value in values[period:]:
        result = (
            value * multiplier
            + result * (1 - multiplier)
        )

    return result

def calculate_rsi(values, period=14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        difference = (
            values[i] - values[i - 1]
        )

        gains.append(max(difference, 0))
        losses.append(max(-difference, 0))

    average_gain = statistics.mean(
        gains[:period]
    )

    average_loss = statistics.mean(
        losses[:period]
    )

    for i in range(period, len(gains)):
        average_gain = (
            (average_gain * (period - 1))
            + gains[i]
        ) / period

        average_loss = (
            (average_loss * (period - 1))
            + losses[i]
        ) / period

    if average_loss == 0:
        return 100

    relative_strength = (
        average_gain / average_loss
    )

    return 100 - (
        100 / (1 + relative_strength)
    )

def calculate_atr(data, period=14):
    if len(data) < period + 1:
        return None

    ranges = []

    for i in range(1, len(data)):
        high = data[i]["high"]
        low = data[i]["low"]
        previous_close = data[i - 1]["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close)
        )

        ranges.append(true_range)

    return statistics.mean(
        ranges[-period:]
    )

def structure(data):
    if len(data) < 10:
        return "UNKNOWN"

    recent = data[-10:]

    highs = [
        candle["high"]
        for candle in recent
    ]

    lows = [
        candle["low"]
        for candle in recent
    ]

    if (
        highs[-1] > highs[0]
        and lows[-1] > lows[0]
    ):
        return "BULLISH STRUCTURE"

    if (
        highs[-1] < highs[0]
        and lows[-1] < lows[0]
    ):
        return "BEARISH STRUCTURE"

    return "RANGE / TRANSITION"

def analyze_symbol(symbol):
    d5 = get_candles(symbol, "5min")
    d15 = get_candles(symbol, "15min")
    d1 = get_candles(symbol, "1h")
    d4 = get_candles(symbol, "4h")

    if not d5:
        return {
            "available": False,
            "symbol": symbol,
            "status": "DATA UNAVAILABLE"
        }

    closes = [
        candle["close"]
        for candle in d5
    ]

    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    r = calculate_rsi(closes)
    a = calculate_atr(d5)

    price = closes[-1]

    if (
        ema20
        and ema50
        and price > ema20 > ema50
    ):
        trend = "BULLISH"

    elif (
        ema20
        and ema50
        and price < ema20 < ema50
    ):
        trend = "BEARISH"

    else:
        trend = "MIXED"

    st = structure(d5)

    support = min(
        candle["low"]
        for candle in d5[-30:]
    )

    resistance = max(
        candle["high"]
        for candle in d5[-30:]
    )

    return {
        "available": True,
        "symbol": symbol,
        "price": price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": r,
        "atr": a,
        "trend": trend,
        "structure": st,
        "support": support,
        "resistance": resistance,
        "mtf": {
            "5M": structure(d5),
            "15M": structure(d15) if d15 else "UNAVAILABLE",
            "1H": structure(d1) if d1 else "UNAVAILABLE",
            "4H": structure(d4) if d4 else "UNAVAILABLE"
        }
    }

# ---------------------------------------------------------
# TITAN X ENGINE
# ---------------------------------------------------------

def titan(symbol):
    data = analyze_symbol(symbol)

    if not data.get("available"):
        return {
            "symbol": symbol,
            "status": "DATA UNAVAILABLE",
            "score": 0
        }

    score = 0

    if data["trend"] == "BULLISH":
        score += 25
    elif data["trend"] == "BEARISH":
        score -= 25

    if data["structure"] == "BULLISH STRUCTURE":
        score += 20
    elif data["structure"] == "BEARISH STRUCTURE":
        score -= 20

    rsi = data.get("rsi") or 50

    if rsi > 55:
        score += 15
    elif rsi < 45:
        score -= 15

    mtf = data["mtf"]

    bullish = sum(
        1
        for value in mtf.values()
        if "BULLISH" in value
    )

    bearish = sum(
        1
        for value in mtf.values()
        if "BEARISH" in value
    )

    score += bullish * 10
    score -= bearish * 10

    if score >= 45:
        status = "BUY WATCH"
        direction = "BUY"

    elif score <= -45:
        status = "SELL WATCH"
        direction = "SELL"

    else:
        status = "WAIT"
        direction = "NEUTRAL"

    price = data["price"]
    atr = data.get("atr") or 0

    if direction == "BUY":
        entry = price
        sl = price - atr * 1.5
        tp1 = price + atr * 2
        tp2 = price + atr * 3

    elif direction == "SELL":
        entry = price
        sl = price + atr * 1.5
        tp1 = price - atr * 2
        tp2 = price - atr * 3

    else:
        entry = None
        sl = None
        tp1 = None
        tp2 = None

    return {
        **data,
        "score": score,
        "status": status,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "blueprint": {
            "range": "4H range / no-trade assessment",
            "indication": "Break of structure / displacement",
            "correction": "Retest / correction",
            "continuation": "Confirmation toward directional target"
        },
        "institutional_style": {
            "liquidity": "Observable liquidity zones",
            "displacement": "Momentum expansion",
            "regime": "Trend / range classification",
            "order_flow": "No privileged institutional order-flow feed"
        }
    }

# ---------------------------------------------------------
# CSS
# ---------------------------------------------------------

CSS = r"""
:root{
--bg:#05070b;
--panel:#0c1119;
--panel2:#111823;
--gold:#d9ad48;
--text:#f3f5f8;
--muted:#8e9aaa;
--green:#38dc91;
--red:#ff5e6c;
--border:#202a38;
}

*{box-sizing:border-box}

body{
margin:0;
background:
radial-gradient(circle at top,#18202d 0,#05070b 50%);
color:var(--text);
font-family:Arial,Helvetica,sans-serif;
}

header{
padding:17px 22px;
display:flex;
justify-content:space-between;
align-items:center;
border-bottom:1px solid var(--border);
background:rgba(5,7,11,.94);
position:sticky;
top:0;
z-index:100;
backdrop-filter:blur(12px);
}

.logo{
font-weight:900;
font-size:22px;
letter-spacing:1px;
}

.logo span{color:var(--gold)}

nav a{
color:#c9d1dc;
text-decoration:none;
font-size:13px;
margin-left:13px;
}

.container{
max-width:1450px;
margin:auto;
padding:25px;
}

.hero{
padding:55px 5px 40px;
}

.badge{
display:inline-block;
border:1px solid #4d3c18;
color:var(--gold);
border-radius:30px;
padding:7px 12px;
font-size:11px;
font-weight:800;
letter-spacing:.7px;
}

h1{
font-size:clamp(36px,6vw,72px);
line-height:.98;
margin:16px 0;
}

h2{margin-top:0}

p{
line-height:1.6;
}

.muted,.small{
color:var(--muted);
}

.small{
font-size:12px;
}

.grid{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
gap:16px;
}

.card{
background:linear-gradient(145deg,var(--panel),#080c12);
border:1px solid var(--border);
border-radius:15px;
padding:20px;
box-shadow:0 12px 35px rgba(0,0,0,.25);
}

.price{
font-size:31px;
font-weight:900;
color:var(--gold);
margin:14px 0;
}

.btn{
display:inline-block;
padding:12px 17px;
border-radius:9px;
border:1px solid var(--border);
background:#141b25;
color:#fff;
text-decoration:none;
font-weight:800;
cursor:pointer;
margin:4px;
}

.btn.gold{
background:var(--gold);
color:#07090c;
border-color:var(--gold);
}

.btn.green{
background:var(--green);
color:#061009;
border-color:var(--green);
}

input,select,textarea{
width:100%;
padding:12px;
background:#070b11;
color:#fff;
border:1px solid var(--border);
border-radius:8px;
margin:6px 0 13px;
}

label{
font-size:12px;
color:#adb7c5;
}

table{
width:100%;
border-collapse:collapse;
font-size:12px;
}

th,td{
padding:10px;
border-bottom:1px solid var(--border);
text-align:left;
vertical-align:top;
}

th{color:var(--gold)}

.heat{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(145px,1fr));
gap:9px;
}

.heatbox{
padding:15px;
background:#101722;
border:1px solid var(--border);
border-radius:10px;
}

.gauge{
height:10px;
background:#202833;
border-radius:20px;
overflow:hidden;
}

.gauge i{
display:block;
height:100%;
background:linear-gradient(
90deg,
var(--red),
var(--gold),
var(--green)
);
}

.map{
height:470px;
border:1px solid var(--border);
border-radius:14px;
overflow:hidden;
}

.status{
font-weight:900;
}

.success{
border-color:var(--green);
}

.danger{
border-color:var(--red);
}

@media(max-width:700px){
header{
position:relative;
align-items:flex-start;
}
nav{
line-height:2;
}
.container{
padding:15px;
}
}
"""

# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

def home_page():
    cards = ""

    for name, amount in PLANS.items():

        if name == "TW Trades Mentorship":
            description = (
                "Trading education, TW Blueprint and "
                "structured mentorship."
            )

        elif name == "Titan X":
            description = (
                "Market intelligence, technical analysis, "
                "multi-timeframe scanning and Titan X."
            )

        else:
            description = (
                "Titan X plus access to the Yuki AI workspace."
            )

        cards += f"""
        <div class="card">
            <div class="small">TW TRADES</div>
            <h2>{esc(name)}</h2>
            <div class="price">
                R{amount:,}<span class="small"> / month</span>
            </div>
            <p class="muted">{description}</p>
            <a class="btn gold"
               href="/access?plan={urllib.parse.quote(name)}">
               Get Access
            </a>
        </div>
        """

    wa = whatsapp_link()
    ig = instagram_link()
    email = email_link()

    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>TW Trades Intelligence</title>
<style>{CSS}</style>
</head>

<body>

<header>
<div class="logo">TW <span>TRADES</span></div>

<nav>
<a href="/">Home</a>
<a href="/terminal">Terminal</a>
<a href="/market">Market</a>
<a href="/journal">Journal</a>
<a href="/admin">Admin</a>
</nav>
</header>

<div class="container">

<section class="hero">

<div class="badge">
TW TRADES INTELLIGENCE PLATFORM
</div>

<h1>
Structured market intelligence.
</h1>

<p class="muted" style="max-width:850px;font-size:17px">
Titan X combines observable market data, multi-timeframe
technical analysis, TW Blueprint / ICC logic, volatility,
market structure and contextual market information.
</p>

<a class="btn gold" href="#plans">
View Packages
</a>

<a class="btn" href="/terminal">
Open Terminal
</a>

</section>

<section id="plans">

<h2>Packages</h2>

<div class="grid">
{cards}
</div>

</section>

<br>

<div class="grid">

<div class="card">
<h2>Titan X</h2>
<p class="muted">
Multi-timeframe market analysis using live data when
the configured market-data provider is available.
</p>
</div>

<div class="card">
<h2>TW Blueprint</h2>
<p class="muted">
4H range → indication → correction → continuation,
with lower-timeframe confirmation.
</p>
</div>

<div class="card">
<h2>Yuki</h2>
<p class="muted">
Available with the Titan X + Yuki package.
</p>
<a class="btn"
href="https://yuki-core-os.base44.app"
target="_blank">
Open Yuki
</a>
</div>

<div class="card">
<h2>Contact TW Trades</h2>

<a class="btn green"
href="{esc(wa)}"
target="_blank">
WhatsApp
</a>

<a class="btn"
href="{esc(ig)}"
target="_blank">
Instagram
</a>

<a class="btn"
href="{esc(email)}">
Email
</a>

</div>

</div>

<br>

<div class="card">
<p class="small">
Trading involves risk. Titan X provides analytical information
and does not guarantee profits or future market outcomes.
</p>
</div>

</div>

</body>
</html>
"""

# ---------------------------------------------------------
# ACCESS FORM
# ---------------------------------------------------------

def access_page(plan):

    if plan not in PLANS:
        return """
        <html><body style="background:#05070b;color:white">
        <h2>Invalid package.</h2>
        <a href="/">Return</a>
        </body></html>
        """

    amount = PLANS[plan]

    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>TW Trades Access</title>
<style>{CSS}</style>
</head>

<body>

<header>
<div class="logo">TW <span>TRADES</span></div>
<a class="btn" href="/">Back</a>
</header>

<div class="container">

<div class="card"
style="max-width:720px;margin:30px auto">

<div class="badge">ACCESS REQUEST</div>

<h1 style="font-size:43px">
Connect with TW Trades
</h1>

<p class="muted">
Package:
<strong>{esc(plan)}</strong>
<br>
Price:
<strong style="color:var(--gold)">
R{amount:,} / month
</strong>
</p>

<form method="POST"
action="/access">

<input type="hidden"
name="plan"
value="{esc(plan)}">

<label>Full Name *</label>
<input name="name"
required
placeholder="Your full name">

<label>Email *</label>
<input type="email"
name="email"
required
placeholder="you@example.com">

<label>WhatsApp Number *</label>
<input name="whatsapp"
required
placeholder="+27...">

<label>Instagram</label>
<input name="instagram"
placeholder="@username">

<label>TikTok</label>
<input name="tiktok"
placeholder="@username">

<label>Trading Experience</label>
<select name="experience">
<option>Beginner</option>
<option>Less than 1 year</option>
<option>1–3 years</option>
<option>3–5 years</option>
<option>5+ years</option>
</select>

<label>Payment Reference</label>
<input name="reference"
placeholder="Payment reference if already paid">

<button class="btn gold"
type="submit">
Submit Access Request
</button>

</form>

<p class="small">
Your details are stored securely in the local TW Trades
database so the owner can follow up with you.
</p>

</div>
</div>

</body>
</html>
"""

# ---------------------------------------------------------
# SUCCESS
# ---------------------------------------------------------

def success_page():
    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport"
content="width=device-width,initial-scale=1">
<style>{CSS}</style>
<title>Request Received</title>
</head>

<body>

<div class="container">

<div class="card success"
style="max-width:650px;margin:70px auto;text-align:center">

<div class="badge">REQUEST RECEIVED</div>

<h1 style="font-size:45px">
Thank you.
</h1>

<p class="muted">
Your access request has been saved.
TW Trades can now follow up using the
contact information you provided.
</p>

<a class="btn gold" href="/">
Return to Website
</a>

</div>

</div>

</body>
</html>
"""

# ---------------------------------------------------------
# MARKET
# ---------------------------------------------------------

def market_page():

    cards = ""

    for symbol in WATCHLIST:

        q = get_quote(symbol)

        if q["available"]:

            change = q["change"] or 0

            color = (
                "var(--green)"
                if change >= 0
                else "var(--red)"
            )

            cards += f"""
            <div class="heatbox">
                <strong>{esc(symbol)}</strong>

                <div style="font-size:21px;margin-top:8px">
                    {q['price']}
                </div>

                <div style="color:{color}">
                    {change:.2f}%
                </div>
            </div>
            """

        else:

            cards += f"""
            <div class="heatbox">
                <strong>{esc(symbol)}</strong>
                <div class="small">
                    DATA UNAVAILABLE
                </div>
            </div>
            """

    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>TW Trades Market</title>
<style>{CSS}</style>
</head>

<body>

<header>
<div class="logo">TW <span>TRADES MARKET</span></div>
<nav>
<a href="/">Home</a>
<a href="/terminal">Terminal</a>
<a href="/journal">Journal</a>
<a href="/admin">Admin</a>
</nav>
</header>

<div class="container">

<h1 style="font-size:48px">
Market Heatmap
</h1>

<p class="muted">
Live market prices appear when a valid Twelve Data API key
is configured under Admin Settings.
</p>

<div class="heat">
{cards}
</div>

<br>

<div class="grid">

<div class="card">
<h2>Market Gauge</h2>
<p class="small">
Trend / momentum / volatility framework
</p>
<div class="gauge">
<i style="width:67%"></i>
</div>
</div>

<div class="card">
<h2>Volatility</h2>
<p class="small">
Titan X calculates ATR-based volatility when sufficient
candle data is available.
</p>
</div>

<div class="card">
<h2>Geopolitical Context</h2>
<p class="small">
The map is a market-context workspace. Live geopolitical
events require a real configured news/event provider.
No events are fabricated.
</p>
</div>

</div>

</div>

</body>
</html>
"""

# ---------------------------------------------------------
# TERMINAL
# ---------------------------------------------------------

def terminal_page():

    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>TW Trades Terminal</title>
<style>{CSS}</style>

<link rel="stylesheet"
href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">

</head>

<body>

<header>
<div class="logo">
TW <span>TRADES TERMINAL</span>
</div>

<nav>
<a href="/">Home</a>
<a href="/market">Market</a>
<a href="/journal">Journal</a>
<a href="/admin">Admin</a>
</nav>
</header>

<div class="container">

<h1 style="font-size:48px">
Intelligence Terminal
</h1>

<div class="grid">

<div class="card">

<h2>Live Watchlist</h2>

<div id="watch">
Loading...
</div>

</div>

<div class="card">

<h2>Titan X Scanner</h2>

<div id="scanner">
Scanning...
</div>

</div>

<div class="card">

<h2>TW Blueprint / ICC</h2>

<p class="small">
<strong>1. RANGE</strong><br>
Identify the 4H trading/no-trade environment.
</p>

<p class="small">
<strong>2. INDICATION</strong><br>
Break of structure / displacement.
</p>

<p class="small">
<strong>3. CORRECTION</strong><br>
Retest or structured correction.
</p>

<p class="small">
<strong>4. CONTINUATION</strong><br>
Lower-timeframe confirmation.
</p>

</div>

<div class="card">

<h2>Institutional-Style Layer</h2>

<p class="small">
Liquidity<br>
Displacement<br>
Market regime<br>
Multi-timeframe alignment<br>
Volatility<br>
Structure
</p>

<p class="small">
This uses observable market data. It does not claim
access to proprietary institutional order flow.
</p>

</div>

</div>

<br>

<div class="card">

<h2>Geopolitical Market Map</h2>

<div id="map" class="map"></div>

<p class="small">
Regional reference visualization only. Live event information
must come from an actual news/event provider.
</p>

</div>

<br>

<div class="card">

<h2>Yuki</h2>

<p class="muted">
Open the Yuki workspace from here.
A true backend integration requires a Yuki API endpoint
and authentication.
</p>

<a class="btn gold"
href="https://yuki-core-os.base44.app"
target="_blank">
Open Yuki
</a>

</div>

</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>

<script>

async function loadScanner(){

try{

const response = await fetch('/api/scan');
const data = await response.json();

let watch = "";
let scanner = "";

for(const x of data){

watch += `
<div style="
padding:10px 0;
border-bottom:1px solid #202a38
">
<strong>${x.symbol}</strong>

<span style="float:right">
${x.price ?? "N/A"}
</span>

<br>

<span class="small">
${x.change !== null &&
 x.change !== undefined
 ? x.change.toFixed(2)+"%"
 : "No live quote"}
</span>
</div>
`;

scanner += `
<div style="
padding:10px 0;
border-bottom:1px solid #202a38
">

<strong>${x.symbol}</strong>

<br>

<span class="status">
${x.status || "WAIT"}
</span>

<br>

<span class="small">
Score: ${x.score ?? 0}
</span>

</div>
`;

}

document.getElementById("watch").innerHTML = watch;
document.getElementById("scanner").innerHTML = scanner;

}catch(error){

document.getElementById("watch").innerHTML =
"Market data unavailable.";

document.getElementById("scanner").innerHTML =
"Scanner unavailable.";

}

}

loadScanner();

const map = L.map("map").setView([15,20],2);

L.tileLayer(
"https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
{
attribution:"© OpenStreetMap contributors"
}
).addTo(map);

const regions = [
["North America",40,-100],
["Europe",50,10],
["Middle East",29,45],
["Asia",35,105],
["Africa",0,20],
["South America",-15,-60]
];

regions.forEach(region => {

L.marker([region[1],region[2]])
.addTo(map)
.bindPopup(region[0]+" market region");

});

</script>

</body>
</html>
"""

# ---------------------------------------------------------
# JOURNAL
# ---------------------------------------------------------

def journal_page():

    con = get_db()

    rows = con.execute(
        "SELECT * FROM journal "
        "ORDER BY id DESC LIMIT 50"
    ).fetchall()

    con.close()

    table = ""

    for row in rows:

        table += f"""
        <tr>
        <td>{esc(row['created'])}</td>
        <td>{esc(row['symbol'])}</td>
        <td>{esc(row['direction'])}</td>
        <td>{row['entry']}</td>
        <td>{row['sl']}</td>
        <td>{row['tp1']}</td>
        <td>{row['tp2']}</td>
        <td>{esc(row['notes'])}</td>
        </tr>
        """

    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>TW Trades Journal</title>
<style>{CSS}</style>
</head>

<body>

<header>
<div class="logo">
TW <span>TRADES JOURNAL</span>
</div>
<a href="/" class="btn">Home</a>
</header>

<div class="container">

<div class="card">

<h1 style="font-size:45px">
Trade Journal
</h1>

<form method="POST"
action="/journal">

<label>Symbol</label>
<input name="symbol"
placeholder="XAU/USD"
required>

<label>Direction</label>
<select name="direction">
<option>BUY</option>
<option>SELL</option>
</select>

<label>Entry</label>
<input name="entry"
type="number"
step="any"
required>

<label>Stop Loss</label>
<input name="sl"
type="number"
step="any"
required>

<label>TP1</label>
<input name="tp1"
type="number"
step="any">

<label>TP2</label>
<input name="tp2"
type="number"
step="any">

<label>Notes</label>
<textarea name="notes"
rows="4"></textarea>

<button class="btn gold">
Save Trade
</button>

</form>

</div>

<br>

<div class="card"
style="overflow:auto">

<h2>Recent Trades</h2>

<table>

<tr>
<th>Date</th>
<th>Symbol</th>
<th>Direction</th>
<th>Entry</th>
<th>SL</th>
<th>TP1</th>
<th>TP2</th>
<th>Notes</th>
</tr>

{table}

</table>

</div>

</div>

</body>
</html>
"""

# ---------------------------------------------------------
# ADMIN
# ---------------------------------------------------------

def admin_page(message=""):

    con = get_db()

    visitors = con.execute(
        "SELECT * FROM visitors "
        "ORDER BY id DESC"
    ).fetchall()

    payments = con.execute(
        "SELECT * FROM payments "
        "ORDER BY id DESC"
    ).fetchall()

    con.close()

    owner_email = setting(
        "owner_email",
        DEFAULT_OWNER_EMAIL
    )

    owner_instagram = setting(
        "owner_instagram",
        DEFAULT_INSTAGRAM
    )

    owner_whatsapp = setting(
        "owner_whatsapp",
        DEFAULT_WHATSAPP
    )

    visitor_rows = ""

    for v in visitors:

        visitor_rows += f"""
        <tr>

        <td>
        <strong>{esc(v['name'])}</strong>
        </td>

        <td>
        <a href="{esc(email_link({
            'name':v['name'],
            'email':v['email'],
            'whatsapp':v['whatsapp'],
            'instagram':v['instagram'],
            'tiktok':v['tiktok'],
            'experience':v['experience'],
            'plan':'',
            'reference':'',
            'amount':''
        }))}">
        {esc(v['email'])}
        </a>
        </td>

        <td>
        {esc(v['whatsapp'])}
        </td>

        <td>
        {esc(v['instagram'])}
        </td>

        <td>
        {esc(v['tiktok'])}
        </td>

        <td>
        {esc(v['experience'])}
        </td>

        <td>
        {esc(v['created'])}
        </td>

        </tr>
        """

    payment_rows = ""

    for p in payments:

        visitor = con.execute(
            "SELECT * FROM visitors "
            "WHERE id=?",
            (p["visitor_id"],)
        ).fetchone()

        customer = {
            "name": visitor["name"] if visitor else "",
            "email": p["email"],
            "whatsapp": visitor["whatsapp"] if visitor else "",
            "instagram": visitor["instagram"] if visitor else "",
            "tiktok": visitor["tiktok"] if visitor else "",
            "experience": visitor["experience"] if visitor else "",
            "plan": p["plan"],
            "reference": p["reference"],
            "amount": p["amount"]
        }

        wa = whatsapp_link(customer)
        mail = email_link(customer)

        payment_rows += f"""
        <tr>

        <td>{p['id']}</td>

        <td>
        {esc(p['email'])}
        </td>

        <td>
        {esc(p['plan'])}
        </td>

        <td>
        R{p['amount']:,.0f}
        </td>

        <td>
        {esc(p['reference'])}
        </td>

        <td>
        {esc(p['status'])}
        </td>

        <td>
        {esc(p['created'])}
        </td>

        <td>

        <a class="btn green"
           href="{esc(wa)}"
           target="_blank">
           WhatsApp
        </a>

        <a class="btn"
           href="{esc(mail)}">
           Email
        </a>

        </td>

        </tr>
        """

    td_status = (
        "Configured"
        if setting("twelve_data_key")
        else "Not configured"
    )

    news_status = (
        "Configured"
        if setting("news_api_key")
        else "Not configured"
    )

    return f"""
<!doctype html>
<html>
<head>
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>TW Trades Admin</title>
<style>{CSS}</style>
</head>

<body>

<header>

<div class="logo">
TW <span>TRADES ADMIN</span>
</div>

<a class="btn" href="/">
Website
</a>

</header>

<div class="container">

<div class="badge">
ADMIN CONTROL CENTER
</div>

<h1 style="font-size:50px">
Dashboard
</h1>

{f'''
<div class="card success">
{esc(message)}
</div>
<br>
''' if message else ""}

<!-- OWNER CONTACT SETTINGS -->

<div class="card">

<h2>Owner Contact Settings</h2>

<p class="muted">
These details control the public contact buttons and
the WhatsApp / Email actions inside the Admin dashboard.
</p>

<form method="POST"
action="/admin/contact">

<label>Your WhatsApp Number</label>

<input
name="owner_whatsapp"
value="{esc(owner_whatsapp)}"
placeholder="+27XXXXXXXXX">

<p class="small">
Enter your number in international format where possible,
for example +27XXXXXXXXX.
</p>

<label>Your Instagram</label>

<input
name="owner_instagram"
value="{esc(owner_instagram)}"
placeholder="@yourusername">

<label>Your Email</label>

<input
type="email"
name="owner_email"
value="{esc(owner_email)}"
placeholder="you@example.com">

<button class="btn gold">
Save Contact Settings
</button>

</form>

</div>

<br>

<!-- API SETTINGS -->

<div class="grid">

<div class="card">

<h2>Twelve Data</h2>

<p class="status">
{td_status}
</p>

<form method="POST"
action="/admin/api">

<label>Twelve Data API Key</label>

<input
type="password"
name="api_key"
placeholder="Paste new API key">

<button class="btn gold">
Save API Key
</button>

</form>

<p class="small">
Used for market quotes and candle data.
</p>

</div>

<div class="card">

<h2>News / Events</h2>

<p class="status">
{news_status}
</p>

<form method="POST"
action="/admin/news">

<label>News API Key</label>

<input
type="password"
name="api_key"
placeholder="Paste news API key">

<button class="btn gold">
Save News Key
</button>

</form>

<p class="small">
The key is stored in the local settings database.
</p>

</div>

</div>

<br>

<!-- CONTACT DATABASE -->

<div class="card">

<h2>Customer Contact Database</h2>

<p class="muted">
Every access request submitted through the website
appears here.
</p>

<div style="overflow:auto">

<table>

<tr>
<th>Name</th>
<th>Email</th>
<th>WhatsApp</th>
<th>Instagram</th>
<th>TikTok</th>
<th>Experience</th>
<th>Date</th>
</tr>

{visitor_rows}

</table>

</div>

</div>

<br>

<!-- PAYMENT REQUESTS -->

<div class="card">

<h2>Access & Payment Requests</h2>

<p class="muted">
Use the WhatsApp button to contact a customer with
their request details already prepared.
</p>

<div style="overflow:auto">

<table>

<tr>
<th>ID</th>
<th>Email</th>
<th>Package</th>
<th>Amount</th>
<th>Reference</th>
<th>Status</th>
<th>Date</th>
<th>Contact</th>
</tr>

{payment_rows}

</table>

</div>

</div>

<br>

<!-- PRICING -->

<div class="card">

<h2>Your Packages</h2>

<table>

<tr>
<th>Package</th>
<th>Price</th>
</tr>

<tr>
<td>TW Trades Mentorship</td>
<td>R300 / month</td>
</tr>

<tr>
<td>Titan X</td>
<td>R1,500 / month</td>
</tr>

<tr>
<td>Titan X + Yuki</td>
<td>R2,500 / month</td>
</tr>

</table>

</div>

<br>

<!-- SECURITY -->

<div class="card">

<h2>Security</h2>

<p class="small">
Default local admin credentials:
</p>

<pre>
Email: admin@twtrades.local
Password: ChangeMe123!
</pre>

<p class="small">
Change the default password before exposing this
application publicly. Production deployment should also
use HTTPS, proper authentication, CSRF protection,
rate limiting and secure secret storage.
</p>

</div>

</div>

</body>
</html>
"""

# ---------------------------------------------------------
# SERVER
# ---------------------------------------------------------

class Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def do_GET(self):

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            return html(self, home_page())

        if path == "/access":

            query = urllib.parse.parse_qs(
                parsed.query
            )

            plan = query.get(
                "plan",
                [""]
            )[0]

            return html(
                self,
                access_page(plan)
            )

        if path == "/market":
            return html(
                self,
                market_page()
            )

        if path == "/terminal":
            return html(
                self,
                terminal_page()
            )

        if path == "/journal":
            return html(
                self,
                journal_page()
            )

        if path == "/admin":
            return html(
                self,
                admin_page()
            )

        if path == "/health":

            return json_out(
                self,
                {
                    "status": "ok",
                    "time": now()
                }
            )

        if path == "/api/scan":

            results = []

            for symbol in WATCHLIST:

                quote = get_quote(symbol)
                analysis = titan(symbol)

                results.append({
                    "symbol": symbol,
                    "price": quote.get("price"),
                    "change": quote.get("change"),
                    "status": analysis.get(
                        "status",
                        "WAIT"
                    ),
                    "score": analysis.get(
                        "score",
                        0
                    )
                })

            return json_out(
                self,
                results
            )

        if path.startswith("/api/analyze/"):

            symbol = urllib.parse.unquote(
                path.split(
                    "/api/analyze/",
                    1
                )[1]
            )

            return json_out(
                self,
                titan(symbol)
            )

        self.send_error(404)

    def do_POST(self):

        parsed = urllib.parse.urlparse(
            self.path
        )

        path = parsed.path
        form = parse_form(self)

        # ---------------------------------------------
        # CUSTOMER ACCESS REQUEST
        # ---------------------------------------------

        if path == "/access":

            name = form_value(form, "name")
            email = form_value(form, "email")
            whatsapp = form_value(
                form,
                "whatsapp"
            )
            instagram = form_value(
                form,
                "instagram"
            )
            tiktok = form_value(
                form,
                "tiktok"
            )
            experience = form_value(
                form,
                "experience"
            )
            plan = form_value(
                form,
                "plan"
            )
            reference = form_value(
                form,
                "reference"
            )

            if plan not in PLANS:

                return html(
                    self,
                    "<h2>Invalid package.</h2>",
                    400
                )

            con = get_db()

            con.execute("""
            INSERT INTO visitors
            (
                name,
                email,
                whatsapp,
                instagram,
                tiktok,
                experience,
                created
            )
            VALUES(?,?,?,?,?,?,?)

            ON CONFLICT(email)
            DO UPDATE SET
                name=excluded.name,
                whatsapp=excluded.whatsapp,
                instagram=excluded.instagram,
                tiktok=excluded.tiktok,
                experience=excluded.experience
            """, (
                name,
                email,
                whatsapp,
                instagram,
                tiktok,
                experience,
                now()
            ))

            visitor = con.execute(
                "SELECT id FROM visitors "
                "WHERE email=?",
                (email,)
            ).fetchone()

            con.execute("""
            INSERT INTO payments
            (
                visitor_id,
                email,
                plan,
                reference,
                amount,
                status,
                created
            )
            VALUES(?,?,?,?,?,?,?)
            """, (
                visitor["id"],
                email,
                plan,
                reference,
                PLANS[plan],
                "pending",
                now()
            ))

            con.commit()
            con.close()

            return html(
                self,
                success_page()
            )

        # ---------------------------------------------
        # OWNER CONTACT SETTINGS
        # ---------------------------------------------

        if path == "/admin/contact":

            whatsapp = form_value(
                form,
                "owner_whatsapp"
            )

            instagram = form_value(
                form,
                "owner_instagram"
            )

            email_address = form_value(
                form,
                "owner_email"
            )

            save_setting(
                "owner_whatsapp",
                whatsapp
            )

            save_setting(
                "owner_instagram",
                instagram
            )

            save_setting(
                "owner_email",
                email_address
            )

            return html(
                self,
                admin_page(
                    "Owner contact settings saved successfully."
                )
            )

        # ---------------------------------------------
        # TWELVE DATA
        # ---------------------------------------------

        if path == "/admin/api":

            key = form_value(
                form,
                "api_key"
            )

            if key:
                save_setting(
                    "twelve_data_key",
                    key
                )

            return html(
                self,
                admin_page(
                    "Twelve Data API settings saved."
                )
            )

        # ---------------------------------------------
        # NEWS API
        # ---------------------------------------------

        if path == "/admin/news":

            key = form_value(
                form,
                "api_key"
            )

            if key:
                save_setting(
                    "news_api_key",
                    key
                )

            return html(
                self,
                admin_page(
                    "News API settings saved."
                )
            )

        # ---------------------------------------------
        # JOURNAL
        # ---------------------------------------------

        if path == "/journal":

            try:

                entry = float(
                    form_value(
                        form,
                        "entry"
                    ) or 0
                )

                sl = float(
                    form_value(
                        form,
                        "sl"
                    ) or 0
                )

                tp1 = float(
                    form_value(
                        form,
                        "tp1"
                    ) or 0
                )

                tp2 = float(
                    form_value(
                        form,
                        "tp2"
                    ) or 0
                )

            except ValueError:

                return html(
                    self,
                    "<h2>Invalid trade values.</h2>",
                    400
                )

            con = get_db()

            con.execute("""
            INSERT INTO journal
            (
                symbol,
                direction,
                entry,
                sl,
                tp1,
                tp2,
                notes,
                created
            )
            VALUES(?,?,?,?,?,?,?,?)
            """, (
                form_value(form, "symbol"),
                form_value(form, "direction"),
                entry,
                sl,
                tp1,
                tp2,
                form_value(form, "notes"),
                now()
            ))

            con.commit()
            con.close()

            self.send_response(303)
            self.send_header(
                "Location",
                "/journal"
            )
            self.end_headers()
            return

        self.send_error(404)

# ---------------------------------------------------------
# START
# ---------------------------------------------------------

print("")
print("================================================")
print("       TW TRADES INTELLIGENCE PLATFORM")
print("================================================")
print("")
print("Website : http://127.0.0.1:8080")
print("Admin   : http://127.0.0.1:8080/admin")
print("Market  : http://127.0.0.1:8080/market")
print("Terminal: http://127.0.0.1:8080/terminal")
print("Journal : http://127.0.0.1:8080/journal")
print("")
print("Admin email    :", DEFAULT_ADMIN_EMAIL)
print("Admin password :", DEFAULT_ADMIN_PASSWORD)
print("")
print("FIRST STEP:")
print("Open /admin and enter your WhatsApp number.")
print("")
print("================================================")

ThreadingHTTPServer(
    ("0.0.0.0", PORT),
    Handler
).serve_forever()
