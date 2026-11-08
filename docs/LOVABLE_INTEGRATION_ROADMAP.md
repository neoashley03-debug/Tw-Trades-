# TW Trades — Lovable / Flask Integration Roadmap

## Current verified baseline

Repository: `neoashley03-debug/Tw-Trades-`  
Production backend: `https://tw-trades-1.onrender.com/`  
Backend runtime: Flask + SQLite (`tw_blueprint.db`)  
Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`  
Current dependency file: root `requirements.txt`.

The existing Flask app already contains a market universe, market-data status, scanner, news, AI, blueprint, signal-commit, admin/access, and health functionality. Preserve these routes and existing behavior. The currently configured CORS allowlist contains the old Netlify origins; the Lovable production origin must be added deliberately before browser requests from Lovable will work.

This document is a plan, not a claim that all listed integrations or endpoints are already implemented.

## Phase 0 — Protect the production application

1. Keep the existing `main` branch and Render deployment unchanged.
2. Work on the dedicated `lovable-integration` branch.
3. Build the React frontend under `/frontend`; do not replace the root Flask app.
4. Review any generated changes before merging to main.
5. Verify the existing root app still starts and its current health/API checks pass.

## Phase 1 — Lovable frontend

1. Create/import the Lovable project using the repository and integration branch.
2. Keep generated frontend code under `/frontend`.
3. Set `VITE_TW_API_BASE_URL=https://tw-trades-1.onrender.com` in the Lovable frontend environment.
4. Implement the app shell, navigation, responsive dashboard, chart workspace, scanner views, signal detail, intelligence panels, journal, and settings.
5. Use typed API adapters. Do not invent a successful response when a backend endpoint is absent.
6. Verify the generated project build and mobile layout before connecting it to production.

If Lovable's GitHub sync insists on writing at repository root, stop and use a separate frontend repository or a carefully controlled export. Do not allow it to overwrite the Flask project.

## Phase 2 — Backend API contract and frontend connectivity

Inventory the actual Flask routes and authentication model before changing them. Keep current endpoints backward compatible.

Existing route families to preserve include:
- `GET /health`
- `GET /api/market-data/status`
- `GET /api/market-data/universe-status`
- `GET /api/scan`
- `GET /api/news`
- `GET /api/ai`
- `GET /api/blueprint`
- `POST /api/commit`

Confirm exact methods, query parameters, payloads, response shapes, and authentication requirements from the current source before wiring the frontend. The list above is a route inventory to verify, not a substitute for API schema inspection.

Required backend integration work:
- Add the Lovable production origin to the explicit CORS allowlist (prefer a server-side `FRONTEND_ORIGINS` environment variable). Allow only required methods and headers.
- Add a versioned API namespace for new capabilities rather than breaking existing endpoints.
- Add authenticated journal CRUD, trade attachments, analytics, and export routes.
- Add a unified market-data adapter interface with per-provider health, timestamps, symbol mapping, rate-limit state, and entitlement state.
- Add a scanner response schema that carries evidence, failed checks, source provenance, stale-data flags, and algorithm version.
- Add server-side request validation, rate limiting, audit logging, and user-level authorization.
- Add database migrations and backups before changing persistent schema. Do not rely on ephemeral local disk for production SQLite durability; verify Render persistent disk configuration or migrate to managed PostgreSQL before multi-user production usage.

## Phase 3 — Real data integrations

Provider integrations must be server-side adapters and must be enabled only after credentials, entitlements, licensing, and symbol coverage are verified.

| Domain | Candidate sources | Important limitation |
|---|---|---|
| FX / metals / crypto price history | Twelve Data, broker feed, exchange APIs | Coverage, delay, granularity, and redistribution rights vary by plan and instrument. |
| Execution-grade quotes | User's broker API / authorized broker feed | Broker-specific; do not call a generic data feed executable pricing. |
| Indices | Licensed index/futures data provider | Index cash symbols and futures contracts are not interchangeable. |
| Synthetic indices | Authorized Deriv API / broker stream | Do not map synthetic indices to unrelated symbols or estimate missing prices. |
| Macro releases | Official central-bank/statistical sources; licensed economic calendar | Consensus estimates may require a paid provider. |
| CFTC positioning | CFTC COT reports | Weekly, delayed, futures/options categories; not real-time spot FX positioning. |
| Futures volume / open interest | CME or other exchange-licensed data | Exchange entitlements and redistribution restrictions apply. |
| Financial news | MarketAux or licensed news provider | Sentiment methodology and news rights must be reviewed. |
| Retail positioning | Myfxbook or another authorized positioning API | Retail sample is not the entire market and may be delayed. |

Every adapter must return source name, source timestamp, retrieval timestamp, instrument mapping, units, delay/entitlement notes, and explicit errors. The scanner must fail closed when critical data is stale or unavailable.

## Phase 4 — Internal signal engine

1. Define versioned rules per asset class and trading style.
2. Implement the user's ICC framework consistently: pre-ICC range, indication, correction, continuation; body-based break rules; explicit invalidation.
3. Add multi-timeframe structure, ATR/volatility regime, levels, liquidity-sweep candidates, FVG/order-block candidates, and volume only when a valid volume source exists.
4. Add macro-event and sentiment filters with explicit data provenance.
5. Add institutional context only from datasets actually available (for example delayed CFTC positioning and licensed futures data).
6. Calculate confluence scores as scores, not probabilities. Only display probability after calibration on sufficient out-of-sample data.
7. Require spread, stale-feed, timestamp, and risk checks before publishing a signal.
8. Store every candidate, published signal, invalidation, and outcome to enable audit and performance reporting.

Trading styles:
- Ultra-scalp: 1m / 3m / 5m
- Scalp: 5m / 15m
- Day: 15m / 1h / 4h
- Swing: 4h / 1D
- Position: 1D / 1W

## Phase 5 — Research and proof

- Build a reproducible backtest harness with realistic transaction costs.
- Use chronological train / validation / test splits and walk-forward evaluation.
- Prevent look-ahead, repainting, data leakage, and survivorship bias.
- Track strategy version, market regime, source quality, signal timestamp, entry assumptions, and realized outcome.
- Publish sample size, win rate, expectancy, profit factor, drawdown, and uncertainty for each style and market.
- Run paper trading before enabling any live signal distribution.
- Do not promise a fixed accuracy level or guaranteed returns.

## Phase 6 — Release gates

Do not merge or deploy until:
- Existing Flask health check and old application features still work.
- Lovable frontend builds successfully and is responsive on Android and desktop.
- Browser-to-Render CORS works only for approved origins.
- No provider secrets are present in frontend bundles or Git history.
- All unavailable feeds are visibly marked unavailable.
- Scanner has tests for stale data, bad candles, missing inputs, conflicting evidence, and no-trade outcomes.
- Journal authorization, data isolation, backups, and export are tested.
- Backtest results are independently reproducible and clearly separated from live/paper results.

## Operational note

Lovable is the frontend builder. Render remains the backend host. GitHub remains the source of truth. A Lovable project connection does not itself create provider subscriptions, API credentials, exchange licenses, broker access, or verified signal performance.
