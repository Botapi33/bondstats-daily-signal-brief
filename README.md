# BondStats Daily Signal Brief — Production V2

**What changed. What the bond market is pricing. What matters next.**

A deterministic, news-free daily market-intelligence product for BondStats. It combines structured sovereign-yield data, Macro Data Watch, Central Bank Watch and Market Calendar data into an original daily signal layer with an immutable archive.

## Product layers

- **Signal Halo** — daily state + 0–100 signal intensity.
- **The One Thing** — one prioritized observation rather than a list of headlines.
- **Signal Stack** — Rates / Macro / Policy / Event Risk / Divergence.
- **Signals Before the Headlines** — verified changes ranked by strength and archive rarity.
- **Where the Market Stops Rhyming** — cross-signal dislocations without fabricated causality.
- **Rates Tape** — fresh daily, non-fallback sovereign moves only.
- **Signal Memory** — state streaks, recurrence and historical move percentiles.
- **What Matters Next** — high-information scheduled events and policy decisions.
- **Source Integrity** — live/degraded/unavailable status is visible.
- **Immutable Daily Archive** — the first successful snapshot for a date is never silently rewritten.

## Files

- `index.html` — full Daily Signal Brief
- `widget.html` — homepage teaser
- `archive.html` — archive index
- `brief.html?date=YYYY-MM-DD` — historical brief view
- `methodology.html` — data, signal and originality methodology
- `health.html` — source health
- `scripts/update_brief.py` — deterministic daily engine
- `tests/test_brief.py` — production integrity checks
- `.github/workflows/update-daily-brief.yml` — daily + manual GitHub Action
- `workflow-files/update-daily-brief.yml` — visible duplicate for users whose file upload hides `.github`

## Automation

The workflow runs once per day at `06:37 UTC` and can also be started manually with **Run workflow**.

Pipeline:

1. Fetch current structured upstream feeds.
2. Fall back visibly to last-known-good snapshots when necessary.
3. Build market state, signal stack, dislocations and signal memory.
4. Write `data/latest.json`.
5. Create the date's archive snapshot only if one does not already exist.
6. Run deterministic tests.
7. Commit changed data.

## Originality / copyright architecture

The engine intentionally does **not** ingest, scrape, copy, summarize or rewrite third-party financial-news articles, headlines, screenshots or editorial text. It uses structured facts, official-source observations and BondStats data feeds. Narrative output is deterministic and BondStats-authored in structure and presentation.

This architecture is designed to reduce exposure to third-party editorial copyright. It is not a blanket legal claim that every underlying fact or dataset is “copyright free”; provider terms and data rights still apply.

## GitHub upload warning

On macOS, `.github` can be hidden. If the workflow does not appear in GitHub Actions, create this path directly in GitHub:

`.github/workflows/update-daily-brief.yml`

and paste the identical content from:

`workflow-files/update-daily-brief.yml`

## License

No open-source license is granted. © 2026 BondStats Ltd. All rights reserved.
