# BondStats Daily Signal Brief

**What changed. What the bond market is pricing. What matters next.**

An original, deterministic daily market brief built from BondStats-owned structured market data and factual official-source feeds. It deliberately does **not** ingest, scrape, copy, summarize or rewrite third-party financial news.

## Product architecture

- `index.html` — distinctive Signal Desk / Halo UI
- `archive.html` — daily archive index
- `brief.html?date=YYYY-MM-DD` — archived daily snapshot reader
- `health.html` — source health
- `data/latest.json` — current brief
- `data/archive/YYYY-MM-DD.json` — immutable daily snapshots
- `data/archive.json` — archive manifest
- `scripts/update_brief.py` — deterministic signal engine
- `.github/workflows/update-daily-brief.yml` — daily + manual GitHub Action
- `tests/test_brief.py` — integrity tests

## Data sources

The updater consumes the public BondStats Macro Data Watch, Central Bank Watch, Market Calendar and Global Yields feeds. Macro/policy/calendar products themselves use official primary sources. No editorial-news provider is consumed.

## Copyright / reuse posture

BondStats owns the original UI, selection/structure, deterministic rules and original generated wording in this repository. Underlying factual observations remain attributable to their source. The product avoids third-party article text, headlines, screenshots, logos and editorial graphics. This architecture materially reduces copyright/licensing exposure, but it is not a legal guarantee; source terms should continue to be reviewed as integrations evolve.

© 2026 BondStats Ltd. All rights reserved.
