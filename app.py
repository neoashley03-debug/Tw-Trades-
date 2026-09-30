import os
import sqlite3
import secrets
from datetime import datetime
from functools import wraps
from urllib.parse import quote

import requests
from flask import Flask, request, redirect, url_for, session, jsonify, render_template_string

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "twtrades.db")

app = Flask(__name__)

# Persistent secret
SECRET_FILE = os.path.join(APP_DIR, ".secret")
if os.path.exists(SECRET_FILE):
    SECRET_KEY = open(SECRET_FILE).read().strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    open(SECRET_FILE, "w").write(SECRET_KEY)

app.secret_key = SECRET_KEY

# ---------------------------------------------------------
# ADMIN
# ---------------------------------------------------------

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@twtrades.local")

PASSWORD_FILE = os.path.join(APP_DIR, ".admin_password")
if os.path.exists(PASSWORD_FILE):
    ADMIN_PASSWORD = open(PASSWORD_FILE).read().strip()
else:
    ADMIN_PASSWORD = secrets.token_urlsafe(12)
    open(PASSWORD_FILE, "w").write(ADMIN_PASSWORD)

# ---------------------------------------------------------
# DEFAULT SETTINGS
# ---------------------------------------------------------

DEFAULT_SETTINGS = {
    "owner_email": "neoashley03@gmail.com",
    "instagram": "@ashleysnowfx",

    # WhatsApp numbers without +
    "whatsapp1": "27697343252",
    "whatsapp2": "27693118405",

    "twelve_data_key": "",
    "news_api_key": "",

    "yuki_url": "https://yuki-core-os.base44.app",
    "titan_url": "",

    "package_basic": "300",
    "package_pro": "1500",
    "package_elite": "2500",
}

# ---------------------------------------------------------
# DATABASE
# ---------------------------------------------------------

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            package TEXT DEFAULT '',
            message TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)",
            (key, value)
        )

    conn.commit()
    conn.close()


def get_settings():
    conn = db()
    rows = conn.execute("SELECT key,value FROM settings").fetchall()
    conn.close()

    data = DEFAULT_SETTINGS.copy()

    for row in rows:
        data[row["key"]] = row["value"]

    return data


def save_setting(key, value):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)",
        (key, value)
    )
    conn.commit()
    conn.close()


init_db()

# ---------------------------------------------------------
# AUTH
# ---------------------------------------------------------

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return fn(*args, **kwargs)
    return wrapper

# ---------------------------------------------------------
# STYLE
# ---------------------------------------------------------

STYLE = """
<style>
*{box-sizing:border-box}

html{scroll-behavior:smooth}

body{
margin:0;
font-family:Inter,Arial,Helvetica,sans-serif;
background:#05070b;
color:#f5f7fa;
line-height:1.55;
}

nav{
position:sticky;
top:0;
z-index:100;
display:flex;
align-items:center;
gap:22px;
padding:16px 5%;
background:rgba(8,11,17,.96);
backdrop-filter:blur(12px);
border-bottom:1px solid #202631;
}

nav a{
color:#c9ced7;
text-decoration:none;
font-weight:600;
}

nav a:hover{color:#fff}

.container{
width:min(1180px,92%);
margin:35px auto;
}

.hero{
padding:65px 30px;
border:1px solid #252c38;
border-radius:26px;
background:
radial-gradient(circle at top right,#182131 0,transparent 38%),
linear-gradient(135deg,#111720,#07090d);
box-shadow:0 25px 80px rgba(0,0,0,.35);
}

.eyebrow{
letter-spacing:3px;
color:#8e98a8;
font-size:13px;
font-weight:bold;
}

h1{
font-size:clamp(42px,7vw,76px);
line-height:1;
margin:18px 0;
letter-spacing:-3px;
}

h2{margin-top:0}

h3{font-size:28px}

.muted{color:#929baa}

.grid{
display:grid;
grid-template-columns:repeat(auto-fit,minmax(240px,1fr));
gap:18px;
}

.card{
background:#0e131a;
border:1px solid #252d39;
border-radius:18px;
padding:24px;
}

.card:hover{
border-color:#3a4352;
}

.price{
font-size:35px;
font-weight:800;
margin:8px 0;
}

.btn{
display:inline-block;
padding:13px 20px;
border-radius:11px;
background:#f4f4f5;
color:#07090c;
text-decoration:none;
border:0;
cursor:pointer;
font-weight:800;
margin:4px;
}

.btn.dark{
background:#151b24;
color:#fff;
border:1px solid #303948;
}

.btn.gold{
background:#d7b46a;
color:#080808;
}

input,textarea,select{
width:100%;
padding:13px;
margin:7px 0 15px;
border-radius:10px;
border:1px solid #303847;
background:#080b10;
color:#fff;
font-size:15px;
}

textarea{min-height:130px}

table{
width:100%;
border-collapse:collapse;
overflow:auto;
}

th,td{
padding:12px;
border-bottom:1px solid #252d39;
text-align:left;
font-size:14px;
}

.badge{
display:inline-block;
padding:5px 9px;
border-radius:8px;
background:#202833;
}

.alert{
padding:15px;
border-radius:11px;
background:#17221b;
border:1px solid #304a39;
margin-bottom:20px;
}

.danger{
background:#281719;
border-color:#633034;
}

.quote{
font-size:27px;
font-weight:800;
margin:10px 0;
}

.news{
display:block;
padding:16px 0;
border-bottom:1px solid #252d39;
color:#fff;
text-decoration:none;
}

.news:hover{background:#11161d}

.small{font-size:13px}

.status{
display:inline-block;
width:9px;
height:9px;
border-radius:50%;
background:#6dd68a;
margin-right:7px;
}

footer{
margin-top:70px;
padding:35px 10px;
text-align:center;
color:#727b89;
border-top:1px solid #202631;
}

@media(max-width:650px){
nav{gap:14px;font-size:14px}
.container{width:94%}
.hero{padding:45px 22px}
h1{letter-spacing:-2px}
}
</style>
"""

NAV = """
<nav>
<a href="/">TW TRADES</a>
<a href="/">Home</a>
<a href="/market">Market</a>
<a href="/terminal">Terminal</a>
<a href="/journal">Journal</a>
<a href="/admin">Admin</a>
</nav>
"""


def page(title, body):
    return f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="TW Trades Trading Intelligence Platform">
<title>{title} — TW Trades</title>
{STYLE}
</head>
<body>
{NAV}
<div class="container">
{body}
</div>
<footer>
TW Trades • SnowFX<br>
Educational purposes only. Market data may be delayed and is not financial advice.
</footer>
</body>
</html>
"""

# ---------------------------------------------------------
# WHATSAPP
# ---------------------------------------------------------

def wa_url(number, message=""):
    if not number:
        return "#"

    number = number.replace("+","").replace(" ","").replace("-","")
    return "https://wa.me/" + number + "?text=" + quote(message)


def request_message(name,email,phone,package,message):
    return (
        "TW TRADES ACCESS REQUEST\n\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Phone: {phone}\n"
        f"Package: {package}\n"
        f"Message: {message}\n\n"
        "Please assist with access."
    )

# ---------------------------------------------------------
# HOME
# ---------------------------------------------------------

@app.route("/")
def home():

    s = get_settings()

    msg = "Hello TW Trades, I would like information about your trading packages."

    wa1 = wa_url(s["whatsapp1"], msg)
    wa2 = wa_url(s["whatsapp2"], msg)

    body = f"""
<section class="hero">

<p class="eyebrow">TW TRADES • SNOWFX</p>

<h1>Trading Intelligence Platform</h1>

<p style="font-size:20px;max-width:700px">
Market intelligence, trading tools, analysis resources and
controlled access to TW Trades systems — built in one platform.
</p>

<br>

<a class="btn" href="/market">Open Market</a>
<a class="btn dark" href="/terminal">Open Terminal</a>
<a class="btn gold" href="#packages">Get Access</a>

</section>

<br>

<div class="grid">

<div class="card">
<p class="eyebrow">MARKET</p>
<h2>Live Market Intelligence</h2>
<p class="muted">
Monitor selected forex, gold and index instruments through
the TW Trades market interface.
</p>
<a class="btn dark" href="/market">View Market</a>
</div>

<div class="card">
<p class="eyebrow">SYSTEMS</p>
<h2>Titan X + Yuki</h2>
<p class="muted">
Access the external trading systems and analysis tools connected
to the TW Trades platform.
</p>
<a class="btn dark" href="/terminal">Open Terminal</a>
</div>

<div class="card">
<p class="eyebrow">MENTORSHIP</p>
<h2>TW Trades Education</h2>
<p class="muted">
Trading education focused on structured analysis, price action,
discipline and market awareness.
</p>
</div>

</div>

<br>

<section id="packages">

<h2>Access Packages</h2>

<div class="grid">

<div class="card">
<p class="eyebrow">BASIC</p>
<h2>Starter Access</h2>
<div class="price">R{s["package_basic"]}</div>
<p class="muted">Entry-level TW Trades access.</p>
<a class="btn" href="#request">Request</a>
</div>

<div class="card">
<p class="eyebrow">PRO</p>
<h2>Advanced Access</h2>
<div class="price">R{s["package_pro"]}</div>
<p class="muted">Advanced tools and trading resources.</p>
<a class="btn" href="#request">Request</a>
</div>

<div class="card">
<p class="eyebrow">ELITE</p>
<h2>Premium Access</h2>
<div class="price">R{s["package_elite"]}</div>
<p class="muted">Premium systems and resources.</p>
<a class="btn gold" href="#request">Request</a>
</div>

</div>
</section>

<br>

<section id="request" class="card">

<h2>Request Access</h2>

<p class="muted">
Submit your details. Your request will be saved in the private
TW Trades administration panel.
</p>

<form method="POST" action="/request-access">

<label>Name</label>
<input name="name" required>

<label>Email</label>
<input name="email" type="email">

<label>Phone / WhatsApp</label>
<input name="phone">

<label>Package</label>

<select name="package">
<option>Basic - R{s["package_basic"]}</option>
<option>Pro - R{s["package_pro"]}</option>
<option>Elite - R{s["package_elite"]}</option>
</select>

<label>Message</label>
<textarea name="message" placeholder="Tell us what access you need..."></textarea>

<button class="btn" type="submit">Submit Request</button>

</form>

</section>

<br>

<div class="card">

<h2>Direct WhatsApp</h2>

<p class="muted">Contact TW Trades directly.</p>

<a class="btn" href="{wa1}" target="_blank">WhatsApp 1</a>
<a class="btn dark" href="{wa2}" target="_blank">WhatsApp 2</a>

</div>
"""

    return page("Home", body)

# ---------------------------------------------------------
# REQUEST
# ---------------------------------------------------------

@app.route("/request-access", methods=["POST"])
def request_access():

    name = request.form.get("name","").strip()
    email = request.form.get("email","").strip()
    phone = request.form.get("phone","").strip()
    package = request.form.get("package","").strip()
    message = request.form.get("message","").strip()

    if not name:
        return page(
            "Error",
            '<div class="alert danger">Name is required.</div>'
            '<a class="btn" href="/">Go back</a>'
        )

    conn = db()

    conn.execute("""
        INSERT INTO requests
        (name,email,phone,package,message,status,created_at)
        VALUES (?,?,?,?,?,?,?)
    """,(
        name,email,phone,package,message,
        "pending",
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()

    s = get_settings()

    msg = request_message(
        name,email,phone,package,message
    )

    wa1 = wa_url(s["whatsapp1"], msg)
    wa2 = wa_url(s["whatsapp2"], msg)

    body = f"""
<div class="alert">
<h2>Request received.</h2>
<p>Your request has been saved successfully.</p>
<p>You can now continue directly to WhatsApp.</p>
</div>

<a class="btn" target="_blank" href="{wa1}">
Send to WhatsApp 1
</a>

<a class="btn dark" target="_blank" href="{wa2}">
Send to WhatsApp 2
</a>

<br><br>

<a class="btn dark" href="/">Return Home</a>
"""

    return page("Request Received", body)

# ---------------------------------------------------------
# TWELVE DATA
# ---------------------------------------------------------

SYMBOLS = {
    "XAUUSD": "XAU/USD",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "NAS100": "NDX",
}


def twelve_quote(symbol):

    s = get_settings()
    key = s.get("twelve_data_key","").strip()

    if not key:
        return {
            "status":"not_configured",
            "symbol":symbol,
            "message":"Add your Twelve Data API key in Admin."
        }

    try:

        r = requests.get(
            "https://api.twelvedata.com/quote",
            params={
                "symbol":symbol,
                "apikey":key
            },
            timeout=10
        )

        data = r.json()

        if r.status_code != 200 or data.get("status") == "error":
            return {
                "status":"error",
                "symbol":symbol,
                "message":data.get("message","Market data unavailable")
            }

        return {
            "status":"ok",
            "symbol":data.get("symbol",symbol),
            "price":data.get("close") or data.get("price"),
            "change":data.get("change"),
            "percent_change":data.get("percent_change"),
            "open":data.get("open"),
            "high":data.get("high"),
            "low":data.get("low"),
            "datetime":data.get("datetime"),
            "market_open":data.get("is_market_open")
        }

    except Exception as e:

        return {
            "status":"error",
            "symbol":symbol,
            "message":str(e)
        }


@app.route("/api/market")
def api_market():

    result = {}

    for name,symbol in SYMBOLS.items():
        result[name] = twelve_quote(symbol)

    return jsonify({
        "status":"online",
        "provider":"Twelve Data",
        "timestamp":datetime.utcnow().isoformat(),
        "markets":result
    })

# ---------------------------------------------------------
# MARKET PAGE
# ---------------------------------------------------------

@app.route("/market")
def market():

    cards = ""

    for name,symbol in SYMBOLS.items():

        cards += f"""
<div class="card">
<p class="eyebrow">{name}</p>
<h2>{symbol}</h2>

<div class="quote" id="price-{name}">
Loading...
</div>

<div id="change-{name}" class="muted">
Waiting for market data...
</div>

</div>
"""

    body = f"""
<div class="hero">
<p class="eyebrow">TW TRADES MARKET</p>
<h1>Market Intelligence</h1>

<p>
Live market information from the configured market-data provider.
</p>

<p class="small muted">
Data refreshes automatically. Availability depends on your
Twelve Data plan and instrument coverage.
</p>
</div>

<br>

<div class="grid">
{cards}
</div>

<br>

<div class="card">

<h2>Financial News</h2>

<div id="news">
Loading latest market news...
</div>

</div>

<br>

<div class="card">

<h2>Market Status</h2>

<p>
<span class="status"></span>
TW Trades market engine online
</p>

<p class="muted">
London • New York • Asia • South Africa
</p>

</div>

<script>

async function loadMarket(){{

    try{{

        const response = await fetch('/api/market');
        const data = await response.json();

        for(const [name,item] of Object.entries(data.markets)){{

            const price = document.getElementById('price-'+name);
            const change = document.getElementById('change-'+name);

            if(item.status === 'ok'){{

                price.innerText =
                    item.price ? item.price : 'No price';

                let c = item.change || '0';
                let p = item.percent_change || '0';

                change.innerText =
                    'Change: ' + c + ' (' + p + '%)' +
                    (item.market_open === true ? ' • OPEN' : '');

            }}else{{

                price.innerText = 'Unavailable';

                change.innerText =
                    item.message || 'Data unavailable';
            }}
        }}

    }}catch(e){{

        console.log(e);

    }}
}}


async function loadNews(){{

    try{{

        const response = await fetch('/api/news');
        const data = await response.json();

        const box = document.getElementById('news');

        if(!data.articles || data.articles.length === 0){{

            box.innerHTML =
                '<p class="muted">'+
                (data.message || 'No news available.')+
                '</p>';

            return;
        }}

        box.innerHTML = data.articles.map(a => `

            <a class="news" href="${{a.url}}" target="_blank">

                <strong>${{a.title || ''}}</strong>

                <div class="small muted">
                ${{a.source || ''}}
                ${{a.publishedAt || ''}}
                </div>

            </a>

        `).join('');

    }}catch(e){{

        document.getElementById('news').innerText =
            'News service unavailable.';
    }}
}}


loadMarket();
loadNews();

setInterval(loadMarket, 60000);
setInterval(loadNews, 300000);

</script>
"""

    return page("Market", body)

# ---------------------------------------------------------
# NEWS
# ---------------------------------------------------------

@app.route("/api/news")
def api_news():

    s = get_settings()
    key = s.get("news_api_key","").strip()

    if not key:

        return jsonify({
            "status":"not_configured",
            "message":"Add your NewsAPI key in Admin.",
            "articles":[]
        })

    try:

        r = requests.get(
            "https://newsapi.org/v2/everything",
            headers={"X-Api-Key":key},
            params={
                "q":"gold OR forex OR Federal Reserve OR USD",
                "language":"en",
                "sortBy":"publishedAt",
                "pageSize":8
            },
            timeout=10
        )

        data = r.json()

        if r.status_code != 200 or data.get("status") != "ok":

            return jsonify({
                "status":"error",
                "message":data.get(
                    "message",
                    "News service unavailable."
                ),
                "articles":[]
            })

        articles = []

        for a in data.get("articles",[]):

            articles.append({
                "title":a.get("title"),
                "description":a.get("description"),
                "url":a.get("url"),
                "source":(a.get("source") or {}).get("name"),
                "publishedAt":a.get("publishedAt")
            })

        return jsonify({
            "status":"ok",
            "articles":articles
        })

    except Exception as e:

        return jsonify({
            "status":"error",
            "message":str(e),
            "articles":[]
        })

# ---------------------------------------------------------
# TERMINAL
# ---------------------------------------------------------

@app.route("/terminal")
def terminal():

    s = get_settings()

    yuki = s.get("yuki_url") or "#"
    titan = s.get("titan_url") or "#"

    body = f"""
<div class="hero">

<p class="eyebrow">TW TRADES TERMINAL</p>

<h1>Trading Systems</h1>

<p>
Central access point for connected TW Trades tools.
</p>

</div>

<br>

<div class="grid">

<div class="card">
<p class="eyebrow">AI SYSTEM</p>
<h2>Titan X</h2>
<p class="muted">
AI-powered trading analysis environment.
</p>
<a class="btn" href="{titan}" target="_blank">
Open Titan
</a>
</div>

<div class="card">
<p class="eyebrow">AI ASSISTANT</p>
<h2>Yuki</h2>
<p class="muted">
Trading assistant and scanner interface.
</p>
<a class="btn" href="{yuki}" target="_blank">
Open Yuki
</a>
</div>

<div class="card">
<p class="eyebrow">SCANNER</p>
<h2>Market Scanner</h2>
<p class="muted">
Connected market monitoring interface.
</p>
<a class="btn dark" href="/market">
Open Scanner
</a>
</div>

</div>

<br>

<div class="card">

<h2>TW Trades Engine</h2>

<div id="engine">Checking...</div>

</div>

<script>

fetch('/api/scan')
.then(r => r.json())
.then(data => {{

document.getElementById('engine').innerHTML =
'<p><span class="status"></span>Engine: '+
data.status+
'</p>'+
'<p class="muted">Symbols: '+
data.symbols.join(' • ')+
'</p>';

}})
.catch(() => {{

document.getElementById('engine').innerText =
'Engine status unavailable';

}});

</script>
"""

    return page("Terminal", body)

# ---------------------------------------------------------
# JOURNAL
# ---------------------------------------------------------

@app.route("/journal")
def journal():

    conn = db()

    rows = conn.execute(
        "SELECT * FROM journal ORDER BY id DESC"
    ).fetchall()

    conn.close()

    cards = ""

    for r in rows:

        cards += f"""
<div class="card">

<p class="eyebrow">TW TRADES JOURNAL</p>

<h2>{r["title"]}</h2>

<p>{r["content"]}</p>

<p class="small muted">
{r["created_at"]}
</p>

</div>

<br>
"""

    if not cards:

        cards = """
<div class="card">
<h2>No journal entries yet.</h2>
<p class="muted">
Entries can be published from the Admin panel.
</p>
</div>
"""

    return page(
        "Journal",
        "<h1>Trading Journal</h1>"+cards
    )

# ---------------------------------------------------------
# ADMIN LOGIN
# ---------------------------------------------------------

@app.route("/admin", methods=["GET","POST"])
def admin_login():

    if session.get("admin"):
        return redirect(url_for("admin_dashboard"))

    error = ""

    if request.method == "POST":

        email = request.form.get("email","").strip()
        password = request.form.get("password","")

        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:

            session["admin"] = True

            return redirect(url_for("admin_dashboard"))

        error = """
<div class="alert danger">
Invalid administrator credentials.
</div>
"""

    body = f"""
<h1>Admin Login</h1>

{error}

<div class="card">

<form method="POST">

<label>Email</label>
<input name="email" type="email" required>

<label>Password</label>
<input name="password" type="password" required>

<button class="btn" type="submit">
Login
</button>

</form>

</div>
"""

    return page("Admin", body)

# ---------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------

@app.route("/admin/logout")
def admin_logout():

    session.clear()

    return redirect(url_for("admin_login"))

# ---------------------------------------------------------
# ADMIN DASHBOARD
# ---------------------------------------------------------

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():

    conn = db()

    requests_data = conn.execute(
        "SELECT * FROM requests ORDER BY id DESC"
    ).fetchall()

    journal_data = conn.execute(
        "SELECT * FROM journal ORDER BY id DESC"
    ).fetchall()

    conn.close()

    s = get_settings()

    rows = ""

    for r in requests_data:

        rows += f"""
<tr>
<td>{r["id"]}</td>
<td>{r["name"]}</td>
<td>{r["email"]}</td>
<td>{r["phone"]}</td>
<td>{r["package"]}</td>
<td><span class="badge">{r["status"]}</span></td>
<td>{r["created_at"]}</td>
</tr>
"""

    if not rows:

        rows = """
<tr>
<td colspan="7">No requests yet.</td>
</tr>
"""

    body = f"""
<h1>Admin Dashboard</h1>

<div class="alert">

<strong>TW Trades administration is online.</strong>

<br>

Requests are stored locally in the database.

</div>

<div class="grid">

<div class="card">
<p class="eyebrow">REQUESTS</p>
<h2>{len(requests_data)}</h2>
</div>

<div class="card">
<p class="eyebrow">JOURNAL</p>
<h2>{len(journal_data)}</h2>
</div>

<div class="card">
<p class="eyebrow">WHATSAPP 1</p>
<p>+27 69 734 3252</p>
</div>

<div class="card">
<p class="eyebrow">WHATSAPP 2</p>
<p>+27 69 311 8405</p>
</div>

</div>

<br>

<div class="card">

<h2>API & Business Settings</h2>

<form method="POST" action="/admin/settings">

<label>Owner Email</label>
<input name="owner_email" value="{s["owner_email"]}">

<label>Instagram</label>
<input name="instagram" value="{s["instagram"]}">

<label>WhatsApp 1</label>
<input name="whatsapp1" value="{s["whatsapp1"]}">

<label>WhatsApp 2</label>
<input name="whatsapp2" value="{s["whatsapp2"]}">

<label>Twelve Data API Key</label>
<input name="twelve_data_key" value="{s["twelve_data_key"]}" autocomplete="off">

<label>NewsAPI Key</label>
<input name="news_api_key" value="{s["news_api_key"]}" autocomplete="off">

<label>Yuki URL</label>
<input name="yuki_url" value="{s["yuki_url"]}">

<label>Titan X URL</label>
<input name="titan_url" value="{s["titan_url"]}">

<label>Basic Price</label>
<input name="package_basic" value="{s["package_basic"]}">

<label>Pro Price</label>
<input name="package_pro" value="{s["package_pro"]}">

<label>Elite Price</label>
<input name="package_elite" value="{s["package_elite"]}">

<button class="btn" type="submit">
Save Settings
</button>

</form>

</div>

<br>

<div class="card">

<h2>Access Requests</h2>

<div style="overflow:auto">

<table>

<tr>
<th>ID</th>
<th>Name</th>
<th>Email</th>
<th>Phone</th>
<th>Package</th>
<th>Status</th>
<th>Date</th>
</tr>

{rows}

</table>

</div>

</div>

<br>

<div class="card">

<h2>Publish Journal Entry</h2>

<form method="POST" action="/admin/journal">

<label>Title</label>
<input name="title" required>

<label>Content</label>
<textarea name="content"></textarea>

<button class="btn" type="submit">
Publish
</button>

</form>

</div>

<br>

<a class="btn dark" href="/admin/logout">
Logout
</a>
"""

    return page("Admin Dashboard", body)

# ---------------------------------------------------------
# ADMIN SETTINGS
# ---------------------------------------------------------

@app.route("/admin/settings", methods=["POST"])
@admin_required
def admin_settings():

    keys = [
        "owner_email",
        "instagram",
        "whatsapp1",
        "whatsapp2",
        "twelve_data_key",
        "news_api_key",
        "yuki_url",
        "titan_url",
        "package_basic",
        "package_pro",
        "package_elite"
    ]

    for key in keys:
        save_setting(
            key,
            request.form.get(key,"").strip()
        )

    return redirect(url_for("admin_dashboard"))

# ---------------------------------------------------------
# JOURNAL ADMIN
# ---------------------------------------------------------

@app.route("/admin/journal", methods=["POST"])
@admin_required
def admin_journal():

    title = request.form.get("title","").strip()
    content = request.form.get("content","").strip()

    if title:

        conn = db()

        conn.execute("""
            INSERT INTO journal(title,content,created_at)
            VALUES(?,?,?)
        """,(
            title,
            content,
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

    return redirect(url_for("admin_dashboard"))

# ---------------------------------------------------------
# API SCAN
# ---------------------------------------------------------

@app.route("/api/scan")
def api_scan():

    return jsonify({
        "status":"online",
        "platform":"TW Trades",
        "engine":"Titan / Yuki",
        "timestamp":datetime.utcnow().isoformat(),
        "symbols":list(SYMBOLS.keys())
    })

# ---------------------------------------------------------
# HEALTH
# ---------------------------------------------------------

@app.route("/health")
def health():

    try:

        conn = db()
        conn.execute("SELECT 1").fetchone()
        conn.close()

        return jsonify({
            "status":"healthy",
            "database":"online",
            "platform":"TW Trades",
            "timestamp":datetime.utcnow().isoformat()
        })

    except Exception as e:

        return jsonify({
            "status":"error",
            "database":"offline",
            "error":str(e)
        }),500

# ---------------------------------------------------------
# ERROR
# ---------------------------------------------------------

@app.errorhandler(Exception)
def handle_error(error):

    app.logger.exception("Website error")

    return page(
        "Error",
        f"""
<div class="alert danger">
<h2>Website error</h2>
<p>{error}</p>
</div>

<a class="btn" href="/">Return Home</a>
"""
    ),500

# ---------------------------------------------------------
# START
# ---------------------------------------------------------

if __name__ == "__main__":

    port = int(os.environ.get("PORT","8080"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
