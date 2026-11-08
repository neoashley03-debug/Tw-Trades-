# TW Trades — Lovable Frontend Build Specification

## Product decision

Build the new responsive TW Trades web application with Lovable. Keep the existing Flask application as the system of record and intelligence API on Render. The Lovable app is a separate frontend; it must not replace, rename, or overwrite the existing Flask backend, SQLite database, API integrations, Titan X/Yuki features, Academy, access controls, or current production deployment.

**Selected scope**
- Coverage: all supported market classes from the start.
- Delivery: responsive web application designed for Android/mobile and desktop.
- Signal generation: TW Trades internal signal engine only. Do not import or copy third-party buy/sell calls.
- Existing backend: Flask on Render at `https://tw-trades-1.onrender.com`.
- Existing repository: `neoashley03-debug/Tw-Trades-`.
- Integration branch: `lovable-integration`.

## Frontend architecture

Create a React + TypeScript + Vite application under `/frontend` in this repository. Use Tailwind CSS and accessible shadcn/ui components. Keep all frontend-specific files in `/frontend`; do not move or rewrite root-level Flask files.

Recommended frontend packages:
- Lightweight Charts for interactive candlestick charts. Use only licensed/approved chart libraries and comply with their attribution terms.
- TanStack Query for API state, caching, retries, and stale-data handling.
- Zod for runtime validation of API responses and user inputs.
- React Hook Form for trade journal and settings forms.
- A small, typed API client with the Render backend URL configured through `VITE_TW_API_BASE_URL`.

Do not expose provider API keys in browser code. Provider credentials belong only in Render environment variables or another trusted server-side secret store.

## Main navigation

1. Overview
2. Live Charts
3. AI Scanner
4. Signals
5. Market Intelligence
6. Economic Calendar
7. Titan X
8. Trade Journal AI
9. Performance & Backtesting
10. Academy / TW Blueprint
11. Settings

Preserve existing feature names and behavior where possible. Add new navigation without removing or hiding existing working modules.

## Market universe

Show the following asset classes, but distinguish configured instruments from instruments with a verified live feed:

- Forex: major, minor, and configured cross pairs.
- Metals: XAU/USD and XAG/USD when a valid feed is configured.
- Indices: supported cash/index symbols and futures proxies where the data contract permits.
- Crypto: supported spot pairs.
- Synthetic indices: Deriv-style symbols only when an authorized, compatible provider or broker feed is connected. Never substitute an unrelated symbol or infer a synthetic price from a different market.

Every instrument must expose its canonical symbol, provider symbol mapping, asset class, provider, exchange/venue where relevant, quote currency, timestamp, and feed health.

## Trading-style scanner categories

- Ultra-scalp: 1m / 3m / 5m
- Scalping: 5m / 15m
- Day trading: 15m / 1h / 4h
- Swing trading: 4h / 1D
- Position trading: 1D / 1W

Timeframes are strategy defaults, not guarantees of signal frequency. Users can inspect the exact timeframes and conditions used for each result.

## Chart and technical analysis requirements

- Candles must come from a real, timestamped OHLCV feed. Show provider, venue, last update, and stale-data state.
- Support timeframe switching, crosshair, zoom, pan, volume, indicator overlays, drawing tools where feasible, and synchronized symbol selection.
- Calculate indicators server-side or in a tested shared analysis package so the chart and scanner cannot silently disagree.
- Technical features: market structure, body-based BOS/CHOCH, trend/range regime, support/resistance, ATR, volatility, RSI, moving averages, volume (only when source provides it), liquidity sweep candidates, fair value gap candidates, and order-block candidates.
- ICC framework: distinguish pre-ICC/range, indication, correction, continuation. A setup is not valid merely because one candle breaks a level. Use candle-body rules consistently and document the rule.
- Mark inferred concepts such as order blocks, liquidity pools, and FVGs as algorithmic detections, not verified institutional orders.

## Intelligence engines

### Technical
Multi-timeframe structure, candle patterns, ATR/volatility, levels, trend/range state, and ICC state.

### Fundamental
Official macro releases, central-bank decisions and statements, inflation, employment, rates, bond yields, and relevant scheduled events. Record event time, source, actual/consensus/previous values where licensed, and revision status. Do not fabricate consensus.

### Institutional
CFTC Commitments of Traders (weekly and delayed), CME futures volume/open interest where licensed, and broker-provided order-book/depth data only when actually available. Clearly show reporting lag and venue coverage. Do not claim to see bank orders or global institutional flow from retail FX candles.

### Sentiment
Timestamped financial-news sentiment, clearly attributed retail positioning, and other licensed positioning datasets. Sentiment is contextual evidence, not a standalone trade trigger. Do not label a news headline as market-wide sentiment without aggregation and methodology.

### Quantitative / algorithms
Deterministic, versioned features; regime detection; confluence scoring; historical event studies; walk-forward testing; probability calibration; and drift monitoring. Never present an uncalibrated confluence score as a probability of profit.

## Signal card contract

Each internally generated signal must include:
- Unique signal ID, symbol, asset class, trading style, timeframe, direction.
- Status: WATCH / QUALIFIED / ACTIVE / INVALIDATED / EXPIRED / CLOSED.
- Created-at and last-validated timestamps in UTC plus displayed local timezone.
- Entry zone, invalidation/stop level, targets, spread/slippage assumptions, and risk-to-reward.
- ICC phase and exact setup rules passed/failed.
- Technical, fundamental, institutional, sentiment, and quantitative evidence, with unavailable dimensions explicitly marked unavailable.
- Source/provider IDs, source timestamps, and feed-health state.
- Risk warning and rationale; never auto-execute a trade.
- Outcome tracking for honest performance reporting.

No signal may be published if required price data is missing, stale, inconsistent, or outside configured spread/volatility limits. "No trade" is a valid scanner outcome.

## Accuracy, validation, and performance reporting

- No claim of perfect or guaranteed accuracy.
- Report strategy-specific sample size, win rate, expectancy in R, profit factor, max drawdown, average adverse/favourable excursion where measurable, and date range.
- Separate in-sample, validation, and untouched out-of-sample results.
- Use walk-forward testing and realistic spread, commission, swap/funding, slippage, latency, and execution assumptions.
- Prevent look-ahead bias, survivorship bias, duplicate signals, and candle-repainting.
- Never tune thresholds against the final test set.
- Show confidence intervals and warn when sample size is too small.
- Distinguish backtest, paper-trading, and live tracked results.

## Trade journal

Build an Android-friendly trade form with symbol, style, session, direction, entry, stop, targets, lot/quantity, account balance, risk %, fees, result, R-multiple, ICC notes, rule adherence, screenshot attachment, and lessons. Store records through authenticated backend endpoints. Provide filters, calendar, statistics, CSV export, and a WhatsApp share action that opens a prefilled message. Do not claim automatic WhatsApp delivery unless an approved WhatsApp Business API integration is configured.

## UX requirements

- Professional dark institutional terminal, restrained accent colors, clear typography, dense desktop layout and touch-friendly mobile layout.
- Responsive from 360px width upwards.
- Fast initial load; lazy-load chart and analytics modules.
- Clear loading, empty, error, stale-feed, and disconnected-provider states.
- No fake tickers, placeholder candles, fabricated order flow, fake signal cards, or sample P&L presented as live.
- Every data tile must show its source and timestamp or clearly say "not configured / unavailable".
- Include keyboard accessibility, semantic labels, and visible focus states.

## Security and privacy

- Never put API keys in Lovable frontend code, VITE variables, browser storage, or Git.
- Use HTTPS for all API requests.
- Authenticate private journal, account, and admin operations.
- Enforce authorization on the Flask backend; hiding a frontend button is not access control.
- Validate and rate-limit writes and expensive scanner requests.
- Do not expose admin endpoints or secrets to public frontend routes.
- Keep secrets in Render environment variables and rotate any key accidentally committed to Git.

## Lovable handoff prompt

Build the TW Trades frontend described in this document in the `/frontend` directory only. First inspect the existing repository and preserve the Flask backend at the root. Do not modify `app.py`, the existing database, deployment files, or working application pages unless an explicitly documented integration task requires a separate reviewed backend change. Use a typed API client that calls the existing Render backend. Do not create mock market prices, simulated signals, fake performance metrics, or hardcoded provider responses. If an endpoint or provider is not available, show a clear unavailable state and list the backend integration needed. Make the UI responsive for Android and desktop. Keep all secrets server-side.
