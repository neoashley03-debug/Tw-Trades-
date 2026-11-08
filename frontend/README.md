# TW Trades frontend

This directory is reserved for the Lovable-generated React + TypeScript frontend.

Important:
- Keep the Flask backend and its current deployment files at the repository root.
- Do not move or overwrite root-level `app.py`, `requirements.txt`, `Procfile`, the SQLite database, or existing application assets.
- Configure the frontend with `VITE_TW_API_BASE_URL=https://tw-trades-1.onrender.com`.
- Never put provider API keys or backend secrets in `VITE_*` variables.
- Follow [the Lovable build specification](../docs/LOVABLE_BUILD_SPEC.md) and [integration roadmap](../docs/LOVABLE_INTEGRATION_ROADMAP.md).
- If Lovable GitHub sync cannot target this directory safely, stop rather than overwriting the Flask application.
