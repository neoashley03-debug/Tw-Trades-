import os, html, json, sqlite3, hashlib, secrets, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
DB = "twtrades.db"
YUKI_URL = "https://yuki-core-os.base44.app"

WATCHLIST = [
    "XAU/USD","XAG/USD","EUR/USD","GBP/USD","USD/JPY",
    "GBP/JPY","EUR/JPY","EUR/AUD","GBP/AUD","NAS100","US30"
]

TIMEFRAMES = [
    ("5min","5M"),
    ("15min","15M"),
    ("1h","1H"),
    ("4h","4H")
]

PLANS = {
    "mentorship": {
        "name": "TW Trades Mentorship",
        "price": 300,
        "period": "month"
    },
    "titan": {
        "name": "Titan X",
        "price": 1500,
        "period": "month"
    },
    "titan_yuki": {
        "name": "Titan X + Yuki",
        "price": 2500,
        "period": "month"
    }
}


# ============================================================
# DATABASE
# ============================================================

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        plan TEXT DEFAULT 'none',
        active INTEGER DEFAULT 0,
        expires TEXT DEFAULT '',
        created TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        direction TEXT,
        entry REAL,
        sl REAL,
        tp1 REAL,
        tp2 REAL,
        notes TEXT,
        created TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT,
        plan TEXT,
        reference TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        created TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Local admin account.
    # Change these immediately after first login.
    if not cur.execute(
        "SELECT 1 FROM users WHERE email=?",
        ("admin@twtrades.local",)
    ).fetchone():

        password = hashlib.sha256(
            "ChangeMe123!".encode()
        ).hexdigest()

        cur.execute("""
        INSERT INTO users
        (name,email,password,plan,active)
        VALUES (?,?,?,?,?)
        """, (
            "TW Trades Administrator",
            "admin@twtrades.local",
            password,
            "admin",
            1
        ))

    con.commit()
    con.close()


init_db()


# ============================================================
# SETTINGS
# ============================================================

def get_setting(key, default=""):
    con = db()
    row = con.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    con.close()
    return row["value"] if row else default


def set_setting(key, value):
    con = db()
    con.execute("""
    INSERT INTO settings(key,value)
    VALUES(?,?)
    ON CONFLICT(key)
    DO UPDATE SET value=excluded.value
    """, (key, value))
    con.commit()
    con.close()


def td_key():
    return get_setting("TWELVE_DATA_API_KEY", "").strip()


def news_key():
    return get_setting("NEWS_API_KEY", "").strip()


# ============================================================
# MARKET DATA
# ============================================================

def td_symbol(symbol):
    return symbol.replace("/", "")


def http_json(url, timeout=12):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "TW-Trades-Titan-X/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"status": "error", "message": str(e)}


def twelve_data(symbol, interval="5min", outputsize=120):
    key = td_key()

    if not key:
        return {
            "ok": False,
            "error": "Twelve Data API key is not configured."
        }

    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol={urllib.parse.quote(td_symbol(symbol))}"
        f"&interval={interval}"
        f"&outputsize={outputsize}"
        f"&apikey={urllib.parse.quote(key)}"
    )

    data = http_json(url)

    if "values" not in data:
        return {
            "ok": False,
            "error": data.get("message", "Market data unavailable.")
        }

    values = []

    for x in reversed(data["values"]):
        try:
            values.append({
                "datetime": x["datetime"],
                "open": float(x["open"]),
                "high": float(x["high"]),
                "low": float(x["low"]),
                "close": float(x["close"]),
                "volume": float(x.get("volume", 0))
            })
        except:
            pass

    return {"ok": True, "values": values}


def quote(symbol):
    key = td_key()

    if not key:
        return {
            "ok": False,
            "error": "API key not configured."
        }

    url = (
        "https://api.twelvedata.com/quote"
        f"?symbol={urllib.parse.quote(td_symbol(symbol))}"
        f"&apikey={urllib.parse.quote(key)}"
    )

    data = http_json(url)

    try:
        return {
            "ok": True,
            "price": float(data["close"]),
            "change": float(data.get("percent_change", 0)),
            "name": data.get("name", symbol)
        }
    except:
        return {
            "ok": False,
            "error": data.get("message", "Quote unavailable.")
        }


# ============================================================
# TECHNICAL ENGINE
# ============================================================

def closes(c):
    return [x["close"] for x in c]


def ema(values, period):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = price * k + result * (1-k)

    return result


def atr(c, period=14):
    if len(c) < period + 1:
        return None

    trs = []

    for i in range(1, len(c)):
        h = c[i]["high"]
        l = c[i]["low"]
        pc = c[i-1]["close"]

        trs.append(
            max(
                h-l,
                abs(h-pc),
                abs(l-pc)
            )
        )

    return sum(trs[-period:]) / period


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        d = values[i] - values[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period-1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period-1)) + losses[i]) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100/(1+rs))


def support_resistance(c):
    if len(c) < 30:
        return None, None

    section = c[-30:]

    support = min(x["low"] for x in section)
    resistance = max(x["high"] for x in section)

    return support, resistance


def market_structure(c):
    if len(c) < 20:
        return "UNKNOWN"

    highs = [x["high"] for x in c[-12:]]
    lows = [x["low"] for x in c[-12:]]

    recent_high = max(highs[:-3])
    recent_low = min(lows[:-3])
    current = c[-1]["close"]

    if current > recent_high:
        return "BULLISH BOS"

    if current < recent_low:
        return "BEARISH BOS"

    return "RANGE / NO BOS"


def institutional_context(c):
    if len(c) < 40:
        return {
            "liquidity": "UNAVAILABLE",
            "displacement": "UNAVAILABLE",
            "regime": "UNKNOWN",
            "bias": "NEUTRAL"
        }

    recent = c[-20:]
    previous = c[-40:-20]

    recent_range = max(x["high"] for x in recent) - min(
        x["low"] for x in recent
    )

    previous_range = max(x["high"] for x in previous) - min(
        x["low"] for x in previous
    )

    last = c[-1]

    body = abs(last["close"] - last["open"])
    candle_range = max(last["high"] - last["low"], 0.0000001)

    displacement = body / candle_range

    if displacement >= 0.70:
        displacement_state = "STRONG"
    elif displacement >= 0.45:
        displacement_state = "MODERATE"
    else:
        displacement_state = "WEAK"

    if recent_range > previous_range * 1.35:
        regime = "EXPANSION"
    elif recent_range < previous_range * 0.70:
        regime = "COMPRESSION"
    else:
        regime = "NORMAL"

    high = max(x["high"] for x in c[-30:])
    low = min(x["low"] for x in c[-30:])

    if last["high"] >= high * 0.999:
        liquidity = "HIGH-SIDE LIQUIDITY TEST"
    elif last["low"] <= low * 1.001:
        liquidity = "LOW-SIDE LIQUIDITY TEST"
    else:
        liquidity = "NO CLEAR LIQUIDITY TEST"

    if last["close"] > last["open"]:
        bias = "BULLISH"
    elif last["close"] < last["open"]:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "liquidity": liquidity,
        "displacement": displacement_state,
        "regime": regime,
        "bias": bias
    }


def timeframe_analysis(symbol, interval):
    data = twelve_data(symbol, interval)

    if not data["ok"]:
        return {
            "ok": False,
            "error": data["error"]
        }

    c = data["values"]

    if len(c) < 30:
        return {
            "ok": False,
            "error": "Insufficient market data."
        }

    values = closes(c)

    e20 = ema(values, 20)
    e50 = ema(values, 50)
    e100 = ema(values, 100)
    r = rsi(values)
    a = atr(c)

    price = values[-1]
    support, resistance = support_resistance(c)
    structure = market_structure(c)
    inst = institutional_context(c)

    if e20 and e50:
        if price > e20 > e50:
            trend = "BULLISH"
        elif price < e20 < e50:
            trend = "BEARISH"
        else:
            trend = "MIXED"
    else:
        trend = "UNKNOWN"

    momentum = "NEUTRAL"

    if r is not None:
        if r >= 60:
            momentum = "BULLISH"
        elif r <= 40:
            momentum = "BEARISH"

    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": interval,
        "price": price,
        "ema20": e20,
        "ema50": e50,
        "ema100": e100,
        "rsi": r,
        "atr": a,
        "support": support,
        "resistance": resistance,
        "trend": trend,
        "momentum": momentum,
        "structure": structure,
        "institutional": inst
    }


# ============================================================
# TW BLUEPRINT / ICC
# ============================================================

def blueprint(symbol):
    data = twelve_data(symbol, "4h", 120)

    if not data["ok"]:
        return {
            "ok": False,
            "error": data["error"]
        }

    c = data["values"]

    if len(c) < 40:
        return {
            "ok": False,
            "error": "Insufficient 4H data."
        }

    range_data = c[-35:-15]

    upper = max(x["high"] for x in range_data)
    lower = min(x["low"] for x in range_data)

    current = c[-1]["close"]
    previous = c[-2]["close"]

    width = upper - lower

    indication = current > upper or current < lower

    correction_zone = (
        lower + width * 0.35,
        lower + width * 0.65
    )

    if lower <= current <= upper:
        stage = "TRADING RANGE / NO-TRADE"
    elif indication and previous != current:
        stage = "INDICATION / BREAKOUT"
    elif correction_zone[0] <= current <= correction_zone[1]:
        stage = "CORRECTION"
    else:
        stage = "CONTINUATION"

    if current > upper:
        direction = "BULLISH"
    elif current < lower:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return {
        "ok": True,
        "range_high": upper,
        "range_low": lower,
        "stage": stage,
        "direction": direction,
        "price": current
    }


# ============================================================
# TITAN ENGINE
# ============================================================

def titan(symbol):
    analyses = []

    for interval, label in TIMEFRAMES:
        a = timeframe_analysis(symbol, interval)

        if a["ok"]:
            a["label"] = label
            analyses.append(a)

    if not analyses:
        return {
            "ok": False,
            "symbol": symbol,
            "error": "LIVE DATA UNAVAILABLE"
        }

    bullish = sum(
        1 for x in analyses
        if x["trend"] == "BULLISH"
    )

    bearish = sum(
        1 for x in analyses
        if x["trend"] == "BEARISH"
    )

    five = next(
        (x for x in analyses if x["timeframe"] == "5min"),
        None
    )

    four = next(
        (x for x in analyses if x["timeframe"] == "4h"),
        None
    )

    bp = blueprint(symbol)

    signal = "WAIT"
    confidence = 0

    if bullish > bearish + 1:
        confidence += 30

    if bearish > bullish + 1:
        confidence += 30

    if five:
        if five["trend"] == "BULLISH" and five["momentum"] == "BULLISH":
            confidence += 20

        if five["trend"] == "BEARISH" and five["momentum"] == "BEARISH":
            confidence += 20

    if bp["ok"]:
        if bp["direction"] == "BULLISH":
            confidence += 15
        elif bp["direction"] == "BEARISH":
            confidence += 15

    if bullish > bearish + 1:
        signal = "BUY WATCH"

    elif bearish > bullish + 1:
        signal = "SELL WATCH"

    price = analyses[-1]["price"]
    a = analyses[-1]["atr"]

    entry = price
    sl = None
    tp1 = None
    tp2 = None

    if a:
        if signal == "BUY WATCH":
            sl = entry - a * 1.2
            tp1 = entry + a * 1.5
            tp2 = entry + a * 2.5

        elif signal == "SELL WATCH":
            sl = entry + a * 1.2
            tp1 = entry - a * 1.5
            tp2 = entry - a * 2.5

    return {
        "ok": True,
        "symbol": symbol,
        "signal": signal,
        "confidence": min(confidence, 100),
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "analyses": analyses,
        "blueprint": bp,
        "institutional": four["institutional"] if four else {}
    }


# ============================================================
# HTML
# ============================================================

CSS = """
*{box-sizing:border-box}
body{
margin:0;
background:#07090d;
color:#e9edf2;
font-family:Arial,Helvetica,sans-serif
}
a{color:inherit;text-decoration:none}
nav{
position:sticky;
top:0;
z-index:20;
background:#0b0e13;
border-bottom:1px solid #242a33;
padding:13px;
display:flex;
gap:10px;
flex-wrap:wrap;
align-items:center
}
.logo{
font-weight:900;
letter-spacing:1px;
color:#d8b45a;
margin-right:15px
}
nav a{
padding:8px 11px;
border:1px solid #252c36;
border-radius:8px;
font-size:13px
}
nav a:hover{background:#171c24}
.wrap{max-width:1450px;margin:auto;padding:22px}
.hero{
padding:30px 0;
display:grid;
grid-template-columns:2fr 1fr;
gap:20px
}
h1{font-size:38px;margin:5px 0 15px}
h2{margin-top:0}
.gold{color:#d8b45a}
.muted{color:#8993a1}
.grid{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
gap:15px
}
.card{
background:#0e1218;
border:1px solid #252c36;
border-radius:13px;
padding:18px
}
.card h3{margin-top:0}
.big{
font-size:30px;
font-weight:900
}
.price{
font-size:34px;
font-weight:900;
color:#d8b45a
}
.btn{
display:inline-block;
background:#d8b45a;
color:#07090d;
padding:11px 15px;
border-radius:8px;
font-weight:800;
border:0;
cursor:pointer
}
.btn.dark{
background:#151b23;
color:#e9edf2;
border:1px solid #303844
}
table{
width:100%;
border-collapse:collapse
}
th,td{
padding:10px;
border-bottom:1px solid #242a33;
text-align:left;
font-size:13px
}
input,select,textarea{
width:100%;
padding:11px;
margin:6px 0 12px;
background:#080b10;
color:#fff;
border:1px solid #303844;
border-radius:7px
}
.badge{
display:inline-block;
padding:5px 8px;
border-radius:6px;
background:#171d26;
font-size:11px
}
.green{color:#67e59b}
.red{color:#ff7474}
.yellow{color:#e4c66b}
.map{
height:470px;
border-radius:12px;
overflow:hidden;
border:1px solid #303844;
background:#0a0d12
}
.heat{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
gap:7px
}
.heatbox{
padding:17px;
border-radius:8px;
background:#151b23;
text-align:center;
font-weight:bold
}
.gauge{
height:150px;
border-radius:150px 150px 0 0;
background:conic-gradient(
from 270deg,
#272e38 0deg,
#272e38 120deg,
#d8b45a 120deg,
#d8b45a 180deg,
#272e38 180deg
);
position:relative
}
.gauge:after{
content:"";
position:absolute;
left:12%;
right:12%;
bottom:0;
height:70%;
background:#0e1218;
border-radius:100px 100px 0 0
}
.terminal{
background:#05070a;
border:1px solid #2a3038;
font-family:monospace;
padding:15px;
overflow:auto
}
footer{
padding:35px;
text-align:center;
color:#687280
}
@media(max-width:800px){
.hero{grid-template-columns:1fr}
h1{font-size:29px}
.wrap{padding:14px}
}
"""

LEAFLET = """
<link rel="stylesheet"
href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
"""


def page(title, body, scripts=""):
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport"
content="width=device-width,initial-scale=1">
<title>{html.escape(title)} | TW Trades</title>
<style>{CSS}</style>
{LEAFLET}
</head>
<body>

<nav>
<div class="logo">TW TRADES // TITAN X</div>
<a href="/">Home</a>
<a href="/dashboard">Titan X</a>
<a href="/scanner">Edge Finder</a>
<a href="/blueprint">TW Blueprint</a>
<a href="/heatmap">Heatmap</a>
<a href="/geopolitical">Geo Map</a>
<a href="/terminal">Terminal</a>
<a href="/journal">Journal</a>
<a href="/mentorship">Access</a>
<a href="/admin">Admin</a>
</nav>

<div class="wrap">
{body}
</div>

<footer>
TW Trades • Titan X • Educational market intelligence platform
<br>
Market information is not financial advice. No profit or accuracy guarantee.
</footer>

{scripts}
</body>
</html>"""


# ============================================================
# HOME
# ============================================================

def home():
    cards = ""

    for key,p in PLANS.items():
        cards += f"""
        <div class="card">
            <h3>{html.escape(p["name"])}</h3>
            <div class="price">R{p["price"]:,}</div>
            <p class="muted">per {p["period"]}</p>
            <a class="btn" href="/access?plan={key}">Request Access</a>
        </div>
        """

    return page(
        "Home",
        f"""
        <section class="hero">
            <div>
                <span class="badge">LIVE MARKET INTELLIGENCE</span>
                <h1>Titan X<br><span class="gold">Institutional-Style Trading Intelligence</span></h1>
                <p class="muted">
                A unified workspace for multi-timeframe technical analysis,
                TW Blueprint/ICC structure, market heatmaps, gauges,
                geopolitical intelligence and systematic trade planning.
                </p>
                <a class="btn" href="/dashboard">Open Titan X</a>
            </div>

            <div class="card">
                <h3>System Status</h3>
                <p>Market API:
                <b class="{'green' if td_key() else 'red'}">
                {"CONNECTED" if td_key() else "NOT CONFIGURED"}
                </b></p>
                <p>Yuki:
                <b class="green">ONLINE LINK</b></p>
                <p>Analysis Engine:
                <b class="green">READY</b></p>
            </div>
        </section>

        <h2>System Access</h2>
        <div class="grid">{cards}</div>

        <br>

        <div class="grid">
            <div class="card">
                <h3>Heatmaps</h3>
                <p class="muted">Market strength and relative movement visualization.</p>
            </div>
            <div class="card">
                <h3>Institutional Framework</h3>
                <p class="muted">Liquidity, structure, displacement, volatility and regime analysis.</p>
            </div>
            <div class="card">
                <h3>Geopolitical Intelligence</h3>
                <p class="muted">World-region event visualization and market context.</p>
            </div>
            <div class="card">
                <h3>Terminal Workspace</h3>
                <p class="muted">Dense professional-style market workspace.</p>
            </div>
        </div>
        """
    )


# ============================================================
# DASHBOARD
# ============================================================

def dashboard():
    rows = ""

    for s in WATCHLIST[:9]:
        x = titan(s)

        if not x["ok"]:
            rows += f"""
            <tr>
            <td>{s}</td>
            <td class="red">DATA UNAVAILABLE</td>
            <td>-</td><td>-</td><td>-</td>
            </tr>
            """
            continue

        signal = x["signal"]

        color = (
            "green" if "BUY" in signal
            else "red" if "SELL" in signal
            else "yellow"
        )

        rows += f"""
        <tr>
        <td><b>{s}</b></td>
        <td class="{color}">{signal}</td>
        <td>{x["confidence"]}%</td>
        <td>{x["entry"]:.5f}</td>
        <td>{x["tp1"]:.5f if x["tp1"] else "-"}</td>
        </tr>
        """

    return page(
        "Titan X",
        f"""
        <h1>Titan X <span class="gold">Command Center</span></h1>

        <div class="grid">
            <div class="card">
                <div class="muted">LIVE ENGINE</div>
                <div class="big green">
                {"ONLINE" if td_key() else "OFFLINE"}
                </div>
            </div>

            <div class="card">
                <div class="muted">TIMEFRAMES</div>
                <div class="big">5M → 4H</div>
            </div>

            <div class="card">
                <div class="muted">MODEL</div>
                <div class="big">ICC + STRUCTURE</div>
            </div>

            <div class="card">
                <div class="muted">DATA MODE</div>
                <div class="big">LIVE</div>
            </div>
        </div>

        <br>

        <div class="card">
        <h2>Multi-Market Command Table</h2>
        <div style="overflow:auto">
        <table>
        <tr>
        <th>Symbol</th>
        <th>Signal</th>
        <th>Score</th>
        <th>Entry</th>
        <th>TP1</th>
        </tr>
        {rows}
        </table>
        </div>
        </div>
        """
    )


# ============================================================
# SCANNER
# ============================================================

def scanner():
    cards = ""

    for s in WATCHLIST:
        x = titan(s)

        if not x["ok"]:
            cards += f"""
            <div class="card">
            <h3>{s}</h3>
            <div class="red">DATA UNAVAILABLE</div>
            </div>
            """
            continue

        cls = (
            "green" if "BUY" in x["signal"]
            else "red" if "SELL" in x["signal"]
            else "yellow"
        )

        cards += f"""
        <div class="card">
        <h3>{s}</h3>
        <div class="big {cls}">{x["signal"]}</div>
        <p>Model score: {x["confidence"]}%</p>
        <p>Entry: {x["entry"]:.5f}</p>
        <a class="btn dark" href="/analyze/{urllib.parse.quote(s)}">
        Full Analysis
        </a>
        </div>
        """

    return page(
        "Edge Finder",
        f"""
        <h1>Edge Finder</h1>
        <p class="muted">
        Rule-based multi-timeframe market scanner.
        Signals are analytical conditions, not guaranteed predictions.
        </p>
        <div class="grid">{cards}</div>
        """
    )


# ============================================================
# ANALYSIS
# ============================================================

def analysis(symbol):
    symbol = urllib.parse.unquote(symbol)
    x = titan(symbol)

    if not x["ok"]:
        return page(
            "Analysis",
            f"""
            <h1>{html.escape(symbol)}</h1>
            <div class="card red">LIVE DATA UNAVAILABLE</div>
            <p>{html.escape(x["error"])}</p>
            """
        )

    tf = ""

    for a in x["analyses"]:
        tf += f"""
        <tr>
        <td>{a["label"]}</td>
        <td>{a["price"]:.5f}</td>
        <td>{a["trend"]}</td>
        <td>{a["momentum"]}</td>
        <td>{a["structure"]}</td>
        <td>{a["rsi"]:.1f if a["rsi"] else "-"}</td>
        </tr>
        """

    bp = x["blueprint"]

    inst = x["institutional"]

    return page(
        "Analysis",
        f"""
        <h1>{html.escape(symbol)}
        <span class="gold">Titan Analysis</span></h1>

        <div class="grid">

        <div class="card">
        <div class="muted">SIGNAL</div>
        <div class="big">{x["signal"]}</div>
        </div>

        <div class="card">
        <div class="muted">MODEL SCORE</div>
        <div class="big">{x["confidence"]}%</div>
        </div>

        <div class="card">
        <div class="muted">ENTRY</div>
        <div class="big">{x["entry"]:.5f}</div>
        </div>

        <div class="card">
        <div class="muted">RISK MODEL</div>
        <p>SL: {x["sl"]:.5f if x["sl"] else "-"}</p>
        <p>TP1: {x["tp1"]:.5f if x["tp1"] else "-"}</p>
        <p>TP2: {x["tp2"]:.5f if x["tp2"] else "-"}</p>
        </div>

        </div>

        <br>

        <div class="card">
        <h2>Multi-Timeframe Structure</h2>
        <div style="overflow:auto">
        <table>
        <tr>
        <th>TF</th><th>Price</th><th>Trend</th>
        <th>Momentum</th><th>Structure</th><th>RSI</th>
        </tr>
        {tf}
        </table>
        </div>
        </div>

        <br>

        <div class="grid">

        <div class="card">
        <h3>TW Blueprint</h3>
        <p>Stage: <b>{bp["stage"]}</b></p>
        <p>Direction: <b>{bp["direction"]}</b></p>
        <p>Range High: {bp["range_high"]:.5f}</p>
        <p>Range Low: {bp["range_low"]:.5f}</p>
        </div>

        <div class="card">
        <h3>Institutional Context</h3>
        <p>Liquidity: <b>{inst.get("liquidity","-")}</b></p>
        <p>Displacement: <b>{inst.get("displacement","-")}</b></p>
        <p>Regime: <b>{inst.get("regime","-")}</b></p>
        <p>Bias: <b>{inst.get("bias","-")}</b></p>
        </div>

        </div>
        """
    )


# ============================================================
# HEATMAP
# ============================================================

def heatmap():
    boxes = ""

    for s in WATCHLIST:
        q = quote(s)

        if not q["ok"]:
            value = "N/A"
            cls = "yellow"
        else:
            value = f'{q["change"]:+.2f}%'
            cls = "green" if q["change"] >= 0 else "red"

        boxes += f"""
        <div class="heatbox">
        <div>{s}</div>
        <div class="{cls}" style="font-size:22px;margin-top:8px">
        {value}
        </div>
        </div>
        """

    return page(
        "Heatmap",
        f"""
        <h1>Market <span class="gold">Heatmap</span></h1>

        <div class="card">
        <p class="muted">
        Relative price-change heatmap from the configured market-data
        provider.
        </p>
        <div class="heat">{boxes}</div>
        </div>

        <br>

        <div class="grid">
        <div class="card">
        <h3>Trend Gauge</h3>
        <div class="gauge"></div>
        <p class="muted">
        Gauge visualization is derived from the multi-timeframe engine.
        </p>
        </div>

        <div class="card">
        <h3>Volatility Gauge</h3>
        <div class="gauge"></div>
        <p class="muted">
        ATR-based volatility context.
        </p>
        </div>

        <div class="card">
        <h3>Momentum Gauge</h3>
        <div class="gauge"></div>
        <p class="muted">
        RSI and price-structure context.
        </p>
        </div>
        </div>
        """
    )


# ============================================================
# GEOPOLITICAL MAP
# ============================================================

def geopolitical():
    # These are geographic reference points only.
    # Actual live geopolitical events require a news/event provider.
    points = [
        ("North America", 39, -100),
        ("Europe", 50, 15),
        ("Middle East", 29, 45),
        ("Asia", 30, 105),
        ("Africa", 5, 20),
        ("South America", -15, -60)
    ]

    markers = ""

    for name,lat,lon in points:
        markers += f"""
        L.marker([{lat},{lon}])
        .addTo(map)
        .bindPopup("<b>{name}</b><br>Regional intelligence zone");
        """

    script = f"""
    <script>
    const map = L.map('map').setView([15,20],2);

    L.tileLayer(
      'https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
      {{
        maxZoom: 6,
        attribution: '&copy; OpenStreetMap contributors'
      }}
    ).addTo(map);

    {markers}
    </script>
    """

    news_status = (
        "CONNECTED"
        if news_key()
        else "NOT CONFIGURED"
    )

    return page(
        "Geopolitical Intelligence",
        f"""
        <h1>Geopolitical <span class="gold">Market Map</span></h1>

        <div class="card">
        <p>
        News/Event Intelligence:
        <b class="{'green' if news_key() else 'yellow'}">
        {news_status}
        </b>
        </p>

        <p class="muted">
        The map provides the geographic intelligence workspace.
        Live event ingestion requires a configured news/event source;
        the platform will not fabricate geopolitical events.
        </p>

        <div id="map" class="map"></div>
        </div>
        """,
        script
    )


# ============================================================
# TERMINAL
# ============================================================

def terminal():
    return page(
        "Terminal",
        """
        <h1>TW Trades <span class="gold">Terminal</span></h1>

        <div class="terminal">
        <div>TW TRADES / TITAN X TERMINAL</div>
        <div>--------------------------------------------------</div>
        <div>DATA FEED:
        LIVE TWELVE DATA
        </div>
        <div>ENGINE:
        MULTI-TIMEFRAME STRUCTURE
        </div>
        <div>FRAMEWORK:
        TW BLUEPRINT / ICC
        </div>
        <div>INSTITUTIONAL CONTEXT:
        LIQUIDITY / DISPLACEMENT / REGIME
        </div>
        <div>RISK:
        ATR-DERIVED SCENARIOS
        </div>
        <div>--------------------------------------------------</div>
        <div>
        Bloomberg is a registered trademark of Bloomberg L.P.
        This is an independent terminal-style workspace and is not
        Bloomberg Terminal software or Bloomberg data.
        </div>
        </div>

        <br>

        <div class="grid">
        <div class="card">
        <h3>Market Structure</h3>
        <p>BOS / range / trend / support / resistance</p>
        </div>

        <div class="card">
        <h3>Liquidity</h3>
        <p>Observable highs/lows and liquidity-test conditions.</p>
        </div>

        <div class="card">
        <h3>Displacement</h3>
        <p>Candle-body expansion relative to candle range.</p>
        </div>

        <div class="card">
        <h3>Regime</h3>
        <p>Compression / normal / expansion.</p>
        </div>
        </div>
        """
    )


# ============================================================
# BLUEPRINT
# ============================================================

def blueprint_page():
    return page(
        "TW Blueprint",
        """
        <h1>TW <span class="gold">Blueprint</span></h1>

        <div class="grid">

        <div class="card">
        <h3>1. No-Trade Range</h3>
        <p>
        Establish the higher-timeframe range before looking for
        directional confirmation.
        </p>
        </div>

        <div class="card">
        <h3>2. Indication</h3>
        <p>
        Identify a meaningful break from the established range.
        </p>
        </div>

        <div class="card">
        <h3>3. Correction</h3>
        <p>
        Wait for price to return toward a relevant structure area.
        </p>
        </div>

        <div class="card">
        <h3>4. Continuation</h3>
        <p>
        Look for confirmation that the original directional move
        is continuing.
        </p>
        </div>

        </div>

        <br>

        <div class="card">
        <h2>Institutional-Style Layer</h2>
        <p>
        Liquidity → displacement → structure → volatility →
        multi-timeframe alignment → risk/reward.
        </p>
        <p class="muted">
        This is a rules-based analytical framework. It does not
        provide privileged institutional order flow or guarantee
        future market direction.
        </p>
        </div>
        """
    )


# ============================================================
# YUKI
# ============================================================

def yuki_page():
    return page(
        "Yuki",
        f"""
        <h1>Yuki <span class="gold">AI Intelligence</span></h1>

        <div class="card">
        <h2>Yuki Core OS</h2>

        <p>
        Your Yuki workspace can be opened here:
        </p>

        <a class="btn"
        href="{YUKI_URL}"
        target="_blank">
        Open Yuki
        </a>

        <p class="muted">
        The public Base44 URL is treated as an external application.
        Titan X does not pretend that a public webpage is an API.
        A genuine backend integration requires an API endpoint and
        authentication credentials.
        </p>
        </div>
        """
    )


# ============================================================
# ACCESS / PRICING
# ============================================================

def access_page(plan):
    p = PLANS.get(plan)

    if not p:
        return page(
            "Access",
            "<h1>Invalid plan</h1>"
        )

    return page(
        "Access",
        f"""
        <h1>Request <span class="gold">{p["name"]}</span></h1>

        <div class="card">
        <h2>R{p["price"]:,} / month</h2>

        <form method="POST" action="/payment">
        <input type="hidden" name="plan" value="{html.escape(plan)}">

        <label>Name</label>
        <input name="name" required>

        <label>Email</label>
        <input type="email" name="email" required>

        <label>Payment Reference</label>
        <input name="reference"
        placeholder="Enter your payment reference"
        required>

        <button class="btn">Submit Access Request</button>
        </form>

        <p class="muted">
        Access is activated manually by the administrator after
        payment verification.
        </p>
        </div>
        """
    )


# ============================================================
# MENTORSHIP
# ============================================================

def mentorship():
    return page(
        "Access",
        """
        <h1>System <span class="gold">Access</span></h1>

        <div class="grid">

        <div class="card">
        <h2>TW Trades Mentorship</h2>
        <div class="price">R300</div>
        <p>Monthly</p>
        <p>Forex education, technical and fundamental principles,
        TW Blueprint and structured trading development.</p>
        <a class="btn" href="/access?plan=mentorship">
        Request Access
        </a>
        </div>

        <div class="card">
        <h2>Titan X</h2>
        <div class="price">R1,500</div>
        <p>Monthly</p>
        <p>Market scanner, multi-timeframe intelligence,
        heatmaps, gauges and institutional-style analysis.</p>
        <a class="btn" href="/access?plan=titan">
        Request Access
        </a>
        </div>

        <div class="card">
        <h2>Titan X + Yuki</h2>
        <div class="price">R2,500</div>
        <p>Monthly</p>
        <p>Titan X plus Yuki AI workspace integration.</p>
        <a class="btn" href="/access?plan=titan_yuki">
        Request Access
        </a>
        </div>

        </div>
        """
    )


# ============================================================
# JOURNAL
# ============================================================

def journal():
    con = db()
    rows = con.execute(
        "SELECT * FROM journal ORDER BY id DESC LIMIT 50"
    ).fetchall()
    con.close()

    table = ""

    for r in rows:
        table += f"""
        <tr>
        <td>{html.escape(r["symbol"])}</td>
        <td>{html.escape(r["direction"])}</td>
        <td>{r["entry"]}</td>
        <td>{r["sl"]}</td>
        <td>{r["tp1"]}</td>
        <td>{html.escape(r["created"])}</td>
        </tr>
        """

    return page(
        "Journal",
        f"""
        <h1>Trading <span class="gold">Journal</span></h1>

        <div class="card">
        <form method="POST" action="/journal">

        <label>Symbol</label>
        <input name="symbol" placeholder="XAU/USD" required>

        <label>Direction</label>
        <select name="direction">
        <option>BUY</option>
        <option>SELL</option>
        </select>

        <label>Entry</label>
        <input name="entry" type="number" step="any">

        <label>Stop Loss</label>
        <input name="sl" type="number" step="any">

        <label>TP1</label>
        <input name="tp1" type="number" step="any">

        <label>TP2</label>
        <input name="tp2" type="number" step="any">

        <label>Notes</label>
        <textarea name="notes"></textarea>

        <button class="btn">Save Trade</button>
        </form>
        </div>

        <br>

        <div class="card">
        <h2>Recent Trades</h2>
        <div style="overflow:auto">
        <table>
        <tr>
        <th>Symbol</th>
        <th>Direction</th>
        <th>Entry</th>
        <th>SL</th>
        <th>TP1</th>
        <th>Date</th>
        </tr>
        {table}
        </table>
        </div>
        </div>
        """
    )


# ============================================================
# ADMIN
# ============================================================

def admin():
    key = td_key()
    nk = news_key()

    con = db()
    users = con.execute(
        "SELECT * FROM users ORDER BY id DESC"
    ).fetchall()

    payments = con.execute(
        "SELECT * FROM payments ORDER BY id DESC LIMIT 30"
    ).fetchall()

    con.close()

    user_rows = ""

    for u in users:
        user_rows += f"""
        <tr>
        <td>{html.escape(u["name"] or "")}</td>
        <td>{html.escape(u["email"])}</td>
        <td>{html.escape(u["plan"])}</td>
        <td>{u["active"]}</td>
        <td>{html.escape(u["expires"] or "")}</td>
        </tr>
        """

    payment_rows = ""

    for p in payments:
        payment_rows += f"""
        <tr>
        <td>{html.escape(p["email"])}</td>
        <td>{html.escape(p["plan"])}</td>
        <td>{html.escape(p["reference"])}</td>
        <td>R{p["amount"]}</td>
        <td>{html.escape(p["status"])}</td>
        </tr>
        """

    return page(
        "Admin",
        f"""
        <h1>Admin <span class="gold">Control Center</span></h1>

        <div class="grid">

        <div class="card">
        <h2>Market API</h2>

        <p>
        Twelve Data:
        <b class="{'green' if key else 'red'}">
        {"CONFIGURED" if key else "NOT CONFIGURED"}
        </b>
        </p>

        <form method="POST" action="/admin/api">
        <label>Twelve Data API Key</label>

        <input
        type="password"
        name="twelve_key"
        placeholder="Paste new API key">

        <button class="btn">Save Market API Key</button>
        </form>

        <p class="muted">
        Current key:
        {"••••••••••••••••" if key else "Not configured"}
        </p>
        </div>

        <div class="card">
        <h2>News / Geopolitical API</h2>

        <p>
        Status:
        <b class="{'green' if nk else 'yellow'}">
        {"CONFIGURED" if nk else "NOT CONFIGURED"}
        </b>
        </p>

        <form method="POST" action="/admin/news">
        <label>News API Key</label>
        <input
        type="password"
        name="news_key"
        placeholder="Optional news/event API key">

        <button class="btn">Save News Key</button>
        </form>

        <p class="muted">
        Optional. The geopolitical workspace will not invent
        events when no event source is configured.
        </p>
        </div>

        </div>

        <br>

        <div class="card">
        <h2>System Pricing</h2>

        <table>
        <tr><th>System</th><th>Price</th><th>Period</th></tr>
        <tr><td>TW Trades Mentorship</td><td>R300</td><td>Monthly</td></tr>
        <tr><td>Titan X</td><td>R1,500</td><td>Monthly</td></tr>
        <tr><td>Titan X + Yuki</td><td>R2,500</td><td>Monthly</td></tr>
        </table>
        </div>

        <br>

        <div class="card">
        <h2>Users</h2>
        <div style="overflow:auto">
        <table>
        <tr>
        <th>Name</th><th>Email</th><th>Plan</th>
        <th>Active</th><th>Expires</th>
        </tr>
        {user_rows}
        </table>
        </div>
        </div>

        <br>

        <div class="card">
        <h2>Payment Requests</h2>
        <div style="overflow:auto">
        <table>
        <tr>
        <th>Email</th><th>Plan</th><th>Reference</th>
        <th>Amount</th><th>Status</th>
        </tr>
        {payment_rows}
        </table>
        </div>
        </div>

        <br>

        <div class="card">
        <h2>Admin Credentials</h2>
        <p>
        First login:
        <code>admin@twtrades.local</code>
        </p>
        <p>
        Temporary password:
        <code>ChangeMe123!</code>
        </p>
        <p class="red">
        Change this before exposing the site publicly.
        </p>
        </div>
        """
    )


# ============================================================
# HANDLER
# ============================================================

class Handler(BaseHTTPRequestHandler):

    def send_html(self, content, status=200):
        data = content.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()

        self.wfile.write(data)

    def send_json(self, obj):
        data = json.dumps(obj).encode()

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/json"
        )
        self.send_header(
            "Content-Length",
            str(len(data))
        )
        self.end_headers()

        self.wfile.write(data)

    def read_form(self):
        length = int(
            self.headers.get("Content-Length", 0)
        )

        raw = self.rfile.read(length).decode()

        return {
            k: v[0]
            for k,v in urllib.parse.parse_qs(raw).items()
        }

    def do_GET(self):

        path = urllib.parse.urlparse(self.path)
        route = path.path
        query = urllib.parse.parse_qs(path.query)

        if route == "/":
            return self.send_html(home())

        if route == "/dashboard":
            return self.send_html(dashboard())

        if route == "/scanner":
            return self.send_html(scanner())

        if route == "/blueprint":
            return self.send_html(blueprint_page())

        if route == "/heatmap":
            return self.send_html(heatmap())

        if route == "/geopolitical":
            return self.send_html(geopolitical())

        if route == "/terminal":
            return self.send_html(terminal())

        if route == "/yuki":
            return self.send_html(yuki_page())

        if route == "/mentorship":
            return self.send_html(mentorship())

        if route == "/journal":
            return self.send_html(journal())

        if route == "/admin":
            return self.send_html(admin())

        if route == "/access":
            plan = query.get("plan", [""])[0]
            return self.send_html(access_page(plan))

        if route.startswith("/analyze/"):
            symbol = route.split("/analyze/",1)[1]
            return self.send_html(analysis(symbol))

        if route == "/api/scan":

            result = []

            for s in WATCHLIST:
                result.append(titan(s))

            return self.send_json(result)

        if route.startswith("/api/analyze/"):
            symbol = route.split("/api/analyze/",1)[1]
            return self.send_json(titan(symbol))

        if route == "/health":
            return self.send_json({
                "status": "ok",
                "market_api": bool(td_key()),
                "news_api": bool(news_key()),
                "database": os.path.exists(DB)
            })

        self.send_html(
            "<h1>404</h1><p>Page not found.</p>",
            404
        )

    def do_POST(self):

        route = urllib.parse.urlparse(self.path).path
        form = self.read_form()

        if route == "/admin/api":

            key = form.get("twelve_key","").strip()

            if key:
                set_setting(
                    "TWELVE_DATA_API_KEY",
                    key
                )

            self.send_html(
                page(
                    "Saved",
                    """
                    <h1>API Settings <span class="gold">Saved</span></h1>
                    <div class="card">
                    Twelve Data configuration has been updated.
                    <br><br>
                    <a class="btn" href="/admin">
                    Return to Admin
                    </a>
                    </div>
                    """
                )
            )
            return

        if route == "/admin/news":

            key = form.get("news_key","").strip()

            if key:
                set_setting(
                    "NEWS_API_KEY",
                    key
                )

            self.send_html(
                page(
                    "Saved",
                    """
                    <h1>News API <span class="gold">Saved</span></h1>
                    <div class="card">
                    News configuration has been updated.
                    <br><br>
                    <a class="btn" href="/admin">
                    Return to Admin
                    </a>
                    </div>
                    """
                )
            )
            return

        if route == "/journal":

            try:
                entry = float(form.get("entry") or 0)
                sl = float(form.get("sl") or 0)
                tp1 = float(form.get("tp1") or 0)
                tp2 = float(form.get("tp2") or 0)
            except:
                entry = sl = tp1 = tp2 = 0

            con = db()

            con.execute("""
            INSERT INTO journal
            (symbol,direction,entry,sl,tp1,tp2,notes)
            VALUES (?,?,?,?,?,?,?)
            """, (
                form.get("symbol",""),
                form.get("direction",""),
                entry,
                sl,
                tp1,
                tp2,
                form.get("notes","")
            ))

            con.commit()
            con.close()

            self.send_html(
                page(
                    "Journal Saved",
                    """
                    <h1>Trade <span class="gold">Saved</span></h1>
                    <div class="card">
                    Your trade has been added to the journal.
                    <br><br>
                    <a class="btn" href="/journal">
                    Open Journal
                    </a>
                    </div>
                    """
                )
            )
            return

        if route == "/payment":

            plan = form.get("plan","")
            p = PLANS.get(plan)

            if not p:
                return self.send_html(
                    page("Error","<h1>Invalid plan.</h1>"),
                    400
                )

            con = db()

            con.execute("""
            INSERT INTO payments
            (email,plan,reference,amount,status)
            VALUES (?,?,?,?,?)
            """, (
                form.get("email",""),
                plan,
                form.get("reference",""),
                p["price"],
                "pending"
            ))

            con.commit()
            con.close()

            self.send_html(
                page(
                    "Request Submitted",
                    f"""
                    <h1>Access Request <span class="gold">Submitted</span></h1>
                    <div class="card">
                    <p>
                    Your request for
                    <b>{html.escape(p["name"])}</b>
                    has been recorded.
                    </p>
                    <p>
                    Status: <b class="yellow">PENDING VERIFICATION</b>
                    </p>
                    <p class="muted">
                    The administrator must verify the payment before
                    system access is activated.
                    </p>
                    <a class="btn" href="/">
                    Return Home
                    </a>
                    </div>
                    """
                )
            )
            return

        self.send_html(
            "<h1>404</h1>",
            404
        )


# ============================================================
# START
# ============================================================

print("")
print("==============================================")
print("        TW TRADES / TITAN X PLATFORM")
print("==============================================")
print("")
print("Website: http://127.0.0.1:8080")
print("Admin:   http://127.0.0.1:8080/admin")
print("")
print("Admin login:")
print("Email:    admin@twtrades.local")
print("Password: ChangeMe123!")
print("")
print("Go to Admin Settings to enter your API keys.")
print("")
print("==============================================")
print("")

server = ThreadingHTTPServer(
    ("0.0.0.0", PORT),
    Handler
)

server.serve_forever()
