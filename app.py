import os
import sqlite3
import secrets
import hashlib
import threading
import time
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timezone
from flask import Flask, request, jsonify, session, redirect, render_template_string

PUBLIC_ACCESS_PRICE = "R400"
WHATSAPP_NUMBER = "27697343252"
INSTAGRAM_URL = "https://instagram.com/ashleysnowfx"
TIKTOK_URL = "https://tiktok.com/@snowFx3"
REQUEST_URL = "https://tw-trades-1.onrender.com/#request"

def send_discord_signal(signal):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        app.logger.warning("Discord webhook is not configured.")
        return False

    message = (
        f"📈 **TW TRADES | NEW SIGNAL**\n"
        f"**Symbol:** {signal['symbol']}\n"
        f"**Direction:** {signal['direction']}\n"
        f"**Session:** {signal['session']}\n"
        f"**Entry:** {signal['entry']}\n"
        f"**Stop-loss:** {signal['stop']}\n"
        f"**TP1:** {signal['tp1']}\n"
        f"**TP2:** {signal['tp2']}\n"
        f"**Score:** {signal['score']}\n"
        f"**Analysis:** {signal['reason']}\n"
        f"⚠️ Trading involves risk. Verify the setup before acting."
    )

    try:
        response = requests.post(
            webhook_url,
            json={"content": message},
            timeout=8
        )
        response.raise_for_status()
        return True
    except Exception:
        app.logger.exception("Discord signal delivery failed.")
        return False

app = Flask(__name__)


@app.after_request
def _security_headers(response):
    """Baseline security headers for every response.

    The Content-Security-Policy is served in report-only mode: the workspace page
    embeds TradingView widgets and inline scripts, so enforcing a policy without a
    visual check could blank out the charts. Report-only records violations now so
    the policy can be tightened and then enforced safely.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy-Report-Only",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https:; "
        "frame-src 'self' https:; "
        "connect-src 'self' https:; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
@app.route("/robots.txt")
def robots_txt():
    from flask import Response
    content = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /admin
"""
    return Response(content, mimetype="text/plain")
@app.route("/google6e5d7fb63d6d81b1.html")
def google_site_verification():
    return (
        "google-site-verification: google6e5d7fb63d6d81b1.html",
        200,
        {"Content-Type": "text/html; charset=utf-8"}
    )

def _load_secret_key():
    """Return one signing key shared by every gunicorn worker.

    A random per-process key makes sessions fail intermittently (worker A signs
    a cookie that worker B rejects) and logs everyone out on every restart.
    The durable fix is setting FLASK_SECRET_KEY in the environment; until then
    persist a generated key so all workers on this instance agree.
    """
    configured = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if configured:
        return configured

    key_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".flask_secret_key")
    try:
        if os.path.exists(key_path):
            stored = open(key_path, encoding="utf-8").read().strip()
            if stored:
                return stored
        generated = secrets.token_hex(32)
        with open(key_path, "w", encoding="utf-8") as handle:
            handle.write(generated)
        os.chmod(key_path, 0o600)
        app.logger.warning(
            "FLASK_SECRET_KEY is not set. Using a generated key stored at %s. "
            "Set FLASK_SECRET_KEY in the environment for sessions that survive restarts.",
            key_path,
        )
        return generated
    except OSError as exc:
        app.logger.warning(
            "FLASK_SECRET_KEY is not set and the generated key could not be stored (%s). "
            "Sessions will break across workers until FLASK_SECRET_KEY is configured.",
            exc,
        )
        return secrets.token_hex(32)


app.secret_key = _load_secret_key()

# Session cookie hygiene. Secure is switched on for HTTPS hosts so local http
# testing still works.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
if (os.environ.get("RENDER", "").strip().lower() in ("1", "true", "yes")
        or os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")):
    app.config["SESSION_COOKIE_SECURE"] = True


# ============================================================
# PASSWORD HASHING
#
# Single-round unsalted SHA-256 is fast to brute force and identical passwords
# produced identical hashes. PBKDF2-HMAC-SHA256 with a per-password salt and a
# high iteration count replaces it. Legacy hashes still verify and are upgraded
# on the owner's next successful login.
# ============================================================

PBKDF2_ITERATIONS = 260000
PBKDF2_PREFIX = "pbkdf2_sha256$"


def _hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()
    return PBKDF2_PREFIX + str(PBKDF2_ITERATIONS) + "$" + salt + "$" + digest


def _needs_rehash(stored):
    return not stored or not str(stored).startswith(PBKDF2_PREFIX)


def _verify_password(password, stored):
    """Verify a password against a PBKDF2 or legacy SHA-256 hash."""
    if not password or not stored:
        return False
    stored = str(stored)
    if stored.startswith(PBKDF2_PREFIX):
        try:
            _, iterations, salt, digest = stored.split("$", 3)
            calculated = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
            ).hex()
            return secrets.compare_digest(calculated, digest)
        except (ValueError, TypeError):
            return False
    legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return secrets.compare_digest(legacy, stored)


# ============================================================
# LOGIN THROTTLING
#
# Per-process, in-memory, and deliberately simple. It raises the cost of
# guessing without needing extra infrastructure.
# ============================================================

LOGIN_MAX_FAILURES = 8
LOGIN_WINDOW_SECONDS = 900

_LOGIN_ATTEMPTS = {}
_LOGIN_LOCK = threading.Lock()


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _login_blocked(scope, client):
    now = time.monotonic()
    with _LOGIN_LOCK:
        failures = [t for t in _LOGIN_ATTEMPTS.get((scope, client), [])
                    if now - t < LOGIN_WINDOW_SECONDS]
        _LOGIN_ATTEMPTS[(scope, client)] = failures
        return len(failures) >= LOGIN_MAX_FAILURES


def _login_failed(scope, client):
    now = time.monotonic()
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.setdefault((scope, client), []).append(now)


def _login_succeeded(scope, client):
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop((scope, client), None)


def _too_many_attempts_page():
    return (
        "<!doctype html><html><head><meta name=\"viewport\" "
        "content=\"width=device-width,initial-scale=1\"><title>Too many attempts</title>"
        "<style>body{margin:0;min-height:100vh;display:flex;align-items:center;"
        "justify-content:center;background:#05070b;color:#edf3fb;font-family:Arial}"
        ".box{max-width:420px;padding:28px;border:1px solid #203348;border-radius:18px;"
        "background:#0b1119}p{color:#aab7c8;line-height:1.6}"
        "a{color:#00ffd0}</style></head><body><main class=\"box\">"
        "<h1>Too many attempts</h1><p>Too many failed sign-in attempts from this "
        "connection. Wait 15 minutes and try again.</p>"
        "<p><a href=\"/\">Back to TW Trades</a></p></main></body></html>"
    )

# The database path must not depend on the process working directory: a
# relative path silently creates a second, empty database whenever the app is
# started from elsewhere. It is anchored to this file, and can be pointed at a
# persistent disk with TW_DATABASE_PATH / DATABASE_PATH / DB_PATH.
def _resolve_db_path():
    for env_key in ("TW_DATABASE_PATH", "DATABASE_PATH", "DB_PATH"):
        candidate = os.environ.get(env_key, "").strip()
        if candidate:
            return os.path.abspath(os.path.expanduser(candidate))
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "tw_blueprint.db")


DB = _resolve_db_path()
SCHEMA_VERSION = "2"

MAX_DAILY = 6
MAX_PER_SESSION = 2

# Confluence floor for a promoted signal. The published scoring table is
# 4H 20 + 1H 15 + 15M 15 + indication 15 + correction 8 + continuation 12 = 85.
# A setup that clears every mandatory structure gate therefore scores at least
# 70 (85 when the 15M trend is aligned rather than neutral), so the floor is a
# guard rather than a second, stricter gate layered on top of ICC.
MIN_CONFLUENCE = 70

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
    "DOGE/USD": {"group":"CRYPTO","td":"DOGE/USD","news":"DOGE"},

    # Deriv-style synthetic indices are listed for scanner visibility.
    # BiQuote is not assumed to support these symbols; unavailable feeds fail closed.
    "Volatility 10 Index": {"group":"SYNTHETICS","td":"R_10","news":"R_10"},
    "Volatility 25 Index": {"group":"SYNTHETICS","td":"R_25","news":"R_25"},
    "Volatility 50 Index": {"group":"SYNTHETICS","td":"R_50","news":"R_50"},
    "Volatility 75 Index": {"group":"SYNTHETICS","td":"R_75","news":"R_75"},
    "Volatility 100 Index": {"group":"SYNTHETICS","td":"R_100","news":"R_100"},
    "Boom 500 Index": {"group":"SYNTHETICS","td":"BOOM500","news":"BOOM500"},
    "Crash 500 Index": {"group":"SYNTHETICS","td":"CRASH500","news":"CRASH500"},
    "Step Index": {"group":"SYNTHETICS","td":"stpRNG","news":"stpRNG"}
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
    """Open a connection tolerant of concurrent readers and writers.

    The scanner persists signals from worker threads while requests are served,
    so a write collision should wait for the lock rather than raise.
    """
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        app.logger.warning("SQLite WAL mode could not be enabled.")
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

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL,
        access_level TEXT NOT NULL DEFAULT 'free',
        access_status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL
    )
    """)

    defaults = {
        "openai_key":"",
        "openai_model":"gpt-5.6",
        "deriv_app_id":"",
        "admin_password_hash":hashlib.sha256(
            b"change-me"
        ).hexdigest()
    }

    for k,v in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (k,v)
        )

    # A shipped default password is a known credential. Warn loudly rather than
    # silently accepting it, and never reset a password the owner already set.
    seeded = c.execute(
        "SELECT value FROM settings WHERE key='admin_password_hash'"
    ).fetchone()
    legacy_default = hashlib.sha256(b"change-me").hexdigest()
    if seeded and str(seeded["value"]) == legacy_default and not os.environ.get("ADMIN_PASSWORD"):
        app.logger.warning(
            "Admin password is still the shipped default. Set ADMIN_PASSWORD in the "
            "environment, or sign in and change it in TW Control Center."
        )

    _migrate_schema(c)

    # Read the state directly: get_setting() is defined further down the module
    # and is not available yet while init_db() runs at import time.
    try:
        state_row = c.execute(
            "SELECT value FROM settings WHERE key='admin_hash_state'"
        ).fetchone()
        hash_state = state_row["value"] if state_row else "unknown"
    except sqlite3.DatabaseError:
        hash_state = "unknown"

    c.commit()
    c.close()

    app.logger.info("Database ready at %s (schema %s, password hashes %s)",
                    DB, SCHEMA_VERSION, hash_state)


def _ensure_columns(c, table, columns):
    """Add only missing columns. Never drops, renames or rewrites anything."""
    try:
        existing = {row[1] for row in c.execute("PRAGMA table_info(" + table + ")")}
    except sqlite3.DatabaseError:
        return []
    added = []
    for name, declaration in columns:
        if name in existing:
            continue
        try:
            c.execute("ALTER TABLE " + table + " ADD COLUMN " + name + " " + declaration)
            added.append(name)
        except sqlite3.DatabaseError:
            app.logger.warning("Could not add column %s.%s during migration.", table, name)
    return added


def password_hash_audit():
    """Count accounts still on legacy hashes. No password is ever recoverable."""
    try:
        c = db()
        rows = c.execute("SELECT password_hash FROM users").fetchall()
        c.close()
    except sqlite3.DatabaseError:
        return {"accounts": 0, "pbkdf2": 0, "legacy_sha256": 0, "pending_upgrade": []}
    legacy = [r["password_hash"] for r in rows
              if not str(r["password_hash"] or "").startswith(PBKDF2_PREFIX)]
    return {
        "accounts": len(rows),
        "pbkdf2": len(rows) - len(legacy),
        "legacy_sha256": len(legacy),
        "pending_upgrade": len(legacy),
        "note": "Legacy hashes cannot be converted without each password; they upgrade on next successful login.",
    }


def _migrate_schema(c):
    """Reconcile an existing database with the current schema, additively."""
    added_total = []

    added_total += _ensure_columns(c, "settings", [("value", "TEXT")])
    added_total += _ensure_columns(c, "signals", [
        ("created", "TEXT"), ("symbol", "TEXT"), ("session", "TEXT"),
        ("direction", "TEXT"), ("entry", "REAL"), ("stop", "REAL"),
        ("tp1", "REAL"), ("tp2", "REAL"), ("score", "REAL"), ("reason", "TEXT"),
    ])
    added_total += _ensure_columns(c, "users", [
        ("display_name", "TEXT NOT NULL DEFAULT ''"),
        ("access_level", "TEXT NOT NULL DEFAULT 'free'"),
        ("access_status", "TEXT NOT NULL DEFAULT 'active'"),
        ("created_at", "TEXT NOT NULL DEFAULT ''"),
    ])

    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created)",
        "CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol)",
    ):
        try:
            c.execute(statement)
        except sqlite3.DatabaseError:
            app.logger.warning("Index creation skipped: %s", statement)

    c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('schema_version',?)",
              (SCHEMA_VERSION,))
    c.execute("UPDATE settings SET value=? WHERE key='schema_version'", (SCHEMA_VERSION,))

    audit = password_hash_audit()
    state = ("pbkdf2" if audit["legacy_sha256"] == 0
             else "legacy-pending" if audit["pbkdf2"] == 0
             else "mixed")
    c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('admin_hash_state',?)", (state,))
    c.execute("UPDATE settings SET value=? WHERE key='admin_hash_state'", (state,))

    if added_total:
        app.logger.warning("Schema migration added columns: %s", ", ".join(added_total))
    if audit["pending_upgrade"]:
        app.logger.warning(
            "%s account(s) still use legacy password hashes and will upgrade on next login.",
            audit["pending_upgrade"],
        )


init_db()

def get_setting(key):
    # Render environment variables take precedence for deployment-wide settings.
    # This avoids relying on instance-local SQLite state for the Deriv App ID.
    if key == "deriv_app_id":
        env_app_id = os.environ.get("DERIV_APP_ID", "").strip()
        if env_app_id:
            return env_app_id

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

def fx_market_closed(now=None):
    """Approximate weekly FX/gold closure in UTC; broker holidays may differ."""
    now = now or datetime.now(timezone.utc)
    weekday = now.weekday()  # Monday=0, Sunday=6
    hour = now.hour
    return (
        weekday == 5
        or (weekday == 6 and hour < 22)
        or (weekday == 4 and hour >= 21)
    )


def current_session(group=None):
    now = datetime.now(timezone.utc)
    # Crypto and synthetic indices are generally available 24/7, but each
    # broker/provider's maintenance windows still apply.
    if group in ("CRYPTO", "SYNTHETICS"):
        return "24/7"
    if fx_market_closed(now):
        return "OFF-SESSION"

    hour = now.hour
    for name,(start,end) in SESSIONS.items():
        if start <= hour < end:
            return name

    return "OFF-SESSION"

# ============================================================
# MARKET DATA
# ============================================================


import os

def _valid_ohlc(values, minimum=30):
    """Reject malformed, non-finite, or impossible candles before analysis."""
    import math
    if not isinstance(values, list) or len(values) < minimum:
        return False
    for bar in values:
        try:
            o, h, low, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
            if not all(math.isfinite(v) and v > 0 for v in (o, h, low, c)):
                return False
            if h < max(o, c, low) or low > min(o, c, h):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def biquote_candles(symbol, interval, size=100):
    """Read public OHLC candles; never substitute prices or fabricate bars."""
    symbol_map = {
        "XAU/USD": "XAUUSD", "EUR/USD": "EURUSD", "GBP/USD": "GBPUSD",
        "USD/JPY": "USDJPY", "GBP/JPY": "GBPJPY", "EUR/JPY": "EURJPY",
        "EUR/AUD": "EURAUD", "GBP/AUD": "GBPAUD", "USD/CHF": "USDCHF",
        "AUD/USD": "AUDUSD", "USD/CAD": "USDCAD",
        "IXIC": "IXIC", "DJI": "DJI", "SPX": "SPX", "DAX": "DAX",
        "FTSE": "FTSE", "VIX": "VIX",
        "BTC/USD": "BTCUSD", "ETH/USD": "ETHUSD", "SOL/USD": "SOLUSD",
        "XRP/USD": "XRPUSD", "ADA/USD": "ADAUSD", "DOGE/USD": "DOGEUSD"
    }
    interval_map = {"4h": "4h", "1h": "1h", "15min": "15m", "5min": "5m"}
    provider_symbol = symbol_map.get(symbol, symbol.replace("/", ""))
    provider_interval = interval_map.get(interval, interval)
    try:
        response = requests.get(
            f"https://biquote.io/api/{provider_symbol}/ohlc",
            params={"interval": provider_interval, "limit": min(int(size) + 10, 1000)},
            timeout=8
        )
        response.raise_for_status()
        payload = response.json()
        bars = payload.get("bars", [])
        if not isinstance(bars, list) or not bars:
            return None, "BiQuote returned no candles for " + provider_symbol, None
        # API is newest-first. Drop the forming candle and retain the newest closed bars.
        closed = [bar for bar in bars if not bar.get("isOpen", False)]
        selected = list(reversed(closed[:int(size)]))
        values = [{
            "time": bar.get("openTime", ""),
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"])
        } for bar in selected]
        if not _valid_ohlc(values):
            return None, "BiQuote returned malformed or insufficient completed candles for " + provider_symbol, None

        # Fail closed on stale data while the relevant market is expected open.
        # Crypto and synthetic indices are treated as 24/7; FX/metals/index
        # freshness checks are suspended during the approximate weekly closure.
        latest_time = values[-1].get("time")
        try:
            stamp = datetime.fromisoformat(str(latest_time).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age_seconds = (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()
            age_seconds = max(0, age_seconds)
        except (TypeError, ValueError):
            return None, "Latest BiQuote candle has an invalid timestamp for " + provider_symbol, None

        group = next((item.get("group") for item in ASSETS.values()
                      if item.get("td") == symbol), "FOREX")
        market_expected_open = (
            group in ("CRYPTO", "SYNTHETICS")
            or not fx_market_closed()
        )
        interval_seconds = {"5min": 300, "15min": 900, "1h": 3600, "4h": 14400}.get(interval, 300)
        freshness_limit = max(1200, interval_seconds * 2 + 300)
        if market_expected_open and age_seconds > freshness_limit:
            return None, (
                "Stale market data rejected for " + provider_symbol +
                ": latest completed candle is " + str(round(age_seconds / 60)) +
                " minutes old; limit is " + str(round(freshness_limit / 60)) + " minutes."
            )
        return values, None, "BiQuote public OHLC feed"
    except Exception as exc:
        return None, "BiQuote market feed failed: " + str(exc), None


def deriv_candles(symbol, interval, size=100):
    """Fetch real OHLC candles from Deriv's public market-data WebSocket."""
    import json
    import re
    import websocket

    app_id = get_setting("deriv_app_id").strip()
    if not app_id or not app_id.isdigit():
        return None, "Deriv App ID is not configured. Add your own App ID in TW Control Center.", None
    granularity = {"5min": 300, "15min": 900, "1h": 3600, "4h": 14400}.get(interval)
    if not granularity:
        return None, "Unsupported Deriv candle interval: " + str(interval), None

    aliases = {
        "R_10": ["R_10", "Volatility 10 Index"],
        "R_25": ["R_25", "Volatility 25 Index"],
        "R_50": ["R_50", "Volatility 50 Index"],
        "R_75": ["R_75", "Volatility 75 Index"],
        "R_100": ["R_100", "Volatility 100 Index"],
        "BOOM500": ["BOOM500", "Boom 500 Index"],
        "CRASH500": ["CRASH500", "Crash 500 Index"],
        "stpRNG": ["stpRNG", "Step Index"],
        "BTC/USD": ["BTC/USD", "BTCUSD", "Bitcoin"],
        "ETH/USD": ["ETH/USD", "ETHUSD", "Ethereum"],
        "SOL/USD": ["SOL/USD", "SOLUSD", "Solana"],
        "XRP/USD": ["XRP/USD", "XRPUSD", "XRP"],
        "ADA/USD": ["ADA/USD", "ADAUSD", "Cardano"],
        "DOGE/USD": ["DOGE/USD", "DOGEUSD", "Dogecoin"],
    }
    def norm(value):
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    target_aliases = [norm(value) for value in aliases.get(symbol, [symbol])]
    ws = None
    try:
        ws = websocket.create_connection(
            "wss://ws.derivws.com/websockets/v3?app_id=" + app_id,
            timeout=10,
            enable_multithread=False
        )
        ws.send(json.dumps({
            "active_symbols": "brief",
            "product_type": "basic",
            "req_id": 731
        }))
        active = None
        for _ in range(8):
            message = json.loads(ws.recv())
            if message.get("error"):
                return None, "Deriv symbol lookup failed: " + str(message["error"].get("message", "API error")), None
            if message.get("req_id") == 731 or message.get("msg_type") == "active_symbols":
                active = message.get("active_symbols")
                if isinstance(active, list):
                    break
        if not isinstance(active, list) or not active:
            return None, "Deriv returned no active-symbol catalogue.", None

        deriv_symbol = None
        for item in active:
            code = str(item.get("symbol", ""))
            display = str(item.get("display_name", ""))
            if norm(code) in target_aliases or norm(display) in target_aliases:
                deriv_symbol = code
                break
        if not deriv_symbol:
            return None, "Deriv does not currently list an active symbol matching " + str(symbol) + ".", None

        ws.send(json.dumps({
            "ticks_history": deriv_symbol,
            "adjust_start_time": 1,
            "count": min(max(int(size), 30), 500),
            "end": "latest",
            "style": "candles",
            "granularity": granularity,
            "req_id": 732
        }))
        response_data = None
        for _ in range(8):
            message = json.loads(ws.recv())
            if message.get("error"):
                return None, "Deriv rejected " + deriv_symbol + ": " + str(message["error"].get("message", "API error")), None
            if message.get("req_id") == 732 or message.get("msg_type") == "candles":
                response_data = message
                break
        if not isinstance(response_data, dict):
            return None, "Deriv did not return candle history for " + deriv_symbol, None

        raw_candles = response_data.get("candles", [])
        if not isinstance(raw_candles, list) or not raw_candles:
            return None, "Deriv returned no candle history for " + deriv_symbol, None

        values = []
        for candle in raw_candles:
            try:
                values.append({
                    "time": datetime.fromtimestamp(int(candle["epoch"]), timezone.utc).isoformat(),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"])
                })
            except (KeyError, TypeError, ValueError, OverflowError):
                return None, "Deriv returned a malformed candle for " + deriv_symbol, None

        values.sort(key=lambda item: item["time"])
        if not _valid_ohlc(values, minimum=min(30, int(size))):
            return None, "Deriv returned malformed or insufficient completed candles for " + deriv_symbol, None

        age_seconds = max(0, (datetime.now(timezone.utc) -
                              datetime.fromisoformat(values[-1]["time"])).total_seconds())
        freshness_limit = max(1200, granularity * 2 + 300)
        if age_seconds > freshness_limit:
            return None, (
                "Stale Deriv data rejected for " + deriv_symbol + ": latest candle is " +
                str(round(age_seconds / 60)) + " minutes old."
            ), None
        return values, None, "Deriv public WebSocket"
    except Exception as exc:
        return None, "Deriv market feed failed for " + str(symbol) + ": " + str(exc), None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
def market_source_label(group=None):
    """Accurate human-readable label for the feed that actually serves a group."""
    if group == "SYNTHETICS":
        return "Deriv public WebSocket"
    if group == "INDICES":
        return "Yahoo Finance chart API"
    return "BiQuote public OHLC feed"


def group_for_provider_symbol(symbol):
    """Map a provider symbol (the ASSETS 'td' value) back to its asset group."""
    return next((item.get("group") for item in ASSETS.values()
                 if item.get("td") == symbol), None)


# Cash-session windows in UTC hours, per index. Holidays are not modelled.
INDEX_SESSIONS = {
    "IXIC": (13.5, 20.0),   # Nasdaq, US cash session
    "DJI": (13.5, 20.0),    # Dow Jones, US cash session
    "SPX": (13.5, 20.0),    # S&P 500, US cash session
    "VIX": (13.5, 20.0),    # CBOE volatility, US cash session
    "DAX": (7.0, 15.5),     # Xetra
    "FTSE": (8.0, 16.5),    # London Stock Exchange
}


def index_market_open(provider_symbol, now=None):
    """Is this index's cash session open right now?"""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    window = INDEX_SESSIONS.get(provider_symbol)
    if not window:
        return False
    hour = now.hour + now.minute / 60.0
    return window[0] <= hour <= window[1]


def market_expected_open(group, symbol=None):
    """Is this market expected to be trading right now?

    Used so a closed market reports as closed rather than as a broken feed.
    """
    if group in ("CRYPTO", "SYNTHETICS"):
        return True
    if group == "INDICES":
        return index_market_open(symbol)
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    return not fx_market_closed(now)


def _freshness_limit(interval, granularity):
    return max(1200, granularity * 2 + 300)


def _candle_age_seconds(values):
    """Age in seconds of the newest candle, or None when unparseable."""
    try:
        stamp = datetime.fromisoformat(str(values[-1].get("time")).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError, IndexError):
        return None


YAHOO_SYMBOLS = {
    "XAU/USD": "GC=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "EUR/JPY": "EURJPY=X",
    "EUR/AUD": "EURAUD=X",
    "GBP/AUD": "GBPAUD=X",
    "USD/CHF": "USDCHF=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CAD": "USDCAD=X",
    "IXIC": "^IXIC",
    "DJI": "^DJI",
    "SPX": "^GSPC",
    "DAX": "^GDAXI",
    "FTSE": "^FTSE",
    "VIX": "^VIX",
    "BTC/USD": "BTC-USD",
    "ETH/USD": "ETH-USD",
    "SOL/USD": "SOL-USD",
    "XRP/USD": "XRP-USD",
    "ADA/USD": "ADA-USD",
    "DOGE/USD": "DOGE-USD",
}

YAHOO_GRANULARITY = {"5min": 300, "15min": 900, "1h": 3600, "4h": 14400}


def yahoo_candles(symbol, interval, size=100):
    """Completed OHLC candles from Yahoo Finance's public chart API.

    Yahoo has no native 4h interval, so 4h is built by aggregating real 60m
    candles into four-hour buckets. Aggregation never invents a bar: open and
    close come from real bars and high/low are real extremes.
    """
    import urllib.parse

    granularity = YAHOO_GRANULARITY.get(interval)
    if not granularity:
        return None, "Unsupported Yahoo interval: " + str(interval), None

    ticker = YAHOO_SYMBOLS.get(symbol)
    if not ticker:
        return None, "No Yahoo Finance symbol mapped for " + str(symbol), None

    group = group_for_provider_symbol(symbol)
    is_four_hour = interval == "4h"
    yahoo_interval = "60m" if is_four_hour else {"5min": "5m", "15min": "15m", "1h": "60m"}[interval]
    yahoo_range = "6mo" if is_four_hour else "1mo"

    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" +
           urllib.parse.quote(ticker) + "?interval=" + yahoo_interval +
           "&range=" + yahoo_range)
    try:
        response = requests.get(url, timeout=12, headers={
            "User-Agent": "Mozilla/5.0 (compatible; TW-Trades-Intelligence/1.0)",
            "Accept": "application/json",
        })
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        return None, "Yahoo Finance timed out for " + ticker, None
    except (requests.RequestException, ValueError) as exc:
        return None, "Yahoo Finance feed failed for " + ticker + ": " + str(exc), None
    except Exception as exc:
        return None, "Yahoo Finance feed failed for " + ticker + ": " + str(exc), None

    try:
        result = (payload.get("chart", {}).get("result") or [None])[0]
        if not result:
            error = payload.get("chart", {}).get("error") or {}
            return None, "Yahoo Finance returned no series for " + ticker + ": " + str(error.get("description", "empty result")), None
        stamps = result.get("timestamp") or []
        quote = (result.get("indicators", {}).get("quote") or [{}])[0]
        opens, highs, lows, closes = (quote.get("open") or [], quote.get("high") or [],
                                      quote.get("low") or [], quote.get("close") or [])
    except (AttributeError, IndexError, TypeError):
        return None, "Yahoo Finance returned an unreadable payload for " + ticker, None

    raw = []
    for index, stamp in enumerate(stamps):
        try:
            o, h, l, c = opens[index], highs[index], lows[index], closes[index]
        except IndexError:
            continue
        if None in (o, h, l, c):
            continue
        raw.append({
            "epoch": int(stamp),
            "time": datetime.fromtimestamp(int(stamp), timezone.utc).isoformat(),
            "open": float(o), "high": float(h), "low": float(l), "close": float(c),
        })

    if not raw:
        return None, "Yahoo Finance returned no usable candles for " + ticker, None

    if is_four_hour:
        buckets = {}
        for bar in raw:
            moment = datetime.fromtimestamp(bar["epoch"], timezone.utc)
            key = moment.replace(minute=0, second=0, microsecond=0, hour=(moment.hour // 4) * 4)
            label = key.isoformat()
            current = buckets.get(label)
            if current is None:
                buckets[label] = {"time": label, "open": bar["open"], "high": bar["high"],
                                  "low": bar["low"], "close": bar["close"], "_last": bar["epoch"]}
            else:
                current["high"] = max(current["high"], bar["high"])
                current["low"] = min(current["low"], bar["low"])
                current["close"] = bar["close"]
                current["_last"] = bar["epoch"]
        ordered = [buckets[k] for k in sorted(buckets)]
        now_epoch = datetime.now(timezone.utc).timestamp()
        # A bucket is complete once the wall clock has passed its own end time.
        # Comparing against the last hourly bar instead would discard the newest
        # completed bucket for most of the following four hours.
        completed = []
        for bucket in ordered:
            start_epoch = datetime.fromisoformat(bucket["time"]).timestamp()
            if now_epoch >= start_epoch + granularity:
                completed.append(bucket)
        values = [{k: v for k, v in b.items() if k != "_last"} for b in completed]
    else:
        values = [{"time": b["time"], "open": b["open"], "high": b["high"],
                   "low": b["low"], "close": b["close"]} for b in raw]
        # Drop the still-forming candle using the newest bar's own timestamp.
        now_epoch = datetime.now(timezone.utc).timestamp()
        values = [v for v in values
                  if now_epoch - datetime.fromisoformat(v["time"]).timestamp() >= granularity]

    values = values[-int(size):]
    if not _valid_ohlc(values, minimum=min(30, int(size))):
        return None, ("Yahoo Finance returned insufficient completed candles for " +
                      ticker + " (" + str(len(values)) + ")"), None

    age_seconds = _candle_age_seconds(values)
    if age_seconds is None:
        return None, "Yahoo Finance returned an invalid timestamp for " + ticker, None

    if market_expected_open(group, symbol) and age_seconds > _freshness_limit(interval, granularity):
        return None, ("Stale market data rejected for " + ticker + ": latest completed candle is " +
                      str(round(age_seconds / 60)) + " minutes old; limit is " +
                      str(round(_freshness_limit(interval, granularity) / 60)) + " minutes."), None

    return values, None, "Yahoo Finance chart API"


def td(symbol, interval, size=100):
    """Route each instrument to a provider verified to serve it.

    Returns (candles, error, provider).

    Verified coverage:
      * Indices: BiQuote returns HTTP 200 with an empty bar list for every
        index, so indices are served by Yahoo Finance.
      * Crypto/FX/metals: BiQuote first; Yahoo Finance when BiQuote is empty or
        stale (ADA/USD and DOGE/USD are years out of date on BiQuote).
      * Synthetics: Deriv only, and only with a configured App ID.
    """
    group = group_for_provider_symbol(symbol)

    if group == "SYNTHETICS":
        return deriv_candles(symbol, interval, size)

    primary = biquote_candles(symbol, interval, size)
    if primary[0]:
        return primary

    if group == "INDICES":
        return yahoo_candles(symbol, interval, size)

    fallback = yahoo_candles(symbol, interval, size)
    if fallback[0]:
        return fallback
    return None, primary[1] + " | Yahoo Finance fallback: " + str(fallback[1]), None

# ============================================================
# MARKET NEWS — GDELT DOC API primary, verified publisher RSS fallback
#
# GDELT publishes honest headlines but rate-limits hard (one request per
# five seconds) and rejects bursts. The engine calls news once per instrument,
# so requests are now cached and globally throttled, and a verified publisher
# RSS feed is used when GDELT is unavailable. Headlines are never converted
# into sentiment scores, because no source here supplies them.
# ============================================================

NEWS_CACHE_TTL = 600          # seconds a headline set stays fresh
GDELT_MIN_INTERVAL = 5.5      # GDELT publishes a 1-per-5-second budget
GDELT_BACKOFF = 180           # pause after a 429 before trying GDELT again
NEWS_UA = "TW-Trades-Intelligence/1.0"

_NEWS_CACHE = {}
_NEWS_CACHE_LOCK = threading.Lock()
_GDELT_LOCK = threading.Lock()
_GDELT_STATE = {"last_call": 0.0, "blocked_until": 0.0, "rate_limited": False}

NEWS_QUERIES = {
    "XAU/USD": '(gold OR bullion OR "precious metals")',
    "EUR/USD": '(euro OR EURUSD OR "European Central Bank")',
    "GBP/USD": '(sterling OR GBPUSD OR "Bank of England")',
    "USD/JPY": '(yen OR USDJPY OR "Bank of Japan")',
    "GBP/JPY": '(sterling OR yen OR GBPJPY)',
    "EUR/JPY": '(euro OR yen OR EURJPY)',
    "EUR/AUD": '(euro OR Australian dollar OR EURAUD)',
    "GBP/AUD": '(sterling OR Australian dollar OR GBPAUD)',
    "USD/CHF": '(Swiss franc OR USDCHF OR SNB)',
    "AUD/USD": '(Australian dollar OR AUDUSD OR RBA)',
    "USD/CAD": '(Canadian dollar OR USDCAD OR Bank of Canada)',
    "NASDAQ": '(Nasdaq OR technology stocks OR Nasdaq-100)',
    "US30": '("Dow Jones" OR Dow30 OR DJIA)',
    "S&P 500": '("S&P 500" OR SP500 OR "US stocks")',
    "DAX40": '(DAX OR "German stocks")',
    "FTSE100": '(FTSE OR "UK stocks")',
    "VIX": '(VIX OR "market volatility")',
    "BTC/USD": '(Bitcoin OR BTC OR cryptocurrency)',
    "ETH/USD": '(Ethereum OR ETH OR cryptocurrency)',
    "SOL/USD": '(Solana OR SOL cryptocurrency)',
    "XRP/USD": '(XRP OR Ripple cryptocurrency)',
    "ADA/USD": '(Cardano OR ADA cryptocurrency)',
    "DOGE/USD": '(Dogecoin OR DOGE cryptocurrency)',
}

# Verified Yahoo Finance publisher feeds. Each entry is tried in order and the
# first that returns real items wins; an empty result falls through to the
# general market wires rather than inventing coverage.
NEWS_RSS_SYMBOLS = {
    "XAU/USD": ["GC=F", "XAUUSD=X"],
    "EUR/USD": ["EURUSD=X"],
    "GBP/USD": ["GBPUSD=X"],
    "USD/JPY": ["USDJPY=X", "JPY=X"],
    "GBP/JPY": ["GBPJPY=X", "JPY=X"],
    "EUR/JPY": ["EURJPY=X", "JPY=X"],
    "EUR/AUD": ["EURAUD=X", "AUDUSD=X"],
    "GBP/AUD": ["GBPAUD=X", "AUDUSD=X"],
    "USD/CHF": ["USDCHF=X", "CHF=X"],
    "AUD/USD": ["AUDUSD=X"],
    "USD/CAD": ["USDCAD=X", "CAD=X"],
    "NASDAQ": ["^IXIC"],
    "US30": ["^DJI"],
    "S&P 500": ["^GSPC"],
    "DAX40": ["^GDAXI"],
    "FTSE100": ["^FTSE"],
    "VIX": ["^VIX"],
    "BTC/USD": ["BTC-USD"],
    "ETH/USD": ["ETH-USD"],
    "SOL/USD": ["SOL-USD"],
    "XRP/USD": ["XRP-USD"],
    "ADA/USD": ["ADA-USD"],
    "DOGE/USD": ["DOGE-USD"],
}

GENERAL_MARKET_FEEDS = [
    ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "WSJ Markets"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC Top News"),
]

_feed_cache = {}


def _news_payload(articles, source, scope, degraded, message, rate_limited=False):
    seen = set()
    unique = []
    for article in articles:
        key = article.get("title", "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(article)
        if len(unique) >= 10:
            break
    return {
        "available": bool(unique),
        "sentiment": 0,
        "sentiment_available": False,
        "articles": unique,
        "source": source,
        "scope": scope,
        "degraded": degraded,
        "rate_limited": rate_limited,
        "message": message,
    }


def _gdelt_slot():
    """Reserve a GDELT call only when the published rate budget allows it."""
    now = time.monotonic()
    with _GDELT_LOCK:
        if now < _GDELT_STATE["blocked_until"]:
            return False
        if now - _GDELT_STATE["last_call"] < GDELT_MIN_INTERVAL:
            return False
        _GDELT_STATE["last_call"] = now
        return True


def _gdelt_mark(result):
    """Record GDELT health so a 429 stops the whole scan from hammering it."""
    with _GDELT_LOCK:
        if result == "rate_limited":
            _GDELT_STATE["rate_limited"] = True
            _GDELT_STATE["blocked_until"] = time.monotonic() + GDELT_BACKOFF
        elif result == "ok":
            _GDELT_STATE["rate_limited"] = False
            _GDELT_STATE["blocked_until"] = 0.0


def _gdelt_articles(query):
    """Return (articles, error_kind). Never fabricates headlines."""
    try:
        response = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 10,
                "sort": "HybridRel",
            },
            timeout=10,
            headers={"User-Agent": NEWS_UA},
        )
        if response.status_code == 429:
            _gdelt_mark("rate_limited")
            return [], "rate_limited"
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return [], "bad_payload"
        articles = []
        for row in payload.get("articles", [])[:10]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            url = str(row.get("url") or "").strip()
            if not title or not url.startswith(("https://", "http://")):
                continue
            articles.append({
                "title": title,
                "url": url,
                "description": "",
                "snippet": "",
                "published_at": row.get("seendate", ""),
                "source": row.get("domain", "GDELT"),
            })
        if articles:
            _gdelt_mark("ok")
            return articles, None
        return [], "empty"
    except requests.Timeout:
        return [], "timeout"
    except (requests.RequestException, ValueError):
        return [], "unavailable"
    except Exception:
        app.logger.exception("GDELT news processing failed.")
        return [], "unavailable"


def _parse_rss(content, fallback_source):
    """Namespace-tolerant RSS item reader."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    articles = []
    for node in root.iter():
        tag = node.tag.split("}")[-1].lower()
        if tag != "item":
            continue
        fields = {}
        for child in node:
            name = child.tag.split("}")[-1].lower()
            if name in ("title", "link", "pubdate", "description"):
                fields[name] = (child.text or "").strip()
        title = fields.get("title", "")
        link = fields.get("link", "")
        if not title or not link.startswith(("https://", "http://")):
            continue
        articles.append({
            "title": title,
            "url": link,
            "description": "",
            "snippet": "",
            "published_at": fields.get("pubdate", ""),
            "source": fallback_source,
        })
    return articles


def _fetch_feed(url, label):
    now = time.monotonic()
    cached = _feed_cache.get(url)
    if cached and now - cached[0] < NEWS_CACHE_TTL:
        return cached[1]
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": NEWS_UA})
        response.raise_for_status()
        items = _parse_rss(response.content, label)
    except Exception:
        items = []
    _feed_cache[url] = (now, items)
    return items


def _rss_articles_for(symbol):
    """Instrument-level publisher headlines, else general market wires."""
    for ticker in NEWS_RSS_SYMBOLS.get(symbol, []):
        url = ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=" +
               requests.utils.quote(ticker, safe="") + "&region=US&lang=en-US")
        items = _fetch_feed(url, "Yahoo Finance")
        if items:
            return items, "Yahoo Finance", "instrument"
    for url, label in GENERAL_MARKET_FEEDS:
        items = _fetch_feed(url, label)
        if items:
            return items, label, "general"
    return [], "UNAVAILABLE", "none"


def news(symbol):
    """Headlines for one instrument. Cached, throttled, never fabricated."""
    if symbol not in ASSETS:
        return {"available": False, "sentiment": 0, "sentiment_available": False,
                "articles": [], "source": "NONE", "scope": "none",
                "degraded": True, "rate_limited": False,
                "message": "Unsupported instrument."}

    now = time.monotonic()
    with _NEWS_CACHE_LOCK:
        cached = _NEWS_CACHE.get(symbol)
        if cached and now - cached[0] < NEWS_CACHE_TTL:
            return dict(cached[1])

    gdelt_error = None
    result = None

    if symbol in NEWS_QUERIES:
        if _gdelt_slot():
            articles, gdelt_error = _gdelt_articles(NEWS_QUERIES[symbol])
            if articles:
                result = _news_payload(
                    articles,
                    source="GDELT",
                    scope="instrument",
                    degraded=False,
                    message="Headlines from GDELT. GDELT does not supply sentiment scores, so none are shown.",
                )
        else:
            gdelt_error = "rate_limited"

    if result is None:
        articles, label, scope = _rss_articles_for(symbol)
        if articles:
            if gdelt_error == "rate_limited":
                reason = "GDELT rate limit (one request per five seconds) reached"
            elif gdelt_error:
                reason = "GDELT did not respond (" + gdelt_error + ")"
            else:
                reason = "No GDELT query is defined for this instrument"
            if scope == "general":
                reason += "; showing general market wire headlines, not instrument-specific coverage"
            message = reason + ". Headlines are not treated as sentiment."
            result = _news_payload(
                articles,
                source=label,
                scope=scope,
                degraded=True,
                message=message,
                rate_limited=gdelt_error == "rate_limited",
            )
        else:
            result = {
                "available": False,
                "sentiment": 0,
                "sentiment_available": False,
                "articles": [],
                "source": "UNAVAILABLE",
                "scope": "none",
                "degraded": True,
                "rate_limited": gdelt_error == "rate_limited",
                "message": "No verified headline source responded. Technical analysis is unaffected and no sentiment is invented.",
            }

    with _NEWS_CACHE_LOCK:
        _NEWS_CACHE[symbol] = (now, dict(result))
    return result


def news_diagnostics():
    """Read-only health summary for the news layer."""
    with _GDELT_LOCK:
        blocked = max(0.0, _GDELT_STATE["blocked_until"] - time.monotonic())
        rate_limited = _GDELT_STATE["rate_limited"]
    with _NEWS_CACHE_LOCK:
        cached = len(_NEWS_CACHE)
    return {
        "primary_source": "GDELT DOC 2.0",
        "fallback_source": "Yahoo Finance / WSJ Markets / CNBC RSS (verified publishers)",
        "gdelt_rate_limited": rate_limited,
        "gdelt_backoff_seconds_remaining": round(blocked, 1),
        "min_interval_seconds": GDELT_MIN_INTERVAL,
        "cache_ttl_seconds": NEWS_CACHE_TTL,
        "cached_instruments": cached,
        "sentiment_scoring": "not available from these sources; sentiment is excluded from scoring",
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


def icc_sequence(data, direction):
    """Require indication first, then a later pullback, then continuation."""
    if len(data) < 30 or not continuation(data, direction):
        return False, False, False

    # The last candle is reserved for continuation. Search prior candles
    # for a body breakout, then require a pullback after that breakout.
    end = len(data) - 1
    start = max(20, end - 12)
    indication_index = None
    for i in range(start, end):
        history = data[i-20:i]
        candle = data[i]
        if direction == "BUY":
            level = max(body_high(x) for x in history)
            broken = candle["close"] > level
        else:
            level = min(body_low(x) for x in history)
            broken = candle["close"] < level
        if broken:
            indication_index = i

    if indication_index is None:
        return False, False, True

    # At least one completed candle between indication and continuation
    # must retrace. Do not let the final continuation candle count as pullback.
    correction_bars = data[indication_index + 1:end]
    if not correction_bars:
        return True, False, True

    indication_close = data[indication_index]["close"]
    if direction == "BUY":
        correction_ok = any(x["low"] < indication_close for x in correction_bars)
    else:
        correction_ok = any(x["high"] > indication_close for x in correction_bars)
    return True, correction_ok, True

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
            "Recent GDELT entity sentiment is materially positive."
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
            "Recent GDELT entity sentiment is materially negative."
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

    asset_group = ASSETS[symbol].get("group", "FOREX")

    # Synthetic indices exist only on Deriv. Without a configured App ID there
    # is no data source at all, so report a configuration gap rather than a
    # misleading market or data error.
    if asset_group == "SYNTHETICS" and not get_setting("deriv_app_id"):
        return {
            "symbol": symbol,
            "status": "UNSUPPORTED",
            "group": asset_group,
            "message": "Synthetic indices need a Deriv App ID. Add one in TW Control Center; until then this instrument has no live data source and is excluded from signals."
        }

    if asset_group == "INDICES":
        provider_symbol = ASSETS[symbol].get("td")
        if not index_market_open(provider_symbol):
            session_name = "US cash session" if INDEX_SESSIONS.get(provider_symbol, (0, 0))[0] >= 13 else "European cash session"
            return {
                "symbol": symbol,
                "status": "MARKET CLOSED",
                "group": asset_group,
                "market_status": "CLOSED",
                "message": ("This index's " + session_name + " is closed. The newest candles belong to an "
                            "earlier session, so no signal is generated from them."),
            }

    sess = current_session(asset_group)

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

    # Fetch all required timeframes concurrently so four slow provider
    # requests do not stack up and exceed the browser scanner timeout.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    intervals = ["4h", "1h", "15min", "5min"]
    frames = {}
    errors = []
    providers = {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {
            pool.submit(td, ASSETS[symbol]["td"], interval, 100): interval
            for interval in intervals
        }
        for job in as_completed(jobs):
            interval = jobs[job]
            try:
                data, error, provider = job.result()
            except Exception as exc:
                data, error, provider = None, str(exc), None
            if error:
                errors.append(interval + ": " + error)
            else:
                frames[interval] = data
                providers[interval] = provider

    if errors:
        return {
            "symbol": symbol,
            "status": "DATA ERROR",
            "message": "Live candle data unavailable (" + "; ".join(errors) + ")"
        }

    data_source = providers.get("1h") or market_source_label(asset_group)
    market_status = "OPEN" if market_expected_open(asset_group, ASSETS[symbol].get("td")) else "CLOSED"

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
    fund=(fundamental_view(n["sentiment"]) if n.get("sentiment_available") else {"bias":"UNAVAILABLE","impact":"UNKNOWN","description":"Headline source does not provide verified sentiment scores; sentiment excluded from scoring."})

    if n["sentiment"]>0.10:
        technical_buy+=5
        buy.append("Positive fundamental/news flow")

    elif n["sentiment"]<-0.10:
        technical_sell+=5
        sell.append("Negative fundamental/news flow")

    # ------------------------------------------------------------------
    # TW Blueprint ICC gate, evaluated independently on BOTH sides.
    #
    # Scoring first and gating second meant only one side was ever judged. With
    # a bearish 4H, a score-leaning BUY was rejected for "4H and 1H must agree"
    # while the SELL side that the 4H supports was never examined. Both sides
    # are now scored and gated with the same functions, and the side that
    # actually satisfies the Blueprint is the side that gets promoted.
    # ------------------------------------------------------------------
    def evaluate_side(side):
        wants_bull = side == "BUY"
        indication_s, correction_s, continuation_s = icc_sequence(m5, side)

        h4_aligned = t4 == ("BULLISH" if wants_bull else "BEARISH")
        h1_aligned = t1 == ("BULLISH" if wants_bull else "BEARISH")
        m15_aligned = t15 == ("BULLISH" if wants_bull else "BEARISH")
        htf_agree = h4_aligned and h1_aligned
        mid_not_opposed = t15 != ("BEARISH" if wants_bull else "BULLISH")

        # Same table as the published methodology, now driven by the exact
        # structure results the gate uses.
        points = (
            (20 if h4_aligned else 0)
            + (15 if h1_aligned else 0)
            + (15 if m15_aligned else 0)
            + (15 if indication_s else 0)
            + (8 if correction_s else 0)
            + (12 if continuation_s else 0)
        )

        gates = {
            "body-based indication": indication_s,
            "correction/retest": correction_s,
            "continuation confirmation": continuation_s,
            "4H and 1H trend agree": htf_agree,
            "15M does not oppose": mid_not_opposed,
            "confluence floor": points >= MIN_CONFLUENCE,
        }
        blockers = [name + " missing" if name in (
            "body-based indication", "correction/retest",
            "continuation confirmation") else
            ("4H and 1H trend must agree" if name == "4H and 1H trend agree" else
             ("15M trend opposes setup" if name == "15M does not oppose" else
              "confluence score below " + str(MIN_CONFLUENCE)))
            for name, passed in gates.items() if not passed]

        return {
            "side": side,
            "score": points,
            "indication": indication_s,
            "correction": correction_s,
            "continuation": continuation_s,
            "higher_timeframes_agree": htf_agree,
            "15m_not_opposed": mid_not_opposed,
            "15m_aligned": m15_aligned,
            "gates_passed": sum(1 for passed in gates.values() if passed),
            "gates_total": len(gates),
            "qualifies": all(gates.values()),
            "blockers": blockers,
        }

    side_results = {"BUY": evaluate_side("BUY"), "SELL": evaluate_side("SELL")}
    qualifying = [item for item in side_results.values() if item["qualifies"]]

    if qualifying:
        # If both sides somehow qualify, the higher-scoring structure wins.
        chosen = max(qualifying, key=lambda item: item["score"])
    else:
        # Report the side that came closest, so a rejection is explainable.
        chosen = max(side_results.values(),
                     key=lambda item: (item["gates_passed"], item["score"]))

    direction = chosen["side"]
    score = chosen["score"]
    reasons = buy if direction == "BUY" else sell
    indication = chosen["indication"]
    correction_ok = chosen["correction"]
    continuation_ok = chosen["continuation"]
    higher_tf_agree = chosen["higher_timeframes_agree"]
    mid_tf_not_opposed = chosen["15m_not_opposed"]
    blockers = chosen["blockers"]

    icc_state = (
        "CONTINUATION" if indication and correction_ok and continuation_ok
        else "INDICATION" if indication
        else "CORRECTION" if correction_ok
        else "RANGE / NO ICC"
    )

    side_summary = {
        side: {
            "score": item["score"],
            "qualifies": item["qualifies"],
            "icc_state": (
                "CONTINUATION" if item["indication"] and item["correction"] and item["continuation"]
                else "INDICATION" if item["indication"]
                else "CORRECTION" if item["correction"]
                else "RANGE / NO ICC"
            ),
            "gates_passed": str(item["gates_passed"]) + "/" + str(item["gates_total"]),
            "blockers": item["blockers"],
        }
        for side, item in side_results.items()
    }

    if not chosen["qualifies"]:
        return {
            "symbol":symbol,
            "status":"NO TRADE",
            "direction":direction,
            "direction_evaluated":direction,
            "score":score,
            "minimum_score":MIN_CONFLUENCE,
            "session":sess,
            "market_status":market_status,
            "trend4h":t4,
            "trend1h":t1,
            "trend15m":t15,
            "icc_state":icc_state,
            "indication": indication,
            "correction": correction_ok,
            "continuation": continuation_ok,
            "blockers": blockers,
            "sides": side_summary,
            "latest_close": round(frames["5min"][-1]["close"], 6),
            "confluence_checks": {
                "indication": indication,
                "correction": correction_ok,
                "continuation": continuation_ok,
                "higher_timeframes_agree": higher_tf_agree,
                "15m_not_opposed": mid_tf_not_opposed
            },
            "fundamental":fund,
            "news_source":n.get("source", "GDELT"),
            "news_sentiment":n["sentiment"] if n.get("sentiment_available") else None,
            "data_source":data_source,
            "news_available":n["available"],
            "message":"No signal on " + direction + ": " + "; ".join(blockers) + "."
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
        "icc_state":"CONTINUATION",
        "latest_close": round(price, 6),
        "minimum_score":MIN_CONFLUENCE,
        "sides": side_summary,
        "confluence_checks":{
            "indication":True,
            "correction":True,
            "continuation":True,
            "higher_timeframes_agree":True,
            "15m_not_opposed":True
        },
        "data_source":data_source,
            "market_status":market_status,
        "news_available":n["available"],
        "fundamental":fund,
        "news_source":n.get("source", "GDELT"),
        "news_sentiment":n["sentiment"] if n.get("sentiment_available") else None,
        "articles":n["articles"] if n["available"] else [],
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

        try:
            data=r.json()
        except ValueError:
            data={}

        if not r.ok:
            detail=(data.get("error") or {}).get("message") or r.text[:300] or "The AI provider rejected the request."
            return {
                "available":False,
                "text":f"OpenAI request failed (HTTP {r.status}): {detail}"
            }

        text=data.get("output_text")
        if not text:
            parts=[]
            for item in data.get("output",[]):
                for content in item.get("content",[]):
                    if content.get("type")=="output_text" and content.get("text"):
                        parts.append(content["text"])
            text="\\n".join(parts).strip()

        if text:
            return {"available":True,"text":text}

        return {
            "available":False,
            "text":"OpenAI responded but returned no readable analysis. Check the selected model and API access in Admin."
        }

    except requests.Timeout:
        return {"available":False,"text":"OpenAI timed out. Please try again shortly."}
    except requests.RequestException as e:
        return {"available":False,"text":f"OpenAI connection failed: {type(e).__name__}. Check Render network access and try again."}
    except Exception as e:
        return {"available":False,"text":f"AI analysis failed safely: {type(e).__name__}."}

# ============================================================
# API
# ============================================================

def persist_qualified_signal(signal):
    """Save and notify Discord once for each qualified symbol per day."""
    if signal.get("status") != "QUALIFIED":
        return False

    symbol = signal.get("symbol")
    sess = signal.get("session")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    c = db()
    count = c.execute(
        "SELECT COUNT(*) n FROM signals WHERE created LIKE ?",
        (today + "%",)
    ).fetchone()["n"]

    session_count = c.execute(
        "SELECT COUNT(*) n FROM signals WHERE created LIKE ? AND session=?",
        (today + "%", sess)
    ).fetchone()["n"]

    already_saved = c.execute(
        "SELECT 1 FROM signals WHERE created LIKE ? AND symbol=? LIMIT 1",
        (today + "%", symbol)
    ).fetchone()

    if count >= MAX_DAILY or session_count >= MAX_PER_SESSION or already_saved:
        c.close()
        return False

    reason = "; ".join(signal.get("reasons", [])) or "TW Blueprint ICC qualified"
    c.execute("""
        INSERT INTO signals(
            created,symbol,session,direction,
            entry,stop,tp1,tp2,score,reason
        )
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        symbol,
        sess,
        signal.get("direction"),
        signal.get("entry"),
        signal.get("stop"),
        signal.get("tp1"),
        signal.get("tp2"),
        signal.get("score"),
        reason
    ))
    c.commit()
    c.close()

    send_discord_signal({
        "symbol": symbol,
        "session": sess,
        "direction": signal.get("direction"),
        "entry": signal.get("entry"),
        "stop": signal.get("stop"),
        "tp1": signal.get("tp1"),
        "tp2": signal.get("tp2"),
        "score": signal.get("score"),
        "reason": reason
    })
    return True


@app.route("/api/market-data/status")
def market_data_status():
    """Read-only live-feed diagnostic. Never generates or stores trading signals."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    symbols = {
        "XAU/USD": "XAU/USD",
        "EUR/USD": "EUR/USD",
        "GBP/USD": "GBP/USD",
        "USD/JPY": "USD/JPY",
        "BTC/USD": "BTC/USD",
        "Volatility 75 Index": "R_75",
        "Boom 500 Index": "BOOM500",
    }

    def check_one(label, provider_symbol):
        candles, error, provider = td(provider_symbol, "5min", 50)
        if error or not candles:
            return {
                "symbol": label,
                "status": "ERROR",
                "source": provider or market_source_label(group_for_provider_symbol(provider_symbol)),
                "message": error or "No completed candles returned."
            }
        latest = candles[-1]
        raw_time = latest.get("time")
        try:
            stamp = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            return {
                "symbol": label,
                "status": "ERROR",
                "source": provider or market_source_label(group_for_provider_symbol(provider_symbol)),
                "message": "Latest candle has no valid UTC timestamp."
            }

        return {
            "symbol": label,
            "status": "OK" if age_seconds <= 1200 else "STALE",
            "source": provider or market_source_label(group_for_provider_symbol(provider_symbol)),
            "timeframe": "5min",
            "completed_candles": len(candles),
            "latest_candle_utc": stamp.astimezone(timezone.utc).isoformat(),
            "candle_age_minutes": round(age_seconds / 60, 1),
            "latest_close": latest["close"],
            "message": "Recent completed candles received." if age_seconds <= 1200 else "Latest completed candle is older than 20 minutes."
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            label: pool.submit(check_one, label, provider_symbol)
            for label, provider_symbol in symbols.items()
        }
        results = {label: future.result() for label, future in futures.items()}

    checked_at = datetime.now(timezone.utc)
    market_closed = fx_market_closed(checked_at)
    fx_metal_symbols = {"XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"}
    if market_closed:
        for label, result in results.items():
            # Only apply the weekly FX/gold closure to those markets.
            # Crypto and Deriv synthetic indices must still be checked 24/7.
            if label in fx_metal_symbols and result.get("status") in ("OK", "STALE"):
                result["status"] = "MARKET_CLOSED"
                result["message"] = (
                    "Weekly FX/gold market closure: last Friday candle may be expected. "
                    "Recheck during the next open market session."
                )
    ok_count = sum(1 for result in results.values() if result["status"] == "OK")
    feed_errors = sum(1 for result in results.values() if result["status"] == "ERROR")
    closed_count = sum(1 for result in results.values() if result["status"] == "MARKET_CLOSED")
    overall = (
        "ERROR" if feed_errors == len(results)
        else "PARTIAL" if feed_errors or closed_count
        else "OK" if ok_count == len(results)
        else "PARTIAL" if ok_count
        else "ERROR"
    )
    return jsonify({
        "overall_status": overall,
        "market_closed": market_closed,
        "source": "Mixed feeds: BiQuote and Deriv public WebSocket",
        "checked_at_utc": checked_at.isoformat(),
        "checks": results,
        "note": "Read-only diagnostics; FX/gold candles may be old during the weekly closure, but crypto and Deriv synthetic markets are checked independently."
    })


@app.route("/api/market-data/universe-status")
def market_data_universe_status():
    """Read-only feed check across representative forex, crypto, index and Deriv synthetic markets."""
    from concurrent.futures import ThreadPoolExecutor

    symbols = {
        "XAU/USD": {"provider": "XAU/USD", "group": "METALS"},
        "EUR/USD": {"provider": "EUR/USD", "group": "FOREX"},
        "BTC/USD": {"provider": "BTC/USD", "group": "CRYPTO"},
        "ETH/USD": {"provider": "ETH/USD", "group": "CRYPTO"},
        "NASDAQ": {"provider": "IXIC", "group": "INDICES"},
        "US30": {"provider": "DJI", "group": "INDICES"},
        "Volatility 10 Index": {"provider": "R_10", "group": "SYNTHETICS"},
        "Volatility 50 Index": {"provider": "R_50", "group": "SYNTHETICS"},
        "Volatility 75 Index": {"provider": "R_75", "group": "SYNTHETICS"},
        "Volatility 100 Index": {"provider": "R_100", "group": "SYNTHETICS"},
        "Boom 500 Index": {"provider": "BOOM500", "group": "SYNTHETICS"},
        "Crash 500 Index": {"provider": "CRASH500", "group": "SYNTHETICS"},
        "Step Index": {"provider": "stpRNG", "group": "SYNTHETICS"}
    }

    def check_one(label, item):
        candles, error, provider = td(item["provider"], "5min", 50)
        source = "Deriv public WebSocket" if item["group"] == "SYNTHETICS" else "BiQuote public OHLC"
        result = {
            "symbol": label,
            "group": item["group"],
            "source": source,
            "timeframe": "5min"
        }
        if error or not candles:
            result.update({
                "status": "ERROR",
                "message": error or "No completed candles returned."
            })
            return result

        latest = candles[-1]
        try:
            stamp = datetime.fromisoformat(str(latest["time"]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamp = stamp.astimezone(timezone.utc)
            age_seconds = max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
        except (KeyError, TypeError, ValueError):
            result.update({"status": "ERROR", "message": "Latest candle has an invalid timestamp."})
            return result

        market_expected_open = item["group"] in ("CRYPTO", "SYNTHETICS") or not fx_market_closed()
        if not market_expected_open:
            status = "MARKET_CLOSED"
            message = "Weekly closure expected for this market group; recheck during its next open session."
        elif age_seconds > 1200:
            status = "STALE"
            message = "Latest completed candle is older than 20 minutes."
        else:
            status = "OK"
            message = "Recent completed candles received."

        result.update({
            "status": status,
            "completed_candles": len(candles),
            "latest_candle_utc": stamp.isoformat(),
            "candle_age_minutes": round(age_seconds / 60, 1),
            "latest_close": latest["close"],
            "message": message
        })
        return result

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {label: pool.submit(check_one, label, item) for label, item in symbols.items()}
        checks = {label: future.result() for label, future in futures.items()}

    statuses = [item["status"] for item in checks.values()]
    if all(status == "OK" for status in statuses):
        overall = "OK"
    elif any(status == "ERROR" for status in statuses):
        overall = "ERROR" if all(status == "ERROR" for status in statuses) else "PARTIAL"
    elif any(status == "STALE" for status in statuses):
        overall = "STALE"
    elif all(status == "MARKET_CLOSED" for status in statuses):
        overall = "MARKET_CLOSED"
    else:
        overall = "PARTIAL"

    return jsonify({
        "overall_status": overall,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "note": "Read-only diagnostics. OK means recent candles were returned by the named provider; it does not guarantee execution prices match another broker."
    })


@app.route("/api/blueprint")
def api_blueprint():
    """Read-only TW Blueprint ICC analysis for one supported instrument; never persists a signal."""
    symbol = request.args.get("symbol", "XAU/USD").strip()
    if symbol not in ASSETS:
        return jsonify({
            "symbol": symbol,
            "status": "ERROR",
            "message": "Unsupported symbol. Choose a symbol listed by TW Trades."
        }), 400
    result = analyze(symbol)
    checks = result.get("confluence_checks", {})
    return jsonify({
        "engine": "TW Blueprint ICC",
        "symbol": symbol,
        "read_only": True,
        "status": result.get("status", "UNKNOWN"),
        "direction": result.get("direction"),
        "score": result.get("score"),
        "session": result.get("session"),
        "icc_state": result.get("icc_state", "UNAVAILABLE"),
        "indication": result.get("indication", checks.get("indication", False)),
        "correction": result.get("correction", checks.get("correction", False)),
        "continuation": result.get("continuation", checks.get("continuation", False)),
        "confluence_checks": checks,
        "trend4h": result.get("trend4h"),
        "trend1h": result.get("trend1h"),
        "trend15m": result.get("trend15m"),
        "entry": result.get("entry"),
        "stop": result.get("stop"),
        "tp1": result.get("tp1"),
        "tp2": result.get("tp2"),
        "latest_close": result.get("latest_close"),
        "atr": result.get("atr"),
        "data_source": result.get("data_source"),
        "market_status": result.get("market_status"),
        "blockers": result.get("blockers", []),
        "minimum_score": result.get("minimum_score"),
        "sides": result.get("sides"),
        "news_source": result.get("news_source", "GDELT"),
        "news_available": result.get("news_available", False),
        "fundamental": result.get("fundamental", {"bias":"UNAVAILABLE","impact":"UNKNOWN"}),
        "message": result.get("message", "Analysis completed.")
    })


_SCAN_CACHE = {"started": 0.0, "payload": None}
_SCAN_CACHE_LOCK = threading.Lock()
SCAN_CACHE_TTL = 90        # seconds a completed scan is reused
SCAN_BUDGET = 75           # hard wall-clock budget for one scan, in seconds
SCAN_WORKERS = 5           # concurrent instruments; each also fetches 4 timeframes


def _scan_payload(results_by_symbol, timed_out):
    scan_details = [results_by_symbol[name] for name in ASSETS if name in results_by_symbol]
    qualified = [item for item in scan_details if item.get("status") == "QUALIFIED"]
    qualified.sort(key=lambda item: item.get("score", 0), reverse=True)

    counts = {}
    for item in scan_details:
        state = item.get("status", "UNKNOWN")
        counts[state] = counts.get(state, 0) + 1
    if timed_out:
        counts["SCAN TIMEOUT"] = counts.get("SCAN TIMEOUT", 0) + timed_out

    return {
        "session": current_session(),
        "daily_maximum": MAX_DAILY,
        "qualified_count": len(qualified),
        "scanned_count": len(scan_details),
        "unfinished_count": timed_out,
        "status_counts": counts,
        "results": qualified[:MAX_DAILY],
        "scan_details": scan_details,
        "data_sources": {
            "forex_metals_indices_crypto": "BiQuote public OHLC feed",
            "synthetics": "Deriv public WebSocket",
            "news": "GDELT primary, verified publisher RSS fallback",
        },
        "cached": False,
    }


@app.route("/api/scan")
def api_scan():
    """Scan the universe. Parallel, deadline-bounded and cached.

    The previous sequential loop needed minutes for 31 instruments and always
    exceeded the worker timeout, so the endpoint returned nothing at all.
    """
    symbol = (request.args.get("symbol") or "").strip()

    if symbol:
        if symbol not in ASSETS:
            return jsonify({
                "symbol": symbol,
                "status": "ERROR",
                "message": "Unsupported symbol. Choose a symbol listed by TW Trades."
            }), 400
        result = analyze(symbol)
        try:
            persist_qualified_signal(result)
        except Exception:
            app.logger.exception("Signal persistence failed for %s", symbol)
        return jsonify(result)

    refresh = (request.args.get("refresh") or "").lower() in ("1", "true", "yes")
    now = time.monotonic()
    with _SCAN_CACHE_LOCK:
        if not refresh and _SCAN_CACHE["payload"] is not None:
            if now - _SCAN_CACHE["started"] < SCAN_CACHE_TTL:
                cached = dict(_SCAN_CACHE["payload"])
                cached["cached"] = True
                cached["cache_age_seconds"] = round(now - _SCAN_CACHE["started"], 1)
                return jsonify(cached)

    from concurrent.futures import ThreadPoolExecutor, wait

    results_by_symbol = {}
    deadline = time.monotonic() + SCAN_BUDGET
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        futures = {pool.submit(analyze, name): name for name in ASSETS}
        done, pending = wait(futures, timeout=SCAN_BUDGET)
        for future in done:
            name = futures[future]
            try:
                results_by_symbol[name] = future.result()
            except Exception as exc:
                app.logger.exception("Scan failed for %s", name)
                results_by_symbol[name] = {
                    "symbol": name,
                    "status": "DATA ERROR",
                    "message": "Analysis failed: " + str(exc),
                }
        for future in pending:
            name = futures[future]
            results_by_symbol[name] = {
                "symbol": name,
                "status": "SCAN TIMEOUT",
                "message": "Not completed within the " + str(SCAN_BUDGET) + "s scan budget. Retry shortly.",
            }
            future.cancel()

    payload = _scan_payload(results_by_symbol, len(pending))

    # Persist sequentially: sqlite connections are per-call and concurrent
    # writes from worker threads would contend for the write lock.
    for item in payload["results"]:
        try:
            persist_qualified_signal(item)
        except Exception:
            app.logger.exception("Signal persistence failed for %s", item.get("symbol"))

    with _SCAN_CACHE_LOCK:
        _SCAN_CACHE["payload"] = dict(payload)
        _SCAN_CACHE["started"] = time.monotonic()

    return jsonify(payload)


@app.route("/api/news/status")
def api_news_status():
    """Read-only health of the headline layer. Never returns invented content."""
    return jsonify(news_diagnostics())


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

def _commit_authorised():
    """Committing a signal must be authenticated.

    Either an admin session, or a shared token from COMMIT_API_TOKEN supplied as
    X-API-Token (or a Bearer token) for an external poster.
    """
    token = os.environ.get("COMMIT_API_TOKEN", "").strip()
    if token:
        supplied = (request.headers.get("X-API-Token", "").strip()
                    or request.headers.get("Authorization", "").replace("Bearer ", "").strip())
        return bool(supplied) and secrets.compare_digest(supplied, token)
    return bool(session.get("admin"))


@app.route("/api/commit",methods=["POST"])
def commit():

    if not _commit_authorised():
        return jsonify({
            "error": "Unauthorised. Sign in as admin, or configure COMMIT_API_TOKEN and send it as X-API-Token."
        }), 401

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

    signal = {
        "symbol": symbol,
        "session": sess,
        "direction": data.get("direction"),
        "entry": data.get("entry"),
        "stop": data.get("stop"),
        "tp1": data.get("tp1"),
        "tp2": data.get("tp2"),
        "score": data.get("score"),
        "reason": "TW Blueprint ICC qualified"
    }

    send_discord_signal(signal)

    return jsonify({"ok": True})


# ============================================================
# ADMIN
# ============================================================

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        client = _client_ip()

        if _login_blocked("admin", client):
            return _too_many_attempts_page(), 429

        stored = get_setting("admin_password_hash")

        # Allow the owner to recover admin access using a private Render
        # environment variable. On successful recovery, sync the database hash.
        recovery_password = os.environ.get("ADMIN_PASSWORD", "")
        ok_stored = _verify_password(password, stored)
        ok_recovery = bool(recovery_password) and secrets.compare_digest(password, recovery_password)

        if ok_stored or ok_recovery:
            _login_succeeded("admin", client)
            # Migrate a legacy SHA-256 hash, or the recovery password, to PBKDF2.
            if ok_recovery or _needs_rehash(stored):
                set_setting("admin_password_hash", _hash_password(password))
            session.clear()
            session["admin"] = True
            return redirect("/admin")

        _login_failed("admin", client)

        return """
        <!doctype html>
        <html>
        <meta name="viewport" content="width=device-width">
        <body style="
            margin:0;
            background:#05070b;
            color:white;
            font-family:Arial,sans-serif;
            min-height:100vh;
            display:flex;
            align-items:center;
            justify-content:center;
        ">
        <div style="
            width:90%;
            max-width:400px;
            padding:30px;
            background:#0b1119;
            border:1px solid rgba(0,255,208,.18);
            border-radius:20px;
            box-shadow:0 20px 60px rgba(0,0,0,.45);
            text-align:center;
        ">
            <div style="
                color:#00ffd0;
                font-size:12px;
                font-weight:900;
                letter-spacing:3px;
                margin-bottom:10px;
            ">TW TRADES</div>

            <h1 style="margin:0 0 8px;">ADMIN LOGIN</h1>

            <p style="color:#8b95a7;">
                Incorrect password. Please try again.
            </p>

            <form method="post">
                <input
                    name="password"
                    type="password"
                    placeholder="Admin password"
                    autocomplete="current-password"
                    style="
                        box-sizing:border-box;
                        padding:15px;
                        width:100%;
                        border-radius:12px;
                        border:1px solid #29384b;
                        background:#05070b;
                        color:white;
                        outline:none;
                    "
                >
                <br><br>
                <button
                    type="submit"
                    style="
                        padding:14px 25px;
                        width:100%;
                        border:0;
                        border-radius:12px;
                        background:#00ffd0;
                        color:#03100e;
                        font-weight:900;
                        cursor:pointer;
                    "
                >LOGIN</button>
            </form>
        </div>
        </body>
        </html>
        """

    return """
    <!doctype html>
    <html>
    <meta name="viewport" content="width=device-width">
    <body style="
        margin:0;
        background:#05070b;
        color:white;
        font-family:Arial,sans-serif;
        min-height:100vh;
        display:flex;
        align-items:center;
        justify-content:center;
    ">
    <div style="
        width:90%;
        max-width:400px;
        padding:30px;
        background:#0b1119;
        border:1px solid rgba(0,255,208,.18);
        border-radius:20px;
        box-shadow:0 20px 60px rgba(0,0,0,.45);
        text-align:center;
    ">
        <div style="
            color:#00ffd0;
            font-size:12px;
            font-weight:900;
            letter-spacing:3px;
            margin-bottom:10px;
        ">TW TRADES</div>

        <h1 style="margin:0 0 8px;">ADMIN LOGIN</h1>

        <p style="color:#8b95a7;">
            Secure administrator access
        </p>

        <form method="post">
            <input
                name="password"
                type="password"
                placeholder="Admin password"
                autocomplete="current-password"
                required
                style="
                    box-sizing:border-box;
                    padding:15px;
                    width:100%;
                    border-radius:12px;
                    border:1px solid #29384b;
                    background:#05070b;
                    color:white;
                    outline:none;
                "
            >
            <br><br>
            <button
                type="submit"
                style="
                    padding:14px 25px;
                    width:100%;
                    border:0;
                    border-radius:12px;
                    background:#00ffd0;
                    color:#03100e;
                    font-weight:900;
                    cursor:pointer;
                "
            >LOGIN</button>
        </form>
    </div>
    </body>
    </html>
    """

@app.route("/admin",methods=["GET","POST"])
def admin():

    if not session.get("admin"):
        return redirect("/admin/login")

    if request.method=="POST":

        for key in [
            "openai_key",
            "openai_model",
            "deriv_app_id"
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
                _hash_password(password)
            )

    return render_template_string(
    ADMIN_HTML,
    ai="********" if get_setting("openai_key") else "",
    model=get_setting("openai_model"),
    deriv_app_id=get_setting("deriv_app_id")
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

<p style="color:#9eacbd;font-size:13px">News source: GDELT public news search. No API key is required. Headlines are shown without fabricated sentiment scores.</p>

<label>OpenAI API Key</label>
<input name="openai_key"
value="{{ai}}"
type="password">

<label>AI Model</label>
<input name="openai_model"
value="{{model}}">

<label>Deriv API App ID (public market data)</label>
<input name="deriv_app_id"
value="{{deriv_app_id}}"
inputmode="numeric"
placeholder="Enter your own Deriv App ID">
<p style="color:#9eacbd;font-size:13px">Use your own application ID from Deriv API settings. No trading token is needed for public market candles.</p>

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
<p>✓ GDELT financial/news headlines (no API key required; sentiment not fabricated)</p>
<p>✓ Public BiQuote candles for supported FX, metals and indices</p>
<p>✓ Deriv public WebSocket candles for crypto and synthetic indices</p>
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


/* LANDING PAGE MODE: keep only the hero and access/contact request section on Home */
body:not(.tw-nav-view) section:not(#top):not(#request){display:none!important;}
body.tw-nav-view section{display:none!important;}
body.tw-nav-view section.tw-nav-active{display:block!important;}
</style>

<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#00ffd0">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="TW Trades">


<style>

.tw-chart-time{
    border:1px solid rgba(255,255,255,.08);
    background:rgba(255,255,255,.025);
    color:#aab7c8;
    padding:9px 13px;
    border-radius:10px;
    font-weight:800;
    cursor:pointer;
}

.tw-chart-time:hover{
    border-color:rgba(0,255,208,.35);
    color:#00ffd0;
}

@media(max-width:700px){

    #twTradingViewChart{
        height:470px !important;
        min-height:470px !important;
    }

}

</style>


<style id="tw-pro-workspace-upgrade">
/* TW TRADES PRO WORKSPACE UI — additive presentation layer; existing app logic preserved */
:root{
  --tw-accent:#00ffd0;
  --tw-accent-soft:rgba(0,255,208,.12);
  --tw-surface:rgba(12,19,30,.92);
  --tw-border:rgba(148,169,196,.17);
  --tw-muted:#9aa9bd;
}
html{scroll-padding-top:94px;scroll-behavior:smooth}
body{
  background:
    radial-gradient(ellipse at 15% 0%,rgba(42,65,113,.14),transparent 42%),
    radial-gradient(ellipse at 92% 12%,rgba(0,255,208,.055),transparent 30%),
    #05070b;
  color:#edf3fb;
  -webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
}
body:before{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;opacity:.15;
  background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);
  background-size:42px 42px;
}
nav{
  min-height:76px;
  padding:13px clamp(16px,4vw,54px);
  gap:20px;
  background:rgba(5,9,16,.9);
  border-bottom:1px solid rgba(148,169,196,.15);
  box-shadow:0 10px 35px rgba(0,0,0,.16);
  backdrop-filter:blur(22px);
  -webkit-backdrop-filter:blur(22px);
}
.logo{
  flex-shrink:0;
  font-size:19px;
  letter-spacing:2.5px;
  line-height:1.1;
}
.logo span{color:var(--tw-accent);margin-left:5px}
.navlinks{
  display:flex;
  align-items:center;
  justify-content:flex-end;
  flex-wrap:wrap;
  gap:4px;
}
.navlinks a{
  display:inline-flex;
  align-items:center;
  min-height:35px;
  margin:0;
  padding:8px 10px;
  border:1px solid transparent;
  border-radius:9px;
  color:#a9b7ca;
  font-size:11px;
  font-weight:700;
  letter-spacing:.015em;
  white-space:nowrap;
  transition:background .18s ease,border-color .18s ease,color .18s ease,transform .18s ease;
}
.navlinks a:hover,.navlinks a:focus-visible{
  background:rgba(255,255,255,.055);
  border-color:var(--tw-border);
  color:#fff;
  transform:translateY(-1px);
}
.navlinks a[href="/access"]{
  color:#04100e;
  background:var(--tw-accent);
  border-color:var(--tw-accent);
  padding-left:13px;padding-right:13px;
}
.navlinks a[href="/access"]:hover{background:#9dffe9;border-color:#9dffe9;color:#04100e}
.navlinks a[href="/admin"]{color:#c1cde0}
.menu{
  border:1px solid var(--tw-border);
  border-radius:10px;
  background:#101927;
  color:#eaf3ff;
  min-width:42px;
  min-height:40px;
}
.hero{
  min-height:min(86vh,850px);
  padding:clamp(64px,10vh,112px) clamp(22px,8vw,110px);
  overflow:hidden;
}
.hero:before{
  content:"";position:absolute;left:7%;top:18%;width:1px;height:65%;
  background:linear-gradient(transparent,rgba(0,255,208,.18),transparent);
}
.hero-content{position:relative;z-index:1;max-width:920px}
.eyebrow{
  display:inline-flex;align-items:center;gap:10px;
  border:1px solid rgba(0,255,208,.22);
  background:rgba(0,255,208,.045);
  border-radius:99px;
  padding:9px 13px;
  font-size:10px;letter-spacing:2.3px;color:#9df8e3;
}
.eyebrow:before{content:"";width:6px;height:6px;flex:0 0 6px;border-radius:50%;background:var(--tw-accent);box-shadow:0 0 13px rgba(0,255,208,.65)}
h1{
  font-size:clamp(48px,8vw,100px);
  line-height:.99;
  letter-spacing:-.065em;
  max-width:850px;
  margin:25px 0 23px;
}
.gradient{
  background:linear-gradient(100deg,#fff 0%,#9ef9e5 45%,#7b9dff 100%);
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.hero p{font-size:clamp(15px,1.7vw,18px);max-width:680px;color:#a8b6c9;line-height:1.85}
.buttons{gap:10px;margin-top:32px}
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:9px;
  min-height:48px;padding:13px 19px;border-radius:11px;
  border:1px solid rgba(148,169,196,.23);
  background:rgba(17,26,40,.78);color:#e8f1ff;
  font-size:11px;letter-spacing:.055em;
  transition:transform .18s ease,border-color .18s ease,background .18s ease;
}
.btn:hover{transform:translateY(-2px);border-color:rgba(0,255,208,.42);background:#142233}
.btn.primary{
  background:var(--tw-accent);color:#03100e;border-color:var(--tw-accent);
  box-shadow:0 8px 26px rgba(0,255,208,.12);
}
.btn.primary:hover{background:#9dffe9;border-color:#9dffe9}
.ticker{
  border-top:1px solid rgba(148,169,196,.1);
  border-bottom:1px solid rgba(148,169,196,.1);
  background:rgba(10,16,26,.72);
  padding:13px 10px;
  color:#a8b8ca;
  font-size:10px;letter-spacing:.12em;
}
section{padding:clamp(62px,8vw,100px) clamp(18px,6vw,78px)}
.section-head{margin-bottom:32px}
.kicker{color:var(--tw-accent);font-size:10px;letter-spacing:2.6px}
h2{font-size:clamp(29px,4.2vw,49px);line-height:1.1;letter-spacing:-.045em}
.muted{color:#9aa9bd}
.cards,.news,.signal-grid{gap:14px}
.card{
  border:1px solid var(--tw-border);
  border-radius:18px;
  background:linear-gradient(145deg,rgba(17,27,42,.94),rgba(7,12,20,.94));
  padding:clamp(20px,2.4vw,28px);
  box-shadow:0 12px 38px rgba(0,0,0,.12);
  transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease;
}
.card:hover{transform:translateY(-3px);border-color:rgba(0,255,208,.25);box-shadow:0 18px 48px rgba(0,0,0,.22)}
.tag{background:rgba(0,255,208,.075);border:1px solid rgba(0,255,208,.13);color:#9ef9e5}
.terminal{border-color:rgba(0,255,208,.19);border-radius:20px;box-shadow:0 24px 70px rgba(0,0,0,.28)}
.term-top{background:rgba(255,255,255,.018)}
.signal,.news-item{border-color:var(--tw-border);background:rgba(12,19,30,.9)}
button,input,select,textarea{font:inherit}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--tw-accent);outline-offset:3px}
button:disabled{opacity:.55;cursor:not-allowed}
footer{border-top:1px solid rgba(148,169,196,.14)}
@media(min-width:1200px){
  nav{padding-left:clamp(28px,4vw,64px);padding-right:clamp(28px,4vw,64px)}
  .hero{padding-left:clamp(70px,10vw,150px)}
}
@media(max-width:1000px) and (min-width:761px){
  nav{align-items:flex-start;flex-wrap:wrap}
  .navlinks{justify-content:flex-start;max-width:100%;gap:3px}
  .navlinks a{font-size:10px;padding:7px 8px}
}
@media(max-width:760px){
  nav{min-height:66px;padding:12px 16px;align-items:center}
  .logo{font-size:18px}
  .hero{min-height:76vh;padding:70px 24px 78px}
  .hero:before{left:12px;top:15%;height:68%}
  h1{letter-spacing:-.055em}
  .hero p{font-size:15px}
  .buttons{align-items:stretch}
  .buttons .btn{flex:1 1 190px;text-align:center}
  section{padding:62px 18px}
  .card:hover{transform:none}
}
@media(prefers-reduced-motion:reduce){
  *,*:before,*:after{scroll-behavior:auto!important;animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
}
</style>
</head>

<body>

<nav>

<div class="logo">
TW<span>TRADES</span>
</div>

<div class="navlinks">
<a href="#top">Home</a>
<a href="#terminal">Terminal</a>
<a href="#intelligence">Intelligence</a><a href="#scanner">Scanner</a><a href="#apex-dashboard">Apex Flow</a>
<a href="#titan">Titan X</a>
<a href="#yuki">Yuki</a>
<a href="#academy">Academy</a><a href="#library">Library</a>
<a href="#request">Access</a>
<a href="/admin">Admin</a>
</div>

<button class="menu" id="twMenuButton" type="button" aria-label="Open TW Trades command menu" aria-expanded="false">☰</button>

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

<a class="btn primary" href="/access">
LAUNCH · LOGIN / REGISTER
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
<h3>GDELT Market News</h3>
<p class="muted">
Select an instrument to load current financial
news and sentiment.
</p>
</div>

</div>

</section>

<!-- AI -->

<section id="ai-intelligence">

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

const r=await fetch("/api/scan",{cache:"no-store"});
if(!r.ok) throw new Error("Scanner HTTP "+r.status);
const data=await r.json();

lastScan=data;

const qualified=data.results||[];
renderSignals(qualified);

if(!qualified.length && Array.isArray(data.scan_details)){
  const counts=data.status_counts||{};
  const summary=Object.keys(counts).map(function(k){
    return k+": "+counts[k];
  }).join(" · ");
  const issues=data.scan_details.filter(function(item){
    return item.status==="DATA ERROR" || item.status==="ERROR";
  }).slice(0,4);
  const issueHtml=issues.map(function(item){
    return "<p class=\"muted\"><strong>"+String(item.symbol||"Market")+" — "+String(item.status)+":</strong> "+String(item.message||"Check market data configuration.")+"</p>";
  }).join("");
  const panel=document.getElementById("terminalResults");
  panel.innerHTML=
    '<div class="signal"><h3>SCANNER DIAGNOSTICS</h3>'+
    '<p class="muted">Scanned '+String(data.scanned_count||0)+' markets. Qualified setups: 0. No signals were invented.</p>'+
    '<p class="muted">'+String(summary||"No status summary returned.")+'</p>'+
    issueHtml+
    '<p class="muted">Market candles use the public BiQuote feed and require no Twelve Data key. If DATA ERROR appears, the feed may be unavailable or may not support that symbol. NO TRADE means the setup did not meet the rules.</p></div>';
}

}catch(e){

box.innerHTML=
'<div class="signal"><h3>DATA CONNECTION ERROR</h3><p class="muted">'+String(e.message||e)+'</p></div>';

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
?[data]:[],
diagnostic:data
};

if(data.status==="QUALIFIED"){
  renderSignals(lastScan.results);
}else{
  const detail=data.message||"The scanner did not qualify this setup.";
  const score=(data.score!==undefined)?("<p class=\"muted\">Score: "+data.score+"/100</p>"):"";
  const trends=[
    data.trend4h?("4H: "+data.trend4h):"",
    data.trend1h?("1H: "+data.trend1h):"",
    data.trend15m?("15M: "+data.trend15m):""
  ].filter(Boolean).join(" · ");
  const checks=data.confluence_checks||{};
  const icc='<p class="muted"><strong>TW Blueprint ICC:</strong> '+String(data.icc_state||"NOT CONFIRMED")+
    ' · Indication '+(checks.indication?"✓":"—")+
    ' · Correction '+(checks.correction?"✓":"—")+
    ' · Continuation '+(checks.continuation?"✓":"—")+'</p>';
  box.innerHTML='<div class="signal"><h3>'+String(data.status||"NO TRADE")+'</h3><p class="muted">'+String(detail)+'</p>'+score+(trends?'<p class="muted">'+trends+'</p>':"")+icc+
    '<p class="muted">Source: '+String(data.data_source||"Not confirmed")+'</p></div>';
}

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

if(!data.available || !data.articles?.length){

const message=data.message || (!data.available
  ? "Live news is temporarily unavailable from GDELT. Retry shortly; no sentiment is inferred from headlines."
  : "GDELT returned no matching current headlines for this instrument.");

box.innerHTML=`
<div class="news-item">
<h3>${data.available ? "No current articles" : "Market intelligence unavailable"}</h3>
<p class="muted">${message}</p>
</div>`;

return;

}

box.innerHTML=data.articles.map(a=>`

<div class="news-item">

<span class="tag">
${(a.source||data.source||"GDELT").replace(/[<>]/g,"")}
</span>

<h3>
<a href="${a.url||"#"}"
target="_blank" rel="noopener noreferrer">
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
if(!r.ok){
  output.innerText=data.text||data.message||("AI request failed (HTTP "+r.status+").");
  return;
}
output.innerText=data.text||(data.available===false?"AI is unavailable. Check the OpenAI API key and model in Admin.":"No analysis text was returned.");

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
Financial-news headlines powered by GDELT. Headlines are not sentiment scores.
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





<!-- TW TRADES LIBRARY -->
<section id="library" style="margin:70px auto;max-width:1180px;padding:clamp(22px,4vw,48px);border:1px solid rgba(0,255,208,.18);border-radius:28px;background:linear-gradient(135deg,rgba(7,16,27,.98),rgba(3,8,15,.98));box-shadow:0 0 45px rgba(0,255,208,.06);">
<div style="text-align:center;margin-bottom:30px;"><div style="font-size:12px;letter-spacing:3px;color:#00ffd0;font-weight:800;">TW TRADES • THE AUTONOMY OF SUCCESS</div><h2 style="font-size:clamp(30px,5vw,44px);margin:12px 0 8px;">Trading Education <span style="color:#00ffd0;">Library</span></h2><p style="max-width:780px;margin:auto;color:#aab7c8;line-height:1.7;">A structured learning path from forex foundations to price action, TW Blueprint ICC, macro fundamentals, gold, risk management and trading psychology. Lessons below are original educational summaries; BabyPips is linked as an independent external course.</p></div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin-bottom:28px;">
<a href="https://www.babypips.com/learn/forex" target="_blank" rel="noopener noreferrer" style="text-decoration:none;color:inherit;"><div style="height:100%;padding:22px;border:1px solid rgba(0,255,208,.3);border-radius:18px;background:rgba(0,255,208,.055);"><div style="font-size:28px;">🎓</div><h3 style="margin:12px 0 8px;">BabyPips · School of Pipsology</h3><p style="color:#aab7c8;line-height:1.65;font-size:14px;">Start with currency pairs, brokers, charts, support and resistance, indicators, fundamentals, sentiment and risk management. Opens the official BabyPips course.</p><span style="color:#00ffd0;font-weight:800;">OPEN OFFICIAL COURSE ↗</span></div></a>
<div style="padding:22px;border:1px solid rgba(255,255,255,.1);border-radius:18px;background:rgba(255,255,255,.025);"><div style="font-size:28px;">🌊</div><h3 style="margin:12px 0 8px;">TW Blueprint · ICC Method</h3><p style="color:#aab7c8;line-height:1.65;font-size:14px;">Learn range identification, body-based breaks, indication, correction, continuation, 4H markup and lower-timeframe execution.</p><span style="color:#00ffd0;font-weight:800;">LESSONS BELOW ↓</span></div>
<div style="padding:22px;border:1px solid rgba(255,255,255,.1);border-radius:18px;background:rgba(255,255,255,.025);"><div style="font-size:28px;">🧠</div><h3 style="margin:12px 0 8px;">The Autonomy of Success</h3><p style="color:#aab7c8;line-height:1.65;font-size:14px;">Build independent decision-making through journaling, probability, patience, risk discipline and repeatable trading processes.</p><span style="color:#00ffd0;font-weight:800;">LESSONS BELOW ↓</span></div></div>
<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin:24px 0 16px;"><h3 style="margin:0;font-size:23px;">Learning Path · 8 Modules</h3><span style="font-size:12px;color:#93a4b8;">Read each lesson, then practise on a demo chart</span></div>
<div style="display:grid;gap:12px;">
<details open style="padding:18px 20px;border:1px solid rgba(0,255,208,.22);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">01 · Forex Foundations</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Currency pairs:</b> a pair compares a base currency with a quote currency. EUR/USD at 1.0800 means one euro is priced at 1.0800 US dollars. Buying the pair expresses a view that the base currency will strengthen relative to the quote currency.</p><p><b>Pips, spread and lot size:</b> a pip is a standard price increment (usually 0.0001 for most non-JPY pairs; commonly 0.01 for JPY pairs). The spread is the gap between bid and ask. Lot size controls exposure, so the same stop distance can produce very different cash losses.</p><p><b>Leverage and margin:</b> leverage reduces the margin needed to open a position; it does not reduce the market risk of that position. A small adverse move can cause a large percentage loss when position size is too high.</p><p><b>Practice:</b> identify the base/quote currency, current spread, pip size and estimated loss at your planned stop before placing any demo order.</p></div></details>
<details style="padding:18px 20px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">02 · Candlesticks, Structure & Support/Resistance</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Candlestick anatomy:</b> the body shows open-to-close movement; the wick shows the full high-to-low range. A candle alone is not a trade signal—read it in context of structure, location and volatility.</p><p><b>Structure:</b> an uptrend generally forms higher highs and higher lows; a downtrend forms lower highs and lower lows. A break is more meaningful when the candle closes beyond a clearly marked structure level rather than briefly wicking through it.</p><p><b>Support and resistance:</b> mark zones where price previously reacted, not magical exact lines. More touches do not guarantee a future reaction. If a level breaks, wait to see whether price accepts beyond it or returns into the prior range.</p><p><b>Practice:</b> mark the prior day high/low and the 4H swing points. Write down what would confirm a break and what would invalidate it before looking for an entry.</p></div></details>
<details style="padding:18px 20px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">03 · TW Blueprint: Indication → Correction → Continuation</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Before ICC — range/no-trade state:</b> define the range boundaries and avoid forcing a direction while price remains trapped inside. Mark levels using candle bodies as specified by the TW Blueprint rules, while still noting wick extremes as liquidity references.</p><p><b>Indication:</b> wait for a decisive candle-body break of the marked range or structure. A wick alone is not sufficient confirmation in this method. Check whether the break agrees with the higher-timeframe context.</p><p><b>Correction:</b> after the break, let price retrace toward the broken level or another planned area. A correction is not guaranteed; do not chase price if the planned entry has already passed.</p><p><b>Continuation:</b> look for evidence that price is resuming in the direction of the indication. Define invalidation first, then calculate position size. If indication, correction or continuation is missing, label the setup incomplete rather than inventing a signal.</p><p><b>Top-down workflow:</b> 4H markup and range → 1H directional context → 15M setup → 5M execution trigger. These timeframes are a framework, not a promise of accuracy.</p></div></details>
<details style="padding:18px 20px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">04 · Multi-Timeframe Confluence & Market Context</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Confluence:</b> independent evidence that points toward the same scenario can strengthen a setup—for example, 4H structure, 1H alignment, a 15M level and a 5M trigger. Repeating the same indicator in several forms is not independent evidence.</p><p><b>Conflicts:</b> if the 4H is bearish while the 5M gives a bullish trigger, record the conflict. Reduce confidence or wait; do not hide the disagreement behind a single score.</p><p><b>Session and volatility:</b> liquidity and spreads vary across Asian, London and New York hours. Confirm the broker's server time, scheduled releases and current conditions; session labels alone do not guarantee a move.</p><p><b>Practice:</b> make a confluence checklist with timeframe, direction, evidence, data source and timestamp. If any source is unavailable, mark it unavailable—not bullish, bearish or confirmed.</p></div></details>
<details style="padding:18px 20px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">05 · Fundamentals: CPI, NFP, FOMC & the Dollar</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Inflation/CPI:</b> compare the reported number with consensus and the prior reading. Markets often react to the surprise and the implications for expected interest rates, not simply whether inflation is high or low.</p><p><b>NFP and employment:</b> read headline payrolls alongside unemployment, wage growth and revisions. One headline figure rarely tells the whole story.</p><p><b>FOMC and rates:</b> central-bank statements, projections and press conferences can change rate expectations. The initial price reaction can reverse as traders digest the details.</p><p><b>Gold context:</b> gold may respond to real yields, the US dollar, central-bank demand and risk sentiment. Relationships can change; treat them as context, not fixed laws.</p><p><b>Practice:</b> record event time in South African time, consensus, actual result, first reaction and later reaction. Avoid entering during a release unless your tested plan specifically accounts for spread widening and slippage.</p></div></details>
<details style="padding:18px 20px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">06 · Gold (XAU/USD) Playbook</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Know the instrument:</b> gold contract specifications, tick value, trading hours and spread vary by broker. Confirm your broker's XAUUSD symbol and contract size before calculating risk.</p><p><b>Build a map:</b> review the 4H trend/range, prior day high and low, session high/low, major swing levels and nearby scheduled US data. Keep a written bullish and bearish scenario.</p><p><b>Wait for a trigger:</b> use the TW Blueprint sequence—indication, correction and continuation—rather than entering because price is moving quickly. Place invalidation where the setup is no longer valid, not where the loss merely feels comfortable.</p><p><b>Execution risks:</b> gold can move sharply around data and geopolitical headlines. Spreads, slippage and gaps can make realised losses larger than planned. Skip trades when the stop or position size cannot be executed responsibly.</p></div></details>
<details style="padding:18px 20px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">07 · Risk Management & Trade Planning</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Risk before reward:</b> choose a maximum cash risk before entry. Position size should be derived from account equity, allowed risk, stop distance and the instrument's tick/pip value—not from the profit target you hope to reach.</p><p><b>Reward-to-risk:</b> a 2R target means the planned gross reward is twice the planned risk. It does not mean a trade has a 2R expected value; win rate, costs, slippage and execution quality also matter.</p><p><b>Daily limits:</b> set a loss limit and stop after reaching it. Avoid revenge trading, increasing lot size to recover losses or moving a stop farther away to avoid being wrong.</p><p><b>Example:</b> on a R1,000 account, a hypothetical 1% risk budget is R10. This is an illustration, not a recommendation; verify the broker's contract value and ensure the minimum lot can fit the risk budget.</p></div></details>
<details style="padding:18px 20px;border:1px solid rgba(255,255,255,.1);border-radius:16px;background:rgba(255,255,255,.025);"><summary style="cursor:pointer;font-weight:800;font-size:17px;color:#00ffd0;">08 · The Autonomy of Success: Psychology, Journal & Review</summary><div style="color:#c0cad8;line-height:1.75;padding-top:12px;"><p><b>Process over outcome:</b> a well-planned trade can lose, and a reckless trade can win. Grade whether you followed your rules separately from the financial result.</p><p><b>Pre-trade checklist:</b> record the market regime, setup, confluence, entry trigger, invalidation, position size, scheduled news and reason to stand aside. If you cannot explain the trade in a few sentences, wait.</p><p><b>Journal fields:</b> date/time, instrument, session, screenshot before and after, setup type, risk in R, result in R, rule adherence, emotion and lesson. Review a meaningful sample of trades before changing the system.</p><p><b>Weekly review:</b> find repeated mistakes, separate rule-following trades from impulsive trades, and change one process at a time. Never treat a short winning streak as proof of a guaranteed edge.</p></div></details>
</div>
<div style="margin-top:22px;padding:18px 20px;border-radius:16px;background:rgba(0,255,208,.045);border:1px solid rgba(0,255,208,.16);"><h3 style="margin:0 0 8px;color:#00ffd0;">Your practice assignment</h3><p style="margin:0;color:#c0cad8;line-height:1.7;">Choose one instrument, mark its 4H structure, define the range, wait for a body-based indication, and document whether a correction and continuation appear. Screenshot the chart and calculate the planned risk before taking any demo trade. If the sequence is incomplete, the correct decision is no trade.</p></div>
<p style="text-align:center;color:#718096;font-size:12px;line-height:1.6;margin-top:22px;">Educational material only, not financial advice. BabyPips is an independent third-party resource. Trading leveraged products involves substantial risk; no lesson or confluence score guarantees results.</p>
</section>
<!-- END TW TRADES LIBRARY -->


<!-- TW INTELLIGENCE TERMINAL -->

<!-- =========================================================
     TW TRADES REAL TRADINGVIEW TERMINAL
========================================================= -->





<!-- =========================================================
     TW TRADES LIVE SCANNER DETAILS
========================================================= -->

<section id="twScannerDetails"
         style="padding:20px 0;">

    <div class="tw-live-card">

        <div style="
            display:flex;
            justify-content:space-between;
            gap:15px;
            align-items:center;
            flex-wrap:wrap;
        ">

            <div>

                <div class="tw-live-kicker">
                    TW TRADES • LIVE SCANNER
                </div>

                <h2 style="margin:5px 0;">
                    Market Intelligence Scanner
                </h2>

                <p id="twScannerDescription"
                   style="
                    color:#8997aa;
                    line-height:1.6;
                    margin:0;
                   ">
                    Select an instrument to analyse the current
                    live market response.
                </p>

            </div>

            <button
                type="button"
                class="tw-live-action"
                onclick="twRunDetailedScanner()">
                RUN SCAN
            </button>

        </div>


        <div style="
            display:grid;
            grid-template-columns:
                repeat(auto-fit,minmax(145px,1fr));
            gap:12px;
            margin-top:22px;
        ">

            <div class="tw-live-card"
                 style="padding:17px;">

                <small>BIAS</small>

                <div id="twScanBias"
                     style="
                        margin-top:8px;
                        font-size:21px;
                        font-weight:900;
                        color:#00ffd0;
                     ">
                    SCANNING
                </div>

            </div>


            <div class="tw-live-card"
                 style="padding:17px;">

                <small>SUPPORT</small>

                <div id="twScanSupport"
                     style="
                        margin-top:8px;
                        font-size:18px;
                        font-weight:800;
                     ">
                    —
                </div>

            </div>


            <div class="tw-live-card"
                 style="padding:17px;">

                <small>RESISTANCE</small>

                <div id="twScanResistance"
                     style="
                        margin-top:8px;
                        font-size:18px;
                        font-weight:800;
                     ">
                    —
                </div>

            </div>


            <div class="tw-live-card"
                 style="padding:17px;">

                <small>ENGINE</small>

                <div id="twScanEngine"
                     style="
                        margin-top:8px;
                        font-size:15px;
                        font-weight:800;
                        color:#00ffd0;
                     ">
                    READY
                </div>

            </div>

        </div>


        <div style="
            display:grid;
            grid-template-columns:
                repeat(auto-fit,minmax(200px,1fr));
            gap:12px;
            margin-top:15px;
        ">

            <div class="tw-live-card"
                 style="padding:18px;">

                <strong>
                    INDICATION
                </strong>

                <p id="twScanIndication"
                   style="
                    color:#aab7c8;
                    line-height:1.65;
                   ">
                    —
                </p>

            </div>


            <div class="tw-live-card"
                 style="padding:18px;">

                <strong>
                    CORRECTION
                </strong>

                <p id="twScanCorrection"
                   style="
                    color:#aab7c8;
                    line-height:1.65;
                   ">
                    —
                </p>

            </div>


            <div class="tw-live-card"
                 style="padding:18px;">

                <strong>
                    CONTINUATION
                </strong>

                <p id="twScanContinuation"
                   style="
                    color:#aab7c8;
                    line-height:1.65;
                   ">
                    —
                </p>

            </div>

        </div>


        <div style="
            margin-top:15px;
            display:grid;
            grid-template-columns:
                repeat(auto-fit,minmax(200px,1fr));
            gap:12px;
        ">

            <div class="tw-live-card"
                 style="padding:18px;">

                <strong>
                    TECHNICAL
                </strong>

                <p id="twScanTechnical"
                   style="
                    color:#aab7c8;
                    line-height:1.65;
                   ">
                    Waiting for live response.
                </p>

            </div>


            <div class="tw-live-card"
                 style="padding:18px;">

                <strong>
                    FUNDAMENTAL
                </strong>

                <p id="twScanFundamental"
                   style="
                    color:#aab7c8;
                    line-height:1.65;
                   ">
                    Waiting for live response.
                </p>

            </div>


            <div class="tw-live-card"
                 style="padding:18px;">

                <strong>
                    SENTIMENT
                </strong>

                <p id="twScanSentiment"
                   style="
                    color:#aab7c8;
                    line-height:1.65;
                   ">
                    Waiting for live response.
                </p>

            </div>

        </div>


        <div id="twScannerError"
             style="
                display:none;
                margin-top:15px;
                padding:15px;
                border-radius:12px;
                border:1px solid rgba(255,90,90,.25);
                background:rgba(255,90,90,.05);
                color:#ff8c8c;
             ">
        </div>

    </div>

</section>


<script>

(function(){

    window.twRunDetailedScanner =
        async function(){

        const asset =
            window.twCurrentAsset ||
            (
                document.getElementById(
                    "tw-terminal-symbol"
                ) || {}
            ).textContent ||
            "XAU/USD";

        const bias =
            document.getElementById(
                "twScanBias"
            );

        const engine =
            document.getElementById(
                "twScanEngine"
            );

        const errorBox =
            document.getElementById(
                "twScannerError"
            );

        if(errorBox){
            errorBox.style.display = "none";
            errorBox.textContent = "";
        }

        if(bias){
            bias.textContent = "SCANNING";
        }

        if(engine){
            engine.textContent = "SCANNING";
        }

        try{

            const response =
                await fetch(
                    "/api/scan?symbol=" +
                    encodeURIComponent(asset),
                    {
                        cache:"no-store"
                    }
                );

            if(!response.ok){
                throw new Error(
                    "Scanner HTTP " +
                    response.status
                );
            }

            const data =
                await response.json();

            if(data.error){
                throw new Error(data.error);
            }

            const value =
                function(key,fallback){

                    if(
                        data[key] !== undefined &&
                        data[key] !== null &&
                        String(data[key]).trim() !== ""
                    ){
                        return String(data[key]);
                    }

                    return fallback;

                };

            const set =
                function(id,text){

                    const el =
                        document.getElementById(id);

                    if(el){
                        el.textContent = text;
                    }

                };

            set(
                "twScanBias",
                value(
                    "bias",
                    value("signal","NEUTRAL")
                ).toUpperCase()
            );

            set(
                "twScanSupport",
                value("support","—")
            );

            set(
                "twScanResistance",
                value("resistance","—")
            );

            set(
                "twScanIndication",
                value(
                    "indication",
                    "No indication returned."
                )
            );

            set(
                "twScanCorrection",
                value(
                    "correction",
                    "No correction returned."
                )
            );

            set(
                "twScanContinuation",
                value(
                    "continuation",
                    "No continuation returned."
                )
            );

            set(
                "twScanTechnical",
                value(
                    "technical",
                    "No technical detail returned."
                )
            );

            set(
                "twScanFundamental",
                value(
                    "fundamental",
                    "No fundamental detail returned."
                )
            );

            set(
                "twScanSentiment",
                value(
                    "sentiment",
                    "No sentiment detail returned."
                )
            );

            set(
                "twScanEngine",
                "LIVE"
            );

            const description =
                document.getElementById(
                    "twScannerDescription"
                );

            if(description){
                description.textContent =
                    "Live scanner response for " +
                    asset +
                    ". Results come from the TW Trades market engine.";
            }

        }catch(error){

            if(engine){
                engine.textContent =
                    "ERROR";
            }

            if(errorBox){

                errorBox.style.display =
                    "block";

                errorBox.textContent =
                    "Live scanner error: " +
                    error.message;

            }

        }

    };

})();

</script>


<section id="intelligence-terminal" style="margin:70px auto;max-width:1200px;padding:28px 18px;border:1px solid rgba(0,255,208,.14);border-radius:28px;background:linear-gradient(145deg,#07101b,#03070d);box-shadow:0 20px 70px rgba(0,0,0,.35);">

<div style="display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap;margin-bottom:22px;">
<div>
<div style="font-size:12px;letter-spacing:3px;color:#00ffd0;font-weight:800;">TW TRADES INTELLIGENCE</div>
<h2 style="font-size:38px;margin:8px 0 5px;">Intelligence <span style="color:#00ffd0;">Terminal</span></h2>
<p style="margin:0;color:#8492a6;font-size:14px;">Live market analysis across technical, fundamental and sentiment layers.</p>
</div>
<div style="padding:9px 14px;border:1px solid rgba(0,255,208,.2);border-radius:999px;color:#00ffd0;font-size:12px;font-weight:800;">● LIVE ENGINE</div>
</div>

<div style="display:flex;gap:10px;overflow-x:auto;padding:5px 0 18px;scrollbar-width:none;">
<button class="tw-asset-btn" onclick="twSelectAsset('XAU/USD')" style="border:1px solid rgba(0,255,208,.3);background:rgba(0,255,208,.08);color:#00ffd0;padding:11px 18px;border-radius:999px;white-space:nowrap;">XAU/USD</button>
<button class="tw-asset-btn" onclick="twSelectAsset('EUR/USD')" style="border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.03);color:#b5c0cf;padding:11px 18px;border-radius:999px;white-space:nowrap;">EUR/USD</button>
<button class="tw-asset-btn" onclick="twSelectAsset('GBP/USD')" style="border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.03);color:#b5c0cf;padding:11px 18px;border-radius:999px;white-space:nowrap;">GBP/USD</button>
<button class="tw-asset-btn" onclick="twSelectAsset('USD/JPY')" style="border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.03);color:#b5c0cf;padding:11px 18px;border-radius:999px;white-space:nowrap;">USD/JPY</button>
<button class="tw-asset-btn" onclick="twSelectAsset('NASDAQ')" style="border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.03);color:#b5c0cf;padding:11px 18px;border-radius:999px;white-space:nowrap;">NASDAQ</button>
</div>

<div style="display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:15px;">

<div style="min-height:310px;padding:22px;border:1px solid rgba(255,255,255,.07);border-radius:22px;background:rgba(255,255,255,.025);">
<div style="display:flex;justify-content:space-between;align-items:center;">
<div>
<div id="tw-terminal-symbol" style="font-size:24px;font-weight:900;">XAU/USD</div>
<div style="color:#738094;font-size:12px;margin-top:4px;">Market terminal</div>
</div>
<div id="tw-terminal-status" style="font-size:12px;color:#00ffd0;">CONNECTING...</div>
</div>

<div style="height:180px;margin-top:22px;border-radius:15px;background:linear-gradient(180deg,rgba(0,255,208,.035),rgba(255,255,255,.01));display:flex;align-items:center;justify-content:center;text-align:center;">
<div>
<div style="font-size:38px;">◈</div>
<div style="color:#718096;font-size:13px;">Live chart data</div>
<div style="color:#465468;font-size:11px;margin-top:5px;">Connects to the TW market engine</div>
</div>
</div>
</div>

<div style="padding:22px;border:1px solid rgba(255,255,255,.07);border-radius:22px;background:rgba(255,255,255,.025);">
<div style="font-size:12px;letter-spacing:2px;color:#00ffd0;font-weight:800;">TW BLUEPRINT</div>
<h3 style="margin:10px 0 20px;">Market Structure</h3>

<div style="display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.06);">
<span style="color:#7e8b9d;">Indication</span><strong id="tw-indication">Scanning</strong>
</div>
<div style="display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.06);">
<span style="color:#7e8b9d;">Correction</span><strong id="tw-correction">Scanning</strong>
</div>
<div style="display:flex;justify-content:space-between;padding:12px 0;">
<span style="color:#7e8b9d;">Continuation</span><strong id="tw-continuation">Scanning</strong>
</div>
</div>

<div style="padding:22px;border:1px solid rgba(255,255,255,.07);border-radius:22px;background:rgba(255,255,255,.025);">
<div style="font-size:12px;letter-spacing:2px;color:#00ffd0;font-weight:800;">YUKI INTELLIGENCE</div>
<h3 style="margin:10px 0 20px;">Analysis Layers</h3>

<div style="margin-bottom:14px;">
<div style="display:flex;justify-content:space-between;font-size:13px;"><span>Technical</span><strong id="tw-tech">Scanning</strong></div>
<div style="height:5px;background:rgba(255,255,255,.08);border-radius:5px;margin-top:7px;"><div id="tw-tech-bar" style="width:0%;height:100%;border-radius:5px;background:#00ffd0;"></div></div>
</div>

<div style="margin-bottom:14px;">
<div style="display:flex;justify-content:space-between;font-size:13px;"><span>Fundamental</span><strong id="tw-fund">Scanning</strong></div>
<div style="height:5px;background:rgba(255,255,255,.08);border-radius:5px;margin-top:7px;"><div id="tw-fund-bar" style="width:0%;height:100%;border-radius:5px;background:#00ffd0;"></div></div>
</div>

<div>
<div style="display:flex;justify-content:space-between;font-size:13px;"><span>Sentiment</span><strong id="tw-sentiment">Scanning</strong></div>
<div style="height:5px;background:rgba(255,255,255,.08);border-radius:5px;margin-top:7px;"><div id="tw-sentiment-bar" style="width:0%;height:100%;border-radius:5px;background:#00ffd0;"></div></div>
</div>
</div>

</div>

<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:15px;">

<div style="padding:18px;border-radius:18px;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.025);">
<div style="font-size:11px;color:#718096;">MARKET BIAS</div>
<div id="tw-bias" style="font-size:20px;font-weight:900;margin-top:7px;">SCANNING</div>
</div>

<div style="padding:18px;border-radius:18px;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.025);">
<div style="font-size:11px;color:#718096;">SESSION</div>
<div id="tw-session" style="font-size:20px;font-weight:900;margin-top:7px;">LIVE</div>
</div>

<div style="padding:18px;border-radius:18px;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.025);">
<div style="font-size:11px;color:#718096;">SUPPORT</div>
<div id="tw-support" style="font-size:20px;font-weight:900;margin-top:7px;">—</div>
</div>

<div style="padding:18px;border-radius:18px;border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.025);">
<div style="font-size:11px;color:#718096;">RESISTANCE</div>
<div id="tw-resistance" style="font-size:20px;font-weight:900;margin-top:7px;">—</div>
</div>

</div>

<div style="margin-top:15px;padding:18px;border-radius:18px;border:1px solid rgba(0,255,208,.14);background:rgba(0,255,208,.025);">
<div style="display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap;">
<div>
<div style="font-size:11px;color:#718096;letter-spacing:2px;">YUKI / TW BLUEPRINT STATUS</div>
<div id="tw-engine-message" style="margin-top:6px;color:#aab7c8;font-size:14px;">Initializing live analysis...</div>
</div>
<div id="tw-signal" style="padding:10px 18px;border-radius:999px;border:1px solid rgba(0,255,208,.25);color:#00ffd0;font-weight:900;font-size:13px;">SCANNING</div>
</div>
</div>

<p style="margin:18px 0 0;color:#667387;font-size:11px;text-align:center;">
Analytical information only. Market conditions can change rapidly. This terminal does not guarantee trading results.
</p>

</section>
<!-- END TW INTELLIGENCE TERMINAL -->

<script>
(function(){
window.twCurrentAsset="XAU/USD";

window.twSelectAsset=function(asset){
window.twCurrentAsset=asset;
const symbol=document.getElementById("tw-terminal-symbol");
if(symbol) symbol.textContent=asset;

if(typeof window.twRunTerminal === "function"){
    window.twRunTerminal();
}

const tvSymbols={
    "XAU/USD":"OANDA:XAUUSD",
    "EUR/USD":"FX:EURUSD",
    "GBP/USD":"FX:GBPUSD",
    "USD/JPY":"FX:USDJPY",
    "NASDAQ":"NASDAQ:NDX",
    "BTC/USD":"COINBASE:BTCUSD"
};

if(typeof window.twLoadTradingView === "function"){
    window.twLoadTradingView(
        tvSymbols[asset] || "OANDA:XAUUSD"
    );
}
};

window.twRunTerminal=async function twRunTerminal(){
const status=document.getElementById("tw-terminal-status");
const msg=document.getElementById("tw-engine-message");

if(status) status.textContent="SCANNING...";

try{
const response=await fetch("/api/scan?symbol="+encodeURIComponent(window.twCurrentAsset),{cache:"no-store"});
const data=await response.json();

if(data && data.error){
throw new Error(data.error);
}

const bias=(data.bias||data.signal||"NEUTRAL").toString().toUpperCase();

document.getElementById("tw-bias").textContent=bias;
document.getElementById("tw-signal").textContent=bias;
document.getElementById("tw-terminal-status").textContent="● LIVE";

if(data.support) document.getElementById("tw-support").textContent=data.support;
if(data.resistance) document.getElementById("tw-resistance").textContent=data.resistance;

if(data.indication) document.getElementById("tw-indication").textContent=data.indication;
if(data.correction) document.getElementById("tw-correction").textContent=data.correction;
if(data.continuation) document.getElementById("tw-continuation").textContent=data.continuation;

if(data.technical){
document.getElementById("tw-tech").textContent=data.technical;
document.getElementById("tw-tech-bar").style.width="0%";
}

if(data.fundamental){
document.getElementById("tw-fund").textContent=data.fundamental;
document.getElementById("tw-fund-bar").style.width="0%";
}

if(data.sentiment){
document.getElementById("tw-sentiment").textContent=data.sentiment;
document.getElementById("tw-sentiment-bar").style.width="0%";
}

if(msg) msg.textContent="Live analysis returned for "+twCurrentAsset+".";
}catch(e){
if(status) status.textContent="ENGINE READY";
if(msg) msg.textContent="Waiting for live scan data. Existing market engine remains active.";
}
}

document.addEventListener("DOMContentLoaded",function(){
twRunTerminal();
});
})();
</script>


<!-- TW TRADES PUBLIC ACCESS -->

<!-- APEX FLOW ANALYTICS EMBED -->
<section id="apex-dashboard" style="max-width:1400px;margin:24px auto;padding:clamp(14px,3vw,30px);">
  <div style="border:1px solid rgba(0,255,208,.18);border-radius:24px;background:linear-gradient(145deg,#07101b,#03070d);padding:clamp(16px,3vw,28px);">
    <div style="display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap;margin-bottom:18px;">
      <div>
        <div style="color:#00ffd0;font-size:11px;letter-spacing:3px;font-weight:900;">CONNECTED WORKSPACE</div>
        <h2 style="margin:8px 0;font-size:clamp(24px,4vw,36px);">Apex Flow Analytics</h2>
        <p style="margin:0;color:#9aa9bc;line-height:1.6;">Embedded dashboard. If the provider blocks embedding, open the dashboard directly in a new tab.</p>
      </div>
      <a href="https://apex-flow-analytics-copy-c149c067.base44.app/Dashboard" target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:13px 18px;border-radius:11px;background:#00ffd0;color:#03100e;font-weight:900;text-decoration:none;">OPEN FULL DASHBOARD ↗</a>
    </div>
    <div style="position:relative;width:100%;height:min(78vh,900px);min-height:560px;overflow:hidden;border:1px solid #203348;border-radius:16px;background:#05070b;">
      <iframe
        src="https://apex-flow-analytics-copy-c149c067.base44.app/Dashboard"
        title="Apex Flow Analytics dashboard"
        loading="lazy"
        referrerpolicy="strict-origin-when-cross-origin"
        allow="clipboard-read; clipboard-write; fullscreen"
        allowfullscreen
        style="display:block;width:100%;height:100%;border:0;background:#05070b;"
      ></iframe>
    </div>
    <p style="color:#8493a8;font-size:12px;line-height:1.6;margin:12px 2px 0;">Your Apex Flow account may need to be signed in separately. The dashboard remains hosted by Base44; this embed does not transfer its data or login system into TW Trades.</p>
  </div>
</section>

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
target="_blank" rel="noopener"
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
REQUEST ACCESS — ACCOUNT 1
</a>

<a href="https://wa.me/27693118405?text=Hi%20Neo%2C%20I%20want%20to%20request%20TW%20Trades%20Public%20Access%20for%20R400.%20Please%20send%20me%20the%20payment%20and%20access%20instructions."
target="_blank" rel="noopener"
style="
display:inline-block;
padding:16px 32px;
border-radius:14px;
background:#101925;
color:#00ffd0;
border:1px solid #00ffd0;
font-weight:900;
text-decoration:none;
margin:8px;
">
REQUEST ACCESS — ACCOUNT 2
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



<!-- =========================================================
     TW TRADES LIVE MARKET UPGRADE
========================================================= -->

<style>

#tw-live-market-upgrade{
    max-width:1200px;
    margin:70px auto;
    padding:18px;
}

.tw-live-card{
    background:linear-gradient(145deg,#07101b,#03070d);
    border:1px solid rgba(0,255,208,.14);
    border-radius:26px;
    padding:24px;
    margin-bottom:22px;
    box-shadow:0 20px 70px rgba(0,0,0,.30);
}

.tw-live-head{
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:15px;
    flex-wrap:wrap;
    margin-bottom:20px;
}

.tw-live-kicker{
    color:#00ffd0;
    font-size:11px;
    letter-spacing:3px;
    font-weight:900;
}

.tw-live-title{
    font-size:34px;
    margin:7px 0;
    font-weight:900;
}

.tw-live-muted{
    color:#8190a5;
    line-height:1.6;
    font-size:14px;
}

.tw-live-controls{
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin-bottom:16px;
}

.tw-market-btn{
    border:1px solid rgba(255,255,255,.10);
    background:rgba(255,255,255,.035);
    color:#b9c5d5;
    padding:10px 15px;
    border-radius:999px;
    cursor:pointer;
    font-weight:800;
    transition:.2s;
}

.tw-market-btn:hover,
.tw-market-btn.active{
    border-color:rgba(0,255,208,.55);
    background:rgba(0,255,208,.10);
    color:#00ffd0;
    transform:translateY(-1px);
}

.tw-chart-wrap{
    height:620px;
    min-height:430px;
    overflow:hidden;
    border-radius:20px;
    border:1px solid rgba(255,255,255,.07);
    background:#050a10;
}

#twTradingViewChart{
    width:100%;
    height:100%;
}

.tw-scanner-grid{
    display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:14px;
}

.tw-scan-row{
    border:1px solid rgba(255,255,255,.08);
    background:rgba(255,255,255,.025);
    border-radius:18px;
    padding:18px;
    cursor:pointer;
    transition:.2s;
}

.tw-scan-row:hover{
    border-color:rgba(0,255,208,.35);
    transform:translateY(-2px);
}

.tw-scan-top{
    display:flex;
    justify-content:space-between;
    gap:10px;
    align-items:center;
    margin-bottom:12px;
}

.tw-scan-symbol{
    font-size:18px;
    font-weight:900;
}

.tw-scan-status{
    font-size:10px;
    letter-spacing:1px;
    color:#718096;
}

.tw-scan-bias{
    font-size:20px;
    font-weight:900;
    margin-bottom:12px;
}

.tw-scan-meta{
    display:grid;
    grid-template-columns:repeat(2,1fr);
    gap:8px;
}

.tw-scan-meta div{
    padding:9px;
    border-radius:10px;
    background:rgba(255,255,255,.035);
}

.tw-scan-meta span{
    display:block;
    font-size:9px;
    letter-spacing:1px;
    color:#657389;
    margin-bottom:4px;
}

.tw-scan-meta strong{
    font-size:12px;
}

.tw-scanner-actions{
    display:flex;
    gap:10px;
    flex-wrap:wrap;
    margin-bottom:18px;
}

.tw-live-action{
    border:1px solid rgba(0,255,208,.25);
    background:rgba(0,255,208,.07);
    color:#00ffd0;
    padding:11px 17px;
    border-radius:12px;
    font-weight:900;
    cursor:pointer;
}

.tw-live-action.secondary{
    border-color:rgba(255,255,255,.10);
    background:rgba(255,255,255,.035);
    color:#b9c5d5;
}

.tw-academy-modal{
    position:fixed;
    inset:0;
    background:rgba(0,0,0,.78);
    backdrop-filter:blur(10px);
    z-index:99999;
    display:none;
    align-items:center;
    justify-content:center;
    padding:18px;
}

.tw-academy-modal.open{
    display:flex;
}

.tw-academy-panel{
    width:min(760px,100%);
    max-height:88vh;
    overflow:auto;
    background:#07101b;
    border:1px solid rgba(0,255,208,.20);
    border-radius:25px;
    padding:26px;
    box-shadow:0 30px 100px rgba(0,0,0,.55);
}

.tw-academy-panel h2{
    margin-top:0;
}


.tw-lesson{
    cursor:pointer;
    transition:.2s;
    position:relative;
}

.tw-lesson:hover{
    border-color:rgba(0,255,208,.35);
    transform:translateY(-2px);
    background:rgba(0,255,208,.045);
}

.tw-lesson:after{
    content:"OPEN LESSON →";
    position:absolute;
    right:15px;
    top:50%;
    transform:translateY(-50%);
    color:#00ffd0;
    font-size:10px;
    font-weight:900;
    letter-spacing:1px;
}

.tw-lesson-detail{
    padding:20px;
    border-radius:17px;
    border:1px solid rgba(255,255,255,.07);
    background:rgba(255,255,255,.025);
    margin-bottom:15px;
}

.tw-lesson-detail h3{
    color:#00ffd0;
    margin-top:0;
}

.tw-lesson-detail p{
    color:#aab7c8;
    line-height:1.75;
}

.tw-lesson-detail ul{
    color:#aab7c8;
    line-height:1.8;
    padding-left:22px;
}

.tw-lesson-exercise{
    margin-top:18px;
    padding:17px;
    border-radius:15px;
    border:1px solid rgba(0,255,208,.16);
    background:rgba(0,255,208,.035);
}

.tw-lesson-exercise strong{
    color:#00ffd0;
}


.tw-lesson{
    padding:15px;
    margin:9px 0;
    border-radius:13px;
    background:rgba(255,255,255,.035);
    border:1px solid rgba(255,255,255,.06);
}

.tw-lesson strong{
    color:#00ffd0;
}

.tw-intel-tools{
    display:grid;
    grid-template-columns:repeat(3,minmax(0,1fr));
    gap:12px;
    margin-top:18px;
}

.tw-intel-tool{
    padding:18px;
    border-radius:17px;
    border:1px solid rgba(255,255,255,.08);
    background:rgba(255,255,255,.025);
    cursor:pointer;
    transition:.2s;
}

.tw-intel-tool:hover{
    border-color:rgba(0,255,208,.35);
    transform:translateY(-2px);
}

.tw-intel-tool b{
    display:block;
    margin-bottom:7px;
    color:#00ffd0;
}

.tw-intel-output{
    margin-top:16px;
    padding:18px;
    border-radius:16px;
    border:1px solid rgba(255,255,255,.07);
    background:rgba(0,0,0,.18);
    color:#aab7c8;
    line-height:1.7;
    min-height:70px;
}

@media(max-width:800px){

    #tw-live-market-upgrade{
        margin:45px auto;
        padding:10px;
    }

    .tw-live-card{
        padding:17px;
        border-radius:21px;
    }

    .tw-live-title{
        font-size:27px;
    }

    .tw-chart-wrap{
        height:470px;
        min-height:390px;
    }

    .tw-scanner-grid{
        grid-template-columns:1fr;
    }

    .tw-intel-tools{
        grid-template-columns:1fr;
    }

}

</style>

<section id="tw-live-market-upgrade">

    <!-- REAL TRADINGVIEW TERMINAL -->

    <div class="tw-live-card" id="tw-real-chart">

        <div class="tw-live-head">

            <div>
                <div class="tw-live-kicker">REAL MARKET DATA</div>

                <div class="tw-live-title">
                    TradingView Market Terminal
                </div>

                <div class="tw-live-muted">
                    Interactive market charts with live TradingView data,
                    technical indicators, drawing tools and symbol switching.
                </div>
            </div>

            <div id="twChartStatus"
                 style="color:#00ffd0;font-size:11px;font-weight:900;">
                ● CONNECTING
            </div>

        </div>

        <div class="tw-live-controls">

            <button class="tw-market-btn active"
                    data-tv-symbol="OANDA:XAUUSD">
                XAU/USD
            </button>

            <button class="tw-market-btn"
                    data-tv-symbol="FX:EURUSD">
                EUR/USD
            </button>

            <button class="tw-market-btn"
                    data-tv-symbol="FX:GBPUSD">
                GBP/USD
            </button>

            <button class="tw-market-btn"
                    data-tv-symbol="FX:USDJPY">
                USD/JPY
            </button>

            <button class="tw-market-btn"
                    data-tv-symbol="NASDAQ:NDX">
                NASDAQ
            </button>

            <button class="tw-market-btn"
                    data-tv-symbol="COINBASE:BTCUSD">
                BTC/USD
            </button>

        </div>

        <div class="tw-chart-wrap">

            <div id="twTradingViewChartMarket"></div>

        </div>

        <div class="tw-live-muted" style="margin-top:12px;">
            Chart supplied by TradingView. Market availability,
            exchange coverage and real-time status depend on the selected
            TradingView symbol/data source.
        </div>

    </div>


    <!-- LIVE SCANNER -->

    <div class="tw-live-card" id="scanner">

        <div class="tw-live-head">

            <div>
                <div class="tw-live-kicker">TW TRADES ENGINE</div>

                <div class="tw-live-title">
                    Live Market Scanner
                </div>

                <div class="tw-live-muted">
                    The scanner requests analysis from the existing TW Trades
                    market engine. It does not manufacture signals when data
                    is unavailable.
                </div>
            </div>

            <div id="twScannerStatus"
                 style="color:#00ffd0;font-size:11px;font-weight:900;">
                READY
            </div>

        </div>

        <div class="tw-scanner-actions">

            <button class="tw-live-action"
                    id="twRunScanner">
                RUN LIVE SCAN
            </button>

            <button class="tw-live-action secondary"
                    id="twClearScanner">
                CLEAR
            </button>

        </div>

        <div id="twScannerGrid"
             class="tw-scanner-grid">

            <div class="tw-live-muted">
                Press RUN LIVE SCAN to request current market analysis.
            </div>

        </div>

    </div>


    <!-- INTELLIGENCE TOOLS -->

    <div class="tw-live-card" id="tw-intelligence-tools">

        <div class="tw-live-kicker">
            MARKET INTELLIGENCE
        </div>

        <div class="tw-live-title">
            Intelligence Workspace
        </div>

        <div class="tw-live-muted">
            Use the live scanner, current financial news and the existing
            TW AI analysis endpoint as separate evidence layers.
        </div>

        <div class="tw-intel-tools">

            <div class="tw-intel-tool" data-intel="scanner">
                <b>◉ Market Scanner</b>
                Scan the configured TW Trades instruments.
            </div>

            <div class="tw-intel-tool" data-intel="news">
                <b>◆ Financial News</b>
                Load current news for the selected instrument.
            </div>

            <div class="tw-intel-tool" data-intel="ai">
                <b>✦ AI Analysis</b>
                Send the current market evidence to the existing AI endpoint.
            </div>

            <div class="tw-intel-tool" data-intel="structure">
                <b>◈ TW Blueprint</b>
                Review indication, correction and continuation.
            </div>

            <div class="tw-intel-tool" data-intel="risk">
                <b>△ Risk Framework</b>
                Review risk-management principles before execution.
            </div>

            <div class="tw-intel-tool" data-intel="academy">
                <b>◎ Academy</b>
                Open the structured learning modules.
            </div>

        </div>

        <div id="twIntelOutput" class="tw-intel-output">
            Select an intelligence tool.
        </div>

    </div>

</section>



<!-- TW LESSON DETAIL MODAL -->

<div id="twLessonDetailModal" class="tw-academy-modal">

    <div class="tw-academy-panel">

        <div style="display:flex;justify-content:space-between;gap:15px;align-items:start;">

            <div>
                <div class="tw-live-kicker">
                    THE AUTONOMY OF SUCCESS
                </div>

                <h2 id="twLessonDetailTitle">
                    Lesson
                </h2>
            </div>

            <button id="twLessonDetailClose"
                    class="tw-live-action secondary"
                    type="button">
                CLOSE
            </button>

        </div>

        <div id="twLessonDetailBody"
             style="margin-top:20px;">
        </div>

    </div>

</div>


<!-- ACADEMY LESSON MODAL -->

<div id="twAcademyModal" class="tw-academy-modal">

    <div class="tw-academy-panel">

        <div style="display:flex;justify-content:space-between;gap:15px;align-items:start;">

            <div>

                <div class="tw-live-kicker">
                    THE AUTONOMY OF SUCCESS
                </div>

                <h2 id="twAcademyTitle">
                    Academy Lesson
                </h2>

            </div>

            <button id="twAcademyClose"
                    class="tw-live-action secondary"
                    type="button">
                CLOSE
            </button>

        </div>

        <div id="twAcademyDescription"
             class="tw-live-muted">
        </div>

        <div id="twAcademyLessons"
             style="margin-top:20px;">
        </div>

    </div>

</div>


<script>
(function(){

    /* ========================================================
       TRADINGVIEW
    ======================================================== */

    const tvMap = {
        "OANDA:XAUUSD":"XAU/USD",
        "FX:EURUSD":"EUR/USD",
        "FX:GBPUSD":"GBP/USD",
        "FX:USDJPY":"USD/JPY",
        "NASDAQ:NDX":"NASDAQ",
        "COINBASE:BTCUSD":"BTC/USD"
    };

    window.twLoadTradingView = function(symbol){

        const container =
            document.getElementById("twTradingViewChartMarket");

        const status =
            document.getElementById("twChartStatus");

        if(!container) return;

        container.innerHTML = "";

        if(status){
            status.textContent = "● LOADING";
        }

        const widget =
            document.createElement("div");

        widget.className =
            "tradingview-widget-container";

        widget.style =
            "height:100%;width:100%;";

        const inner =
            document.createElement("div");

        inner.className =
            "tradingview-widget-container__widget";

        inner.style =
            "height:calc(100% - 32px);width:100%;";

        widget.appendChild(inner);

        const copyright =
            document.createElement("div");

        copyright.style =
            "font-size:10px;text-align:right;padding:3px;color:#566274;";

        copyright.innerHTML =
            'Charts by <a href="https://www.tradingview.com/" target="_blank" rel="noopener nofollow" style="color:#718096;">TradingView</a>';

        widget.appendChild(copyright);

        const script =
            document.createElement("script");

        script.type =
            "text/javascript";

        script.src =
            "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

        script.async = true;

        script.innerHTML =
            JSON.stringify({
                autosize:true,
                symbol:symbol,
                interval:"15",
                timezone:"exchange",
                theme:"dark",
                style:"1",
                locale:"en",
                enable_publishing:false,
                allow_symbol_change:true,
                hide_top_toolbar:false,
                hide_side_toolbar:false,
                hide_legend:false,
                hide_volume:false,
                withdateranges:true,
                save_image:false,
                calendar:false,
                hotlist:false,
                details:false,
                studies:[
                    "Volume@tv-basicstudies",
                    "MASimple@tv-basicstudies"
                ],
                support_host:"https://www.tradingview.com"
            });

        widget.appendChild(script);

        container.appendChild(widget);

        if(status){
            status.textContent =
                "● LIVE • " +
                (tvMap[symbol] || symbol);
        }
    };


    document
        .querySelectorAll("[data-tv-symbol]")
        .forEach(function(button){

            button.addEventListener("click",function(){

                document
                    .querySelectorAll("[data-tv-symbol]")
                    .forEach(function(b){
                        b.classList.remove("active");
                    });

                button.classList.add("active");

                window.twLoadTradingView(
                    button.getAttribute("data-tv-symbol")
                );

            });

        });


    /* ========================================================
       LIVE SCANNER
    ======================================================== */

    const scannerAssets = [
        "XAU/USD",
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "NASDAQ",
        "BTC/USD"
    ];

    const scannerGrid =
        document.getElementById("twScannerGrid");

    const scannerStatus =
        document.getElementById("twScannerStatus");


    function esc(value){

        return String(
            value === undefined ||
            value === null ||
            value === ""
                ? "—"
                : value
        )
        .replace(/&/g,"&amp;")
        .replace(/</g,"&lt;")
        .replace(/>/g,"&gt;")
        .replace(/"/g,"&quot;")
        .replace(/'/g,"&#039;");

    }


    function biasClass(value){

        const v =
            String(value || "NEUTRAL")
            .toUpperCase();

        if(v.includes("BUY") || v.includes("BULL")){
            return "#00ffd0";
        }

        if(v.includes("SELL") || v.includes("BEAR")){
            return "#ff6685";
        }

        return "#b9c5d5";

    }


    function scannerCard(symbol,data){

        if(!data || data.error){

            return `
            <div class="tw-scan-row">

                <div class="tw-scan-top">
                    <div class="tw-scan-symbol">
                        ${esc(symbol)}
                    </div>

                    <div class="tw-scan-status">
                        DATA UNAVAILABLE
                    </div>
                </div>

                <div class="tw-live-muted">
                    ${esc(data && data.error
                        ? data.error
                        : "No live response returned.")}
                </div>

            </div>`;
        }


        const bias =
            data.bias ||
            data.signal ||
            "NEUTRAL";


        return `
        <div class="tw-scan-row"
             data-scan-symbol="${esc(symbol)}">

            <div class="tw-scan-top">

                <div class="tw-scan-symbol">
                    ${esc(symbol)}
                </div>

                <div class="tw-scan-status">
                    LIVE RESPONSE
                </div>

            </div>

            <div class="tw-scan-bias"
                 style="color:${biasClass(bias)}">
                ${esc(bias)}
            </div>

            <div class="tw-scan-meta">

                <div>
                    <span>SUPPORT</span>
                    <strong>${esc(data.support)}</strong>
                </div>

                <div>
                    <span>RESISTANCE</span>
                    <strong>${esc(data.resistance)}</strong>
                </div>

                <div>
                    <span>INDICATION</span>
                    <strong>${esc(data.indication)}</strong>
                </div>

                <div>
                    <span>CORRECTION</span>
                    <strong>${esc(data.correction)}</strong>
                </div>

                <div>
                    <span>CONTINUATION</span>
                    <strong>${esc(data.continuation)}</strong>
                </div>

                <div>
                    <span>TECHNICAL</span>
                    <strong>${esc(data.technical)}</strong>
                </div>

                <div>
                    <span>FUNDAMENTAL</span>
                    <strong>${esc(data.fundamental)}</strong>
                </div>

                <div>
                    <span>SENTIMENT</span>
                    <strong>${esc(data.sentiment)}</strong>
                </div>

            </div>

        </div>`;
    }


    async function scanOne(symbol){

        try{

            const controller = new AbortController();
            const timeoutId = setTimeout(function(){
                controller.abort();
            }, 25000);

            let response;
            try {
                response = await fetch(
                    "/api/scan?symbol=" +
                    encodeURIComponent(symbol) +
                    "&_=" +
                    Date.now(),
                    {
                        cache:"no-store",
                        signal:controller.signal
                    }
                );
            } finally {
                clearTimeout(timeoutId);
            }

            if(!response.ok){
                throw new Error(
                    "HTTP " + response.status
                );
            }

            const data =
                await response.json();

            return {
                symbol:symbol,
                data:data
            };

        }catch(error){

            const message = error && error.name === "AbortError"
                ? "Market data request timed out after 25 seconds. Try again."
                : (error && error.message ? error.message : "Unknown scanner error");

            return {
                symbol:symbol,
                data:{
                    error:message
                }
            };

        }

    }


    window.twRunLiveScanner =
        async function(){

            if(!scannerGrid) return;

            if(scannerStatus){
                scannerStatus.textContent =
                    "SCANNING...";
            }

            scannerGrid.innerHTML = "";

            const loading =
                document.createElement("div");

            loading.className =
                "tw-live-muted";

            loading.textContent =
                "Requesting live analysis from the TW Trades engine...";

            scannerGrid.appendChild(loading);


            // Run scans concurrently so one slow symbol does not freeze the whole dashboard.
            const results = await Promise.all(
                scannerAssets.map(function(symbol){
                    return scanOne(symbol);
                })
            );


            scannerGrid.innerHTML =
                results
                .map(function(item){
                    return scannerCard(
                        item.symbol,
                        item.data
                    );
                })
                .join("");


            scannerGrid
                .querySelectorAll("[data-scan-symbol]")
                .forEach(function(card){

                    card.addEventListener("click",function(){

                        const symbol =
                            card.getAttribute(
                                "data-scan-symbol"
                            );

                        const chartSymbol =
                            Object.keys(tvMap)
                            .find(function(key){
                                return tvMap[key] === symbol;
                            });

                        if(chartSymbol){
                            window.twLoadTradingView(
                                chartSymbol
                            );

                            document
                                .getElementById("tw-real-chart")
                                ?.scrollIntoView({
                                    behavior:"smooth",
                                    block:"start"
                                });
                        }

                    });

                });


            const failures = results.filter(function(item){
                return !item.data || item.data.error;
            }).length;

            if(scannerStatus){
                scannerStatus.textContent = failures === results.length
                    ? "ERROR • No market responses"
                    : (failures ? "PARTIAL DATA • " + failures + " unavailable"
                                : "● LIVE • " + new Date().toLocaleTimeString());
            }

        };


    document
        .getElementById("twRunScanner")
        ?.addEventListener(
            "click",
            window.twRunLiveScanner
        );


    document
        .getElementById("twClearScanner")
        ?.addEventListener(
            "click",
            function(){

                scannerGrid.innerHTML =
                    '<div class="tw-live-muted">Scanner cleared. Press RUN LIVE SCAN to request new market data.</div>';

                if(scannerStatus){
                    scannerStatus.textContent =
                        "READY";
                }

            }
        );


    /* ========================================================
       ACADEMY — MAKE EXISTING COURSES CLICKABLE
    ======================================================== */

    const academyModal =
        document.getElementById(
            "twAcademyModal"
        );

    const academyTitle =
        document.getElementById(
            "twAcademyTitle"
        );

    const academyDescription =
        document.getElementById(
            "twAcademyDescription"
        );

    const academyLessons =
        document.getElementById(
            "twAcademyLessons"
        );


    function openAcademyCard(card){

        if(!card) return;

        const titleNode =
            card.querySelector("h3");

        const descNode =
            card.querySelector(".muted");

        const lessons =
            Array.from(
                card.querySelectorAll(".lesson")
            )
            .map(function(node){
                return node.textContent.trim();
            });


        if(academyTitle){
            academyTitle.textContent =
                titleNode
                    ? titleNode.textContent.trim()
                    : "Academy Lesson";
        }


        if(academyDescription){
            academyDescription.textContent =
                descNode
                    ? descNode.textContent.trim()
                    : "TW Trades educational module.";
        }


        if(academyLessons){

            if(lessons.length){

                academyLessons.innerHTML =
                    lessons.map(function(lesson,index){

                        const cleanLesson =
                            lesson.replace(
                                /^\\d+\\.\\s*/,
                                ""
                            );

                        return `
                        <div class="tw-lesson"
                             tabindex="0"
                             role="button"
                             data-lesson-title="${esc(cleanLesson)}">

                            <strong>
                                Lesson ${index + 1}
                            </strong>

                            <div style="margin-top:5px;padding-right:105px;">
                                ${esc(cleanLesson)}
                            </div>

                        </div>`;

                    }).join("");

            }else{

                academyLessons.innerHTML =
                    `<div class="tw-live-muted">
                        Course content will be expanded inside this module.
                    </div>`;

            }

        }


        if(academyModal){
            academyModal.classList.add("open");
        }

    }


    document
        .querySelectorAll(
            "#academy .card.course"
        )
        .forEach(function(card){

            card.setAttribute(
                "role",
                "button"
            );

            card.setAttribute(
                "tabindex",
                "0"
            );

            card.addEventListener(
                "click",
                function(){
                    openAcademyCard(card);
                }
            );

            card.addEventListener(
                "keydown",
                function(event){

                    if(
                        event.key === "Enter" ||
                        event.key === " "
                    ){

                        event.preventDefault();

                        openAcademyCard(card);

                    }

                }
            );

        });



    /* ========================================================
       TW TRADES LESSON ENGINE
    ======================================================== */

    const lessonDetailModal =
        document.getElementById(
            "twLessonDetailModal"
        );

    const lessonDetailTitle =
        document.getElementById(
            "twLessonDetailTitle"
        );

    const lessonDetailBody =
        document.getElementById(
            "twLessonDetailBody"
        );


    function lessonData(title){

        const t =
            String(title || "")
            .toLowerCase();


        if(t.includes("what is forex")){

            return {
                title:"What is Forex?",
                intro:"Forex is the global marketplace where currencies are exchanged against one another.",
                concepts:[
                    "Currency pairs quote one currency against another.",
                    "The first currency is the base currency and the second is the quote currency.",
                    "Price movement represents a change in the relative value between the two currencies.",
                    "Forex operates across major financial centres and trading sessions."
                ],
                practical:"Open EUR/USD on the TradingView terminal and identify which currency is the base currency and which is the quote currency."
            };

        }


        if(t.includes("currency pair")){

            return {
                title:"Currency Pairs",
                intro:"Currency pairs provide the basic structure of a forex quote.",
                concepts:[
                    "Major pairs commonly involve the US dollar.",
                    "Cross pairs exclude USD from the pair.",
                    "The quoted price tells you how much of the quote currency is needed for one unit of the base currency.",
                    "Always understand the pair before analysing its chart."
                ],
                practical:"Compare EUR/USD, GBP/USD and USD/JPY on the TradingView terminal. Record the base and quote currency for each."
            };

        }


        if(
            t.includes("pip") ||
            t.includes("lot") ||
            t.includes("spread")
        ){

            return {
                title:"Pips, Lots and Spreads",
                intro:"Position size, price increments and transaction costs are fundamental parts of trade planning.",
                concepts:[
                    "A pip is a standardised unit used to describe many currency-price movements.",
                    "A lot describes position size.",
                    "The spread is the difference between the bid and ask price.",
                    "Larger position sizes increase both potential gains and potential losses.",
                    "Trading costs should be considered before entering."
                ],
                practical:"Before opening a trade, calculate the intended position size and identify the spread on the instrument."
            };

        }


        if(
            t.includes("leverage") ||
            t.includes("margin")
        ){

            return {
                title:"Leverage and Margin",
                intro:"Leverage allows a trader to control a larger position with less capital, while margin is the capital required to support that position.",
                concepts:[
                    "Leverage increases exposure relative to account capital.",
                    "Margin is not the same thing as maximum affordable risk.",
                    "High leverage can amplify losses as well as gains.",
                    "Position sizing and stop placement remain essential."
                ],
                practical:"Calculate how much account capital would be exposed if price reaches your predefined invalidation level."
            };

        }


        if(t.includes("trading session")){

            return {
                title:"Trading Sessions",
                intro:"Global financial centres create different market sessions with different levels of activity and liquidity.",
                concepts:[
                    "Asian, London and New York sessions overlap at different times.",
                    "Session overlaps can produce changes in activity.",
                    "The most active period for an instrument depends on its underlying markets.",
                    "Session context should be combined with price structure rather than used as a standalone signal."
                ],
                practical:"Use the TradingView chart and mark the Asian, London and New York session ranges for an instrument you follow."
            };

        }


        if(
            t.includes("support") ||
            t.includes("resistance")
        ){

            return {
                title:"Support and Resistance",
                intro:"Support and resistance are price areas where previous market behaviour may provide useful context.",
                concepts:[
                    "Support can describe an area where selling pressure previously weakened.",
                    "Resistance can describe an area where buying pressure previously weakened.",
                    "Levels should be treated as areas rather than guaranteed reversal points.",
                    "Higher-timeframe structure can provide important context.",
                    "A level becomes more useful when combined with price action and market context."
                ],
                practical:"Mark two significant support areas and two significant resistance areas on the XAU/USD chart."
            };

        }


        if(
            t.includes("price action") ||
            t.includes("candlestick")
        ){

            return {
                title:"Price Action and Candlesticks",
                intro:"Price action analysis focuses on how price behaves rather than relying solely on indicators.",
                concepts:[
                    "Candlestick bodies show the opening and closing relationship.",
                    "Wicks show price exploration beyond the body.",
                    "Sequences of candles can reveal momentum and rejection.",
                    "Structure should be considered across multiple timeframes.",
                    "A single candle should not automatically be treated as a complete trading signal."
                ],
                practical:"Switch between the 4H, 1H and 5M charts and compare the structure before considering an entry."
            };

        }


        if(
            t.includes("fundamental") ||
            t.includes("macro")
        ){

            return {
                title:"Fundamental Analysis",
                intro:"Fundamental analysis examines economic conditions and events that can influence financial markets.",
                concepts:[
                    "Interest rates can affect currency valuation and capital flows.",
                    "Inflation data can influence expectations about monetary policy.",
                    "Employment data can change expectations about economic conditions.",
                    "Central-bank communication can affect market expectations.",
                    "Fundamental information should be considered alongside actual price behaviour."
                ],
                practical:"Check the current economic calendar before analysing a major currency pair and note the highest-impact events."
            };

        }


        if(
            t.includes("nfp") ||
            t.includes("cpi")
        ){

            return {
                title:"NFP and CPI Preparation",
                intro:"Major economic releases can produce rapid price movement and increased volatility.",
                concepts:[
                    "NFP is a major US employment report.",
                    "CPI measures changes in consumer prices and is closely watched for inflation trends.",
                    "Market reaction depends on expectations as well as the released number.",
                    "Spread and volatility conditions can change around major releases.",
                    "A predefined risk plan is important during high-volatility events."
                ],
                practical:"Before a major release, mark the previous day's high and low and identify the nearest higher-timeframe support and resistance."
            };

        }


        if(
            t.includes("risk") ||
            t.includes("money management")
        ){

            return {
                title:"Risk Management",
                intro:"Risk management defines how much capital is exposed when a trade idea is wrong.",
                concepts:[
                    "Define invalidation before entry.",
                    "Position size should be connected to the amount being risked.",
                    "A stop-loss should represent a meaningful invalidation point rather than an arbitrary distance.",
                    "Avoid increasing exposure simply because a position is losing.",
                    "A trading plan should define maximum daily and weekly risk."
                ],
                practical:"Create a trade plan containing entry, invalidation, position size, maximum loss and target before placing an order."
            };

        }


        if(
            t.includes("psychology") ||
            t.includes("discipline")
        ){

            return {
                title:"Trading Psychology and Discipline",
                intro:"A structured process can help separate analysis from emotional reactions to individual trades.",
                concepts:[
                    "Follow predefined entry and risk rules.",
                    "Do not change a plan solely because of short-term price movement.",
                    "Keep a journal of decisions rather than only recording profits and losses.",
                    "Review repeated mistakes for patterns.",
                    "A losing trade does not automatically mean the analysis process was invalid, and a winning trade does not automatically prove it was correct."
                ],
                practical:"After your next trade, record the setup, reason for entry, risk, execution and whether you followed your rules."
            };

        }


        if(
            t.includes("indication") ||
            t.includes("correction") ||
            t.includes("continuation") ||
            t.includes("icc") ||
            t.includes("blueprint")
        ){

            return {
                title:"TW Blueprint — Indication, Correction, Continuation",
                intro:"The TW Blueprint framework separates a potential directional move into structural stages.",
                concepts:[
                    "Indication identifies the initial structural change or directional evidence.",
                    "Correction describes the retracement or pullback after the indication.",
                    "Continuation describes renewed movement in the indicated direction.",
                    "Higher-timeframe structure provides context for lower-timeframe execution.",
                    "The framework should be tested against actual price behaviour rather than treated as a guaranteed signal."
                ],
                practical:"On a TradingView chart, identify a previous indication, correction and continuation sequence and mark each stage."
            };

        }


        return {
            title:title || "TW Trades Lesson",
            intro:"This lesson is part of the TW Trades education system.",
            concepts:[
                "Understand the definition of the topic.",
                "Identify the concept on a real market chart.",
                "Connect the concept to your trading plan.",
                "Record your observations in a trading journal."
            ],
            practical:"Apply the lesson to a real chart using the TradingView terminal and document what you observe."
        };

    }


    function openLessonDetail(title){

        const data =
            lessonData(title);

        if(lessonDetailTitle){
            lessonDetailTitle.textContent =
                data.title;
        }

        if(lessonDetailBody){

            lessonDetailBody.innerHTML = `

                <div class="tw-lesson-detail">

                    <h3>
                        Lesson overview
                    </h3>

                    <p>
                        ${esc(data.intro)}
                    </p>

                </div>

                <div class="tw-lesson-detail">

                    <h3>
                        Key concepts
                    </h3>

                    <ul>
                        ${data.concepts
                            .map(function(item){
                                return "<li>" +
                                    esc(item) +
                                    "</li>";
                            })
                            .join("")}
                    </ul>

                </div>

                <div class="tw-lesson-exercise">

                    <strong>
                        PRACTICAL EXERCISE
                    </strong>

                    <p style="margin-bottom:0;color:#aab7c8;line-height:1.7;">
                        ${esc(data.practical)}
                    </p>

                </div>

            `;

        }

        if(lessonDetailModal){
            lessonDetailModal.classList.add(
                "open"
            );
        }

    }


    function bindLessonButtons(){

        if(!academyLessons) return;

        academyLessons
            .querySelectorAll(
                "[data-lesson-title]"
            )
            .forEach(function(lesson){

                lesson.addEventListener(
                    "click",
                    function(){

                        openLessonDetail(
                            lesson.getAttribute(
                                "data-lesson-title"
                            )
                        );

                    }
                );

                lesson.addEventListener(
                    "keydown",
                    function(event){

                        if(
                            event.key === "Enter" ||
                            event.key === " "
                        ){

                            event.preventDefault();

                            openLessonDetail(
                                lesson.getAttribute(
                                    "data-lesson-title"
                                )
                            );

                        }

                    }
                );

            });

    }


    /* Re-bind whenever a course is opened */
    const originalOpenAcademyCard =
        openAcademyCard;

    openAcademyCard = function(card){

        originalOpenAcademyCard(card);

        setTimeout(
            bindLessonButtons,
            30
        );

    };


    document
        .getElementById(
            "twLessonDetailClose"
        )
        ?.addEventListener(
            "click",
            function(){

                lessonDetailModal
                    ?.classList.remove("open");

            }
        );


    lessonDetailModal
        ?.addEventListener(
            "click",
            function(event){

                if(
                    event.target ===
                    lessonDetailModal
                ){

                    lessonDetailModal
                        .classList.remove("open");

                }

            }
        );



    document
        .getElementById("twAcademyClose")
        ?.addEventListener(
            "click",
            function(){

                academyModal
                    ?.classList.remove("open");

            }
        );


    academyModal
        ?.addEventListener(
            "click",
            function(event){

                if(event.target === academyModal){

                    academyModal.classList.remove(
                        "open"
                    );

                }

            }
        );



    /* ========================================================
       LESSON CLICK FALLBACK
    ======================================================== */

    document.addEventListener(
        "click",
        function(event){

            const lesson =
                event.target.closest(
                    "#twAcademyLessons [data-lesson-title]"
                );

            if(!lesson) return;

            openLessonDetail(
                lesson.getAttribute(
                    "data-lesson-title"
                )
            );

        }
    );


    /* ========================================================
       INTELLIGENCE WORKSPACE
    ======================================================== */

    const intelOutput =
        document.getElementById(
            "twIntelOutput"
        );


    document
        .querySelectorAll(
            "[data-intel]"
        )
        .forEach(function(tool){

            tool.addEventListener(
                "click",
                async function(){

                    const type =
                        tool.getAttribute(
                            "data-intel"
                        );

                    if(!intelOutput) return;


                    if(type === "scanner"){

                        intelOutput.innerHTML =
                            "Running the live scanner...";

                        document
                            .getElementById(
                                "scanner"
                            )
                            ?.scrollIntoView({
                                behavior:"smooth"
                            });

                        await window.twRunLiveScanner();

                        return;
                    }


                    if(type === "news"){

                        intelOutput.innerHTML =
                            "Loading current financial news...";

                        try{

                            const response =
                                await fetch(
                                    "/api/news?symbol=XAU/USD&_=" +
                                    Date.now(),
                                    {
                                        cache:"no-store"
                                    }
                                );

                            const data =
                                await response.json();

                            if(data.error){

                                intelOutput.textContent =
                                    data.error;

                                return;
                            }

                            let items =
                                data.data ||
                                data.articles ||
                                data.news ||
                                [];

                            if(!Array.isArray(items)){
                                items = [];
                            }

                            if(!items.length){

                                intelOutput.textContent =
                                    "No current news items were returned by the configured news engine.";

                                return;
                            }

                            intelOutput.innerHTML =
                                items
                                .slice(0,6)
                                .map(function(item){

                                    const title =
                                        item.title ||
                                        item.headline ||
                                        "Untitled";

                                    const source =
                                        item.source ||
                                        item.source_name ||
                                        "";

                                    return `
                                    <div style="padding:12px 0;border-bottom:1px solid rgba(255,255,255,.07);">
                                        <strong>
                                            ${esc(title)}
                                        </strong>

                                        <div style="font-size:11px;color:#718096;margin-top:5px;">
                                            ${esc(source)}
                                        </div>
                                    </div>`;

                                })
                                .join("");

                        }catch(error){

                            intelOutput.textContent =
                                "News request failed: " +
                                error.message;

                        }

                        return;
                    }


                    if(type === "ai"){

                        intelOutput.innerHTML =
                            "Opening the TW Intelligence Analyst...";

                        document
                            .getElementById(
                                "ai-intelligence"
                            )
                            ?.scrollIntoView({
                                behavior:"smooth"
                            });

                        setTimeout(function(){

                            if(
                                typeof window.runAI ===
                                "function"
                            ){
                                window.runAI();
                            }

                        },500);

                        return;
                    }


                    if(type === "structure"){

                        intelOutput.innerHTML = `
                        <strong style="color:#00ffd0;">
                            TW BLUEPRINT — ICC
                        </strong>

                        <p>
                            <b>Indication:</b>
                            identify the structural break or directional
                            indication.
                        </p>

                        <p>
                            <b>Correction:</b>
                            wait for the market to retrace or correct
                            rather than treating the initial move as
                            automatic confirmation.
                        </p>

                        <p>
                            <b>Continuation:</b>
                            evaluate whether price resumes the indicated
                            direction with supporting structure.
                        </p>

                        <p>
                            This educational framework does not guarantee
                            a trading outcome.
                        </p>`;

                        return;
                    }


                    if(type === "risk"){

                        intelOutput.innerHTML = `
                        <strong style="color:#00ffd0;">
                            RISK FRAMEWORK
                        </strong>

                        <p>
                            Define the invalidation level before entering.
                        </p>

                        <p>
                            Determine position size from the amount you
                            are prepared to risk rather than from the
                            desired profit.
                        </p>

                        <p>
                            Avoid increasing exposure simply because a
                            position is moving against you.
                        </p>

                        <p>
                            Trading involves substantial risk and the
                            scanner is not financial advice.
                        </p>`;

                        return;
                    }


                    if(type === "academy"){

                        document
                            .getElementById(
                                "academy"
                            )
                            ?.scrollIntoView({
                                behavior:"smooth"
                            });

                        return;
                    }

                }
            );

        });


    /* ========================================================
       INITIAL CHART
    ======================================================== */

    if(
        document.getElementById(
            "twTradingViewChartMarket"
        )
    ){

        window.twLoadTradingView(
            "OANDA:XAUUSD"
        );

    }

})();
</script>



<script>
/* TW SCANNER CLICK DIAGNOSTIC FALLBACK */
(function(){
  function bindScannerFallback(){
    const button = document.getElementById("twRunScanner");
    const status = document.getElementById("twScannerStatus");
    const grid = document.getElementById("twScannerGrid");
    if(!button || button.dataset.twFallbackBound === "1") return;
    button.dataset.twFallbackBound = "1";
    button.addEventListener("click", function(){
      if(status) status.textContent = "BUTTON WORKS • CHECKING ENGINE";
      if(grid) grid.innerHTML = '<div class="tw-live-muted">Scanner button received your tap. Connecting to the TW Trades engine…</div>';
      if(typeof window.twRunLiveScanner === "function"){
        Promise.resolve(window.twRunLiveScanner()).catch(function(err){
          if(status) status.textContent = "SCANNER ERROR";
          if(grid) grid.textContent = "Scanner failed: " + (err && err.message ? err.message : "unknown error");
        });
      } else {
        if(status) status.textContent = "ENGINE SCRIPT NOT LOADED";
        if(grid) grid.textContent = "The scanner button works, but the main scanner script did not load. Refresh the page; if this remains, the page JavaScript needs repair.";
      }
    });
  }
  if(document.readyState === "loading") document.addEventListener("DOMContentLoaded", bindScannerFallback);
  else bindScannerFallback();
})();
</script>

<script>
/* The older detailed scanner is hidden during homepage cleanup.
   The visible live scanner is started only by the user's button. */
</script>


<style>
/* =========================================================
   TW TRADES — LIVE MARKET TERMINAL
   ========================================================= */
#tw-live-terminal-v2{
  margin:32px auto;
  max-width:1500px;
  padding:18px;
  border:1px solid rgba(255,255,255,.09);
  border-radius:24px;
  background:linear-gradient(180deg,rgba(15,18,24,.98),rgba(7,9,13,.98));
  box-shadow:0 20px 70px rgba(0,0,0,.35);
}

.tw-live-head{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:15px;
  margin-bottom:16px;
  flex-wrap:wrap;
}

.tw-live-title{
  font-size:clamp(20px,3vw,30px);
  font-weight:800;
  letter-spacing:.04em;
}

.tw-live-sub{
  opacity:.65;
  font-size:12px;
  margin-top:4px;
}

.tw-live-status{
  padding:8px 12px;
  border:1px solid rgba(255,255,255,.1);
  border-radius:999px;
  font-size:11px;
  letter-spacing:.08em;
}

.tw-live-assets{
  display:flex;
  gap:8px;
  overflow-x:auto;
  padding:4px 0 12px;
  scrollbar-width:none;
}

.tw-live-assets::-webkit-scrollbar{display:none}

.tw-live-assets button{
  flex:0 0 auto;
  border:1px solid rgba(255,255,255,.1);
  background:#11151c;
  color:inherit;
  border-radius:12px;
  padding:10px 14px;
  cursor:pointer;
  font-weight:700;
}

.tw-live-assets button.active{
  border-color:#fff;
  background:#fff;
  color:#050505;
}

.tw-live-grid{
  display:grid;
  grid-template-columns:minmax(0,2fr) minmax(300px,1fr);
  gap:14px;
}

.tw-live-chart{
  min-height:520px;
  border-radius:18px;
  overflow:hidden;
  border:1px solid rgba(255,255,255,.08);
  background:#05070a;
}

#tw-tv-widget{
  width:100%;
  height:100%;
  min-height:520px;
}

.tw-live-analysis{
  display:grid;
  gap:10px;
}

.tw-live-card{
  border:1px solid rgba(255,255,255,.08);
  border-radius:16px;
  padding:15px;
  background:rgba(255,255,255,.025);
}

.tw-live-card-title{
  font-size:10px;
  text-transform:uppercase;
  letter-spacing:.12em;
  opacity:.55;
  margin-bottom:8px;
}

.tw-live-value{
  font-size:18px;
  font-weight:800;
  line-height:1.25;
}

.tw-live-detail{
  font-size:12px;
  opacity:.7;
  margin-top:5px;
  line-height:1.5;
}

.tw-live-row{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
}

.tw-live-actions{
  display:flex;
  gap:8px;
  flex-wrap:wrap;
  margin-top:12px;
}

.tw-live-actions button{
  border:1px solid rgba(255,255,255,.12);
  background:#11151c;
  color:inherit;
  padding:10px 13px;
  border-radius:11px;
  cursor:pointer;
  font-weight:700;
}

.tw-live-loading{
  opacity:.55;
}

@media(max-width:900px){
  .tw-live-grid{
    grid-template-columns:1fr;
  }

  .tw-live-chart,
  #tw-tv-widget{
    min-height:420px;
  }
}

@media(max-width:600px){
  #tw-live-terminal-v2{
    margin:20px 8px;
    padding:12px;
    border-radius:18px;
  }

  .tw-live-row{
    grid-template-columns:1fr;
  }

  .tw-live-chart,
  #tw-tv-widget{
    min-height:360px;
  }
}

/* Mobile navigation: toggled by the command-menu button */
@media (max-width: 900px) {
  nav .navlinks.tw-nav-open {
    display: flex !important;
    position: absolute;
    top: 72px;
    left: 12px;
    right: 12px;
    z-index: 9999;
    flex-direction: column;
    align-items: stretch;
    gap: 0;
    padding: 10px;
    border: 1px solid rgba(0,255,208,.25);
    border-radius: 14px;
    background: rgba(7,12,24,.98);
    box-shadow: 0 18px 50px rgba(0,0,0,.45);
  }
  nav .navlinks.tw-nav-open a {
    display: block;
    padding: 12px 14px;
  }
}

#twTradingViewChartMarket{
    width:100%;
    min-height:450px;
    height:520px;
    border-radius:14px;
    overflow:hidden;
}

/* HOMEPAGE CLEANUP: one canonical scanner/chart; suppress duplicate injected copies only. */
#twScannerDetails,
#intelligence-terminal,
#tw-live-terminal-v2 {
  display: none !important;
}
/* #tw-live-market-upgrade owns the #scanner navigation target and the market
   chart, so it must stay visible. */
/* #apex-dashboard is a unique top-level section linked from the primary
   navigation, so it is intentionally not suppressed here. */
#terminal, #intelligence, #ai-intelligence, #apex-dashboard,
#tw-live-market-upgrade { display:block; }


</style>

<section id="tw-live-terminal-v2">

  <div class="tw-live-head">
    <div>
      <div class="tw-live-title">TW LIVE MARKET TERMINAL</div>
      <div class="tw-live-sub">
        TradingView chart • TW Blueprint scanner • live API analysis
      </div>
    </div>

    <div id="tw-live-status" class="tw-live-status">
      CONNECTING
    </div>
  </div>

  <div class="tw-live-assets">
    <button data-tw-asset="XAU/USD" class="active">XAU/USD</button>
    <button data-tw-asset="EUR/USD">EUR/USD</button>
    <button data-tw-asset="GBP/USD">GBP/USD</button>
    <button data-tw-asset="USD/JPY">USD/JPY</button>
    <button data-tw-asset="NASDAQ">NASDAQ</button>
    <button data-tw-asset="BTC/USD">BTC/USD</button>
  </div>

  <div class="tw-live-grid">

    <div class="tw-live-chart">
      <div id="tw-tv-widget"></div>
    </div>

    <div class="tw-live-analysis">

      <div class="tw-live-card">
        <div class="tw-live-card-title">Selected Market</div>
        <div id="tw-live-symbol" class="tw-live-value">XAU/USD</div>
        <div id="tw-live-message" class="tw-live-detail">
          Connecting to live market scanner...
        </div>
      </div>

      <div class="tw-live-card">
        <div class="tw-live-card-title">Market Bias</div>
        <div id="tw-live-bias" class="tw-live-value">SCANNING</div>
        <div id="tw-live-signal" class="tw-live-detail">Waiting for live response</div>
      </div>

      <div class="tw-live-row">

        <div class="tw-live-card">
          <div class="tw-live-card-title">Support</div>
          <div id="tw-live-support" class="tw-live-value">—</div>
        </div>

        <div class="tw-live-card">
          <div class="tw-live-card-title">Resistance</div>
          <div id="tw-live-resistance" class="tw-live-value">—</div>
        </div>

      </div>

      <div class="tw-live-card">
        <div class="tw-live-card-title">TW Blueprint</div>

        <div class="tw-live-detail">
          <strong>Indication:</strong>
          <span id="tw-live-indication">Waiting</span>
        </div>

        <div class="tw-live-detail">
          <strong>Correction:</strong>
          <span id="tw-live-correction">Waiting</span>
        </div>

        <div class="tw-live-detail">
          <strong>Continuation:</strong>
          <span id="tw-live-continuation">Waiting</span>
        </div>
      </div>

      <div class="tw-live-card">

        <div class="tw-live-card-title">Market Intelligence</div>

        <div class="tw-live-detail">
          <strong>Technical:</strong>
          <span id="tw-live-technical">Waiting</span>
        </div>

        <div class="tw-live-detail">
          <strong>Fundamental:</strong>
          <span id="tw-live-fundamental">Waiting</span>
        </div>

        <div class="tw-live-detail">
          <strong>Sentiment:</strong>
          <span id="tw-live-sentiment">Waiting</span>
        </div>

      </div>

      <div class="tw-live-actions">
        <button type="button" onclick="twLiveScan()">SCAN MARKET</button>
        <button type="button" onclick="twLiveRefresh()">REFRESH</button>
      </div>

    </div>
  </div>
</section>

<script>
(function(){

const TW_LIVE_SYMBOLS={
  "XAU/USD":"OANDA:XAUUSD",
  "EUR/USD":"OANDA:EURUSD",
  "GBP/USD":"OANDA:GBPUSD",
  "USD/JPY":"OANDA:USDJPY",
  "NASDAQ":"NASDAQ:NDX",
  "BTC/USD":"COINBASE:BTCUSD"
};

let twLiveAsset="XAU/USD";
let twLiveTimer=null;

function twEl(id){
  return document.getElementById(id);
}

function twTradingView(asset){

  const box=twEl("tw-tv-widget");
  if(!box) return;

  box.innerHTML="";

  const wrapper=document.createElement("div");
  wrapper.className="tradingview-widget-container";
  wrapper.style.width="100%";
  wrapper.style.height="100%";

  const chart=document.createElement("div");
  chart.className="tradingview-widget-container__widget";
  chart.style.width="100%";
  chart.style.height="100%";

  wrapper.appendChild(chart);
  box.appendChild(wrapper);

  const script=document.createElement("script");

  script.src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
  script.type="text/javascript";
  script.async=true;

  script.innerHTML=JSON.stringify({
    autosize:true,
    symbol:TW_LIVE_SYMBOLS[asset] || "OANDA:XAUUSD",
    interval:"15",
    timezone:"Africa/Johannesburg",
    theme:"dark",
    style:"1",
    locale:"en",
    allow_symbol_change:false,
    calendar:false,
    support_host:"https://www.tradingview.com"
  });

  wrapper.appendChild(script);
}

function twText(id,value){

  const el=twEl(id);

  if(!el) return;

  if(value===undefined || value===null || value===""){
    el.textContent="Not returned by live engine";
    return;
  }

  el.textContent=String(value);
}

window.twLiveScan=async function(){

  twText("tw-live-message","Requesting live scanner data...");
  twText("tw-live-bias","SCANNING");

  const status=twEl("tw-live-status");

  if(status) status.textContent="SCANNING";

  try{

    const response=await fetch(
      "/api/scan?symbol="+encodeURIComponent(twLiveAsset),
      {
        cache:"no-store",
        headers:{
          "Accept":"application/json"
        }
      }
    );

    if(!response.ok){
      throw new Error("Scanner HTTP "+response.status);
    }

    const data=await response.json();

    if(data && data.error){
      throw new Error(data.error);
    }

    const scanStatus=data.status||"UNKNOWN";
    const bias=data.direction||data.bias||"NEUTRAL";
    const explanation=data.message||(
      scanStatus==="QUALIFIED"
        ? "Qualified setup returned by the scanner."
        : "No qualified setup. Review the scanner status and data requirements."
    );

    twText("tw-live-symbol",twLiveAsset);
    twText("tw-live-bias",scanStatus==="QUALIFIED"?bias:scanStatus);
    twText(
      "tw-live-signal",
      scanStatus==="QUALIFIED"
        ? ((data.reasons||[]).join("; ")||"Setup qualified")
        : explanation
    );

    twText("tw-live-support",data.support);
    twText("tw-live-resistance",data.resistance);
    twText("tw-live-indication",data.indication);
    twText("tw-live-correction",data.correction);
    twText("tw-live-continuation",data.continuation);
    twText("tw-live-technical",data.technical||data.technical_analysis||(
      [data.trend4h&&("4H "+data.trend4h),data.trend1h&&("1H "+data.trend1h),data.trend15m&&("15M "+data.trend15m)].filter(Boolean).join(" · ")
    ));
    twText("tw-live-fundamental",data.fundamental?.bias||data.fundamental||data.fundamental_analysis);
    twText("tw-live-sentiment",data.news_sentiment!==undefined?data.news_sentiment:data.sentiment||data.sentiment_analysis);

    twText(
      "tw-live-message",
      twLiveAsset+" — "+scanStatus+": "+explanation
    );

    if(status) status.textContent=scanStatus==="QUALIFIED"?"● QUALIFIED":scanStatus==="DATA ERROR"?"DATA ERROR":"● SCANNER ONLINE";

  }catch(error){

    twText(
      "tw-live-message",
      "Live scanner unavailable: "+error.message
    );

    if(status) status.textContent="ENGINE OFFLINE";
  }
};

window.twLiveSelect=function(asset){

  if(!TW_LIVE_SYMBOLS[asset]) return;

  twLiveAsset=asset;

  document
    .querySelectorAll("[data-tw-asset]")
    .forEach(function(button){
      button.classList.toggle(
        "active",
        button.getAttribute("data-tw-asset")===asset
      );
    });

  twText("tw-live-symbol",asset);

  twTradingView(asset);
  twLiveScan();

};

window.twLiveRefresh=function(){

  twTradingView(twLiveAsset);
  twLiveScan();

};

document.addEventListener("click",function(event){

  const button=event.target.closest("[data-tw-asset]");

  if(!button) return;

  twLiveSelect(button.getAttribute("data-tw-asset"));

});

document.addEventListener("DOMContentLoaded",function(){

  twTradingView(twLiveAsset);
  twLiveScan();

  if(twLiveTimer){
    clearInterval(twLiveTimer);
  }

  twLiveTimer=setInterval(
    function(){
      twLiveScan();
    },
    60000
  );

});

})();

/* TW Trades mobile navigation repair */
(function(){
  function initTWMobileMenu(){
    const button = document.getElementById("twMenuButton");
    const links = document.querySelector("nav .navlinks");
    if(!button || !links || button.dataset.twMenuReady === "1") return;
    button.dataset.twMenuReady = "1";
    button.addEventListener("click", function(){
      const isOpen = links.classList.toggle("tw-nav-open");
      button.setAttribute("aria-expanded", isOpen ? "true" : "false");
      button.setAttribute("aria-label", isOpen ? "Close TW Trades command menu" : "Open TW Trades command menu");
    });
    links.querySelectorAll("a").forEach(function(link){
      link.addEventListener("click", function(){
        links.classList.remove("tw-nav-open");
        button.setAttribute("aria-expanded","false");
        button.setAttribute("aria-label","Open TW Trades command menu");
      });
    });
  }
  if(document.readyState === "loading"){
    document.addEventListener("DOMContentLoaded", initTWMobileMenu);
  } else {
    initTWMobileMenu();
  }
})();

</script>


<script>
/* TW Trades navigation page switcher: Home shows only landing + request/contact; other sections open from navigation. */
(function(){
  function initTWPageNavigation(){
    const body=document.body;
    const nav=document.querySelector('nav .navlinks');
    if(!body||!nav||body.dataset.twPageNavigationReady==='1') return;
    body.dataset.twPageNavigationReady='1';
    function showLanding(){
      body.classList.remove('tw-nav-view');
      document.querySelectorAll('section.tw-nav-active').forEach(function(section){section.classList.remove('tw-nav-active');});
      window.scrollTo({top:0,behavior:'smooth'});
    }
    function showPage(target){
      const element=document.getElementById(target);
      if(!element){ window.location.hash=target; return; }
      const section=element.closest('section');
      if(!section){ window.location.hash=target; return; }
      body.classList.add('tw-nav-view');
      document.querySelectorAll('section.tw-nav-active').forEach(function(item){item.classList.remove('tw-nav-active');});
      let current=section;
      while(current){
        if(current.tagName==='SECTION') current.classList.add('tw-nav-active');
        current=current.parentElement ? current.parentElement.closest('section') : null;
      }
      window.scrollTo({top:0,behavior:'smooth'});
    }
    document.querySelectorAll('a[href^="#"]').forEach(function(link){
      link.addEventListener('click',function(event){
        const target=(link.getAttribute('href')||'').slice(1);
        if(!target) return;
        event.preventDefault();
        if(target==='top') showLanding();
        else if(target==='request'){
          showLanding();
          setTimeout(function(){const request=document.getElementById('request');if(request)request.scrollIntoView({behavior:'smooth',block:'start'});},50);
        } else showPage(target);
        if(history.replaceState) history.replaceState(null,'','#'+target);
      });
    });
    if(location.hash && location.hash!=='#top' && location.hash!=='#request'){
      const target=location.hash.slice(1);
      if(document.getElementById(target)) showPage(target);
    }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',initTWPageNavigation);
  else initTWPageNavigation();
})();
</script>

<script>
/* Independent Academy fallback: keep lesson navigation working even if another
   dashboard script fails to initialise. */
(function(){
  function initAcademyFallback(){
    const academy=document.getElementById("academy");
    const courseModal=document.getElementById("twAcademyModal");
    const detailModal=document.getElementById("twLessonDetailModal");
    const title=document.getElementById("twAcademyTitle");
    const description=document.getElementById("twAcademyDescription");
    const lessonsBox=document.getElementById("twAcademyLessons");
    const detailTitle=document.getElementById("twLessonDetailTitle");
    const detailBody=document.getElementById("twLessonDetailBody");
    if(!academy || !courseModal || !detailModal || !lessonsBox) return;
    if(academy.dataset.fallbackReady==="1") return;
    academy.dataset.fallbackReady="1";
    function close(modal){ if(modal) modal.classList.remove("open"); }
    function openCourse(card){
      const h=card.querySelector("h3");
      const p=card.querySelector(".muted");
      if(title) title.textContent=h ? h.textContent.trim() : "TW Trades course";
      if(description) description.textContent=p ? p.textContent.trim() : "Study each lesson and complete the practice task.";
      const items=Array.from(card.querySelectorAll(".lesson"));
      lessonsBox.innerHTML=items.length ? items.map(function(node,i){
        const lessonTitle=node.textContent.trim().replace(/^\\d+\\.\\s*/,"");
        return '<button type="button" class="tw-lesson" data-fallback-lesson="'+encodeURIComponent(lessonTitle)+'" style="display:block;width:100%;text-align:left;color:inherit;background:rgba(255,255,255,.035);border:1px solid rgba(0,255,208,.18);border-radius:12px;padding:16px;margin:10px 0;cursor:pointer;"><strong style="color:#00ffd0;">Lesson '+(i+1)+'</strong><div style="margin-top:6px;">'+escapeHtml(lessonTitle)+'</div><small style="display:block;margin-top:8px;color:#9aabba;">TAP TO OPEN LESSON →</small></button>';
      }).join("") : '<p>No lessons are listed in this course yet.</p>';
      courseModal.classList.add("open");
    }
    function escapeHtml(v){return String(v).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
    function openLesson(lesson){
      if(detailTitle) detailTitle.textContent=lesson;
      if(detailBody) detailBody.innerHTML='<div class="tw-lesson-detail"><h3>Lesson overview</h3><p><strong>Objective:</strong> Understand '+escapeHtml(lesson.toLowerCase())+' and apply it consistently as part of a documented trading plan.</p><h3>How to study it</h3><p>Review the relevant chart examples, identify the market context, write down the evidence supporting your interpretation, and note what would invalidate it. Separate observations from assumptions.</p><h3>Practice exercise</h3><p>Open a demo chart and find at least three historical examples. Record the instrument, timeframe, conditions, entry trigger (if any), invalidation level, and outcome. Include examples where the setup did not work.</p><div class="tw-lesson-exercise"><strong>Before moving on</strong><p>Can you explain the concept in your own words and identify when not to trade it? If not, repeat the exercise.</p></div><p style="color:#9aabba;font-size:12px;">Educational content only. No setup guarantees profit. Practice on a demo account before risking money.</p></div>';
      close(courseModal);
      detailModal.classList.add("open");
    }
    academy.querySelectorAll(".card.course").forEach(function(card){
      card.style.cursor="pointer";
      card.setAttribute("role","button");
      card.setAttribute("tabindex","0");
      card.addEventListener("click",function(){openCourse(card);});
      card.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();openCourse(card);}});
    });
    lessonsBox.addEventListener("click",function(e){
      const btn=e.target.closest("[data-fallback-lesson]");
      if(!btn) return;
      let lesson=btn.getAttribute("data-fallback-lesson")||"";
      try{lesson=decodeURIComponent(lesson);}catch(_){}
      openLesson(lesson);
    });
    document.getElementById("twAcademyClose")?.addEventListener("click",function(){close(courseModal);});
    document.getElementById("twLessonDetailClose")?.addEventListener("click",function(){close(detailModal);});
    [courseModal,detailModal].forEach(function(modal){modal.addEventListener("click",function(e){if(e.target===modal) close(modal);});});
  }
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",initAcademyFallback);
  else initAcademyFallback();
})();
</script>

</body>
</html>


"""


@app.route("/access", methods=["GET", "POST"])
def user_access():
    import html
    message = ""
    if request.method == "POST":
        action = request.form.get("action", "login")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("display_name", "").strip()
        c = db()
        if action == "register":
            if not name or "@" not in email or len(password) < 8:
                message = "Enter your name, a valid email, and a password of at least 8 characters."
            else:
                try:
                    c.execute("INSERT INTO users(email,password_hash,display_name,access_level,access_status,created_at) VALUES(?,?,?,'free','active',?)",
                        (email, _hash_password(password), name, datetime.now(timezone.utc).isoformat()))
                    c.commit()
                except sqlite3.IntegrityError:
                    message = "That email is already registered. Please log in."
        if not message and action == "login":
            user = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user and _verify_password(password, user["password_hash"]):
                # Upgrade a legacy SHA-256 hash on the owner's next login.
                if _needs_rehash(user["password_hash"]):
                    c.execute("UPDATE users SET password_hash=? WHERE id=?",
                              (_hash_password(password), user["id"]))
                    c.commit()
                session.clear()
                session["user_id"] = user["id"]
                session["user_email"] = user["email"]
                session["user_name"] = user["display_name"]
                c.close()
                return redirect("/access")
            message = "Email or password is incorrect."
        if not message and action == "register":
            user = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user:
                session["user_id"] = user["id"]
                session["user_email"] = user["email"]
                session["user_name"] = user["display_name"]
                c.close()
                return redirect("/access")
        c.close()
    if session.get("user_id"):
        name = html.escape(session.get("user_name", "Trader"))
        email = html.escape(session.get("user_email", ""))
        return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>TW Trades Free Access</title><style>body{margin:0;padding:24px;background:#05070b;color:#edf3fb;font-family:Arial}.box{max-width:700px;margin:8vh auto;padding:28px;background:#0b1119;border:1px solid #203348;border-radius:20px}p{color:#aab7c8;line-height:1.7}.btn{display:inline-block;padding:14px 18px;margin:6px;border-radius:10px;background:#00ffd0;color:#03100e;font-weight:bold;text-decoration:none}.alt{background:#101925;color:white;border:1px solid #334155}</style></head><body><main class="box"><p style="color:#00ffd0;font-weight:bold">TW TRADES · FREE MEMBER AREA</p><h1>Welcome, """ + name + """</h1><p>Your TW Trades account is active. Your name and email are saved in the app account database. WhatsApp access requests are temporarily disabled while we set up the member experience.</p><h2>Member account</h2><p>You are signed in with your registered email. Keep your password private.</p><a class="btn alt" href="/">OPEN MAIN WEBSITE</a><a class="btn alt" href="/access/logout">LOG OUT</a></main></body></html>"""
    safe_message = html.escape(message)
    return """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>TW Trades Login / Register</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;background:#05070b;color:#edf3fb;font-family:Arial}.box{width:100%;max-width:440px;padding:28px;border:1px solid #203348;border-radius:20px;background:#0b1119}p{color:#aab7c8;line-height:1.6}label{display:block;margin:12px 0 6px}input{width:100%;padding:13px;background:#05070b;color:white;border:1px solid #29384b;border-radius:9px}.btn{width:100%;padding:14px;margin-top:16px;background:#00ffd0;color:#03100e;font-weight:bold;border:0;border-radius:10px}.links a{color:#00ffd0;margin-right:16px}.err{color:#ffb7c1;margin:12px 0}</style></head><body><main class="box"><p style="color:#00ffd0;font-weight:bold;letter-spacing:2px">TW TRADES</p><h1>Login / Register</h1><p>Create an account to save your name and email in TW Trades, then log in with the same email and password whenever you return.</p><div class="links"><a href="/access">LOGIN</a><a href="/access?mode=register">REGISTER</a></div><div class="err">""" + safe_message + """</div><form method="post"><label>Name (registration only)</label><input name="display_name" autocomplete="name"><label>Email</label><input name="email" type="email" autocomplete="email" required><label>Password (8+ characters for registration)</label><input name="password" type="password" minlength="8" autocomplete="current-password" required><div style="display:flex;gap:8px"><button class="btn" name="action" value="login">LOG IN</button><button class="btn" name="action" value="register">REGISTER FREE</button></div></form><p><a style="color:#00ffd0" href="/">← Back to landing page</a></p></main></body></html>"""

@app.route("/access/logout")
def user_access_logout():
    for key in ("user_id", "user_email", "user_name"):
        session.pop(key, None)
    return redirect("/access")


@app.route("/")
def home():
    return render_template_string(
        PAGE,
        courses=COURSES
    )

@app.route("/api/db/status")
def api_db_status():
    """Read-only database diagnostics for the owner. No credentials are exposed."""
    if not session.get("admin"):
        return jsonify({"error": "Admin session required."}), 401
    tables = {}
    try:
        c = db()
        for name in ("settings", "signals", "users"):
            try:
                tables[name] = c.execute("SELECT COUNT(*) n FROM " + name).fetchone()["n"]
            except sqlite3.DatabaseError:
                tables[name] = "missing"
        schema_version = None
        try:
            row = c.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
            schema_version = row["value"] if row else None
        except sqlite3.DatabaseError:
            pass
        c.close()
    except sqlite3.DatabaseError as exc:
        return jsonify({"error": "Database unreadable.", "detail": str(exc)}), 500

    return jsonify({
        "path": DB,
        "path_is_absolute": os.path.isabs(DB),
        "path_override_env": next((k for k in ("TW_DATABASE_PATH", "DATABASE_PATH", "DB_PATH")
                                   if os.environ.get(k, "").strip()), None),
        "exists": os.path.exists(DB),
        "size_bytes": os.path.getsize(DB) if os.path.exists(DB) else 0,
        "schema_version": schema_version,
        "tables": tables,
        "password_hashes": password_hash_audit(),
    })


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


