# Repository development guide

Read README.md and market-digest/AGENTS.md before changes. Preserve the existing root ETF database, reports, fixtures, CLI and tests. The new digest is independent in market-digest/; do not silently replace the original implementation.

Run both suites, in separate working directories:

- Root: python -m unittest -v; python -m py_compile etf_db.py flow_quality.py
- market-digest/: python -m unittest discover -s tests -v; python -m py_compile digest.py sources.py

Defaults must remain dry run. Do not commit secrets, real Feishu webhook URLs, private X exports, generated reports, virtual environments or caches. Do not activate scheduling, real messaging, new credentials or production deployment without the applicable user authorization and verification.

Actual scope: ETF parsing, bounded RSS/Atom excerpts, explicitly supplied authorized X export import, configured official-announcement evidence, optional Feishu sender. X automatic monitoring, exchange activity discovery, comprehensive US/crypto news, signed Feishu delivery and verified end-to-end operation are NOT implemented/verified. Preserve these limitations in documentation and status reports. Offline tests do not prove live sources work.


Unified maintenance entrypoint: `python scripts/check.py` runs both suites and compilation from the correct directories and fails if required test dependencies are absent. `python scripts/offline_demo.py` is a standard-library-only historical fixture preview; keep it network-free and clearly labeled as historical. Read docs/OPERATIONS.md and docs/CONTRIBUTING.md when changing operational behavior. Documentation must distinguish dry-run (network reads, no sends) from offline (no network).
