#!/usr/bin/env python3
"""BondStats Daily Signal Brief v2.

A deterministic, news-free daily market-intelligence generator.
It consumes structured BondStats/official-source feeds, detects verified changes,
builds a daily signal state, and writes an immutable dated archive snapshot.

Design constraints:
- No third-party news articles, headlines or editorial prose are ingested.
- No causal story is invented from coincident market moves.
- Daily yield claims require fresh, daily, non-fallback observations.
- Upstream failures degrade gracefully to last-known-good snapshots.
- Every archive date is immutable once written.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import time
import urllib.request
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARCHIVE = DATA / "archive"
SNAPSHOTS = DATA / "snapshots"

URLS = {
    "macro": "https://botapi33.github.io/bondstats-macro-data-watch/data/macro.json",
    "policy": "https://botapi33.github.io/bondstats-central-bank-watch/data/policy.json",
    "calendar": "https://botapi33.github.io/bondstats-market-calendar/data/events.json",
    "yields": "https://botapi33.github.io/bondstats-global-yields/global_yields.json",
}

PRODUCT = "BondStats Daily Signal Brief"
VERSION = "2.0.0"
USER_AGENT = "BondStats-Daily-Signal-Brief/2.0 (+https://www.bondstats.org/)"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_dt(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def number(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except Exception:
        return None


def read_json(path: pathlib.Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def write_json_atomic(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    tmp.replace(path)


def fetch_json(url: str, attempts: int = 3, timeout: int = 30) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url + ("&" if "?" in url else "?") + f"_={int(time.time())}",
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                return json.load(response)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(str(last_error) if last_error else "unknown fetch error")


def load_previous_briefs(limit: int = 120) -> list[dict]:
    rows: list[dict] = []
    if not ARCHIVE.exists():
        return rows
    for path in sorted(ARCHIVE.glob("*.json"), reverse=True):
        item = read_json(path)
        if item and item.get("meta", {}).get("version"):
            rows.append(item)
        if len(rows) >= limit:
            break
    return rows


def snapshot_path(name: str) -> pathlib.Path:
    return SNAPSHOTS / f"{name}.json"


def save_snapshot(name: str, payload: dict, checked_at: dt.datetime) -> None:
    wrapped = {
        "_bondstatsSnapshot": {
            "source": name,
            "savedAt": checked_at.isoformat().replace("+00:00", "Z"),
            "url": URLS[name],
        },
        "payload": payload,
    }
    write_json_atomic(snapshot_path(name), wrapped)


def load_snapshot(name: str) -> tuple[dict | None, str | None]:
    raw = read_json(snapshot_path(name))
    if not raw:
        return None, None
    if "payload" in raw and "_bondstatsSnapshot" in raw:
        return raw.get("payload"), raw.get("_bondstatsSnapshot", {}).get("savedAt")
    # v1 compatibility: raw snapshot was the payload itself.
    return raw, None


def load_sources(now: dt.datetime) -> tuple[dict[str, dict | None], dict[str, dict]]:
    sources: dict[str, dict | None] = {}
    health: dict[str, dict] = {}
    for name, url in URLS.items():
        try:
            payload = fetch_json(url)
            sources[name] = payload
            save_snapshot(name, payload, now)
            health[name] = {
                "status": "live",
                "checkedAt": now.isoformat().replace("+00:00", "Z"),
                "sourceUrl": url,
                "fallback": False,
            }
        except Exception as exc:
            payload, saved_at = load_snapshot(name)
            sources[name] = payload
            health[name] = {
                "status": "degraded" if payload else "unavailable",
                "checkedAt": now.isoformat().replace("+00:00", "Z"),
                "sourceUrl": url,
                "fallback": bool(payload),
                "snapshotSavedAt": saved_at,
                "errorClass": exc.__class__.__name__,
            }
    return sources, health


def market_rows(feed: dict | None) -> list[dict]:
    out: list[dict] = []
    if not feed:
        return out
    for key, row in (feed.get("countries") or {}).items():
        current = number(row.get("value"))
        previous = number(row.get("previousValue"))
        stale = number(row.get("stalenessDays"))
        frequency = str(row.get("frequency", "")).strip().lower()
        fresh_daily = (
            frequency == "daily"
            and not bool(row.get("isFallback"))
            and stale is not None
            and stale <= 7
            and current is not None
            and previous is not None
        )
        change_bp = (current - previous) * 100 if fresh_daily else None
        out.append(
            {
                "id": key,
                "label": row.get("label") or key,
                "yield": current,
                "previousYield": previous,
                "changeBp": round(change_bp, 1) if change_bp is not None else None,
                "date": row.get("date"),
                "previousDate": row.get("previousDate"),
                "frequency": row.get("frequency"),
                "stalenessDays": stale,
                "freshDaily": fresh_daily,
                "source": row.get("source"),
                "tier": row.get("tier"),
            }
        )
    return out


def macro_rows(feed: dict | None) -> list[dict]:
    if not feed:
        return []
    rows = []
    for item in feed.get("indicators", []):
        rows.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "label": item.get("label"),
                "region": item.get("region"),
                "group": item.get("group"),
                "value": number(item.get("value")),
                "previous": number(item.get("previous")),
                "unit": item.get("unit"),
                "transform": item.get("transform"),
                "period": item.get("period"),
                "frequency": item.get("frequency"),
                "direction": item.get("direction"),
                "relevance": item.get("marketRelevance"),
                "sourceName": item.get("sourceName"),
                "sourceUrl": item.get("sourceUrl"),
                "status": item.get("status"),
            }
        )
    return rows


def event_time(item: dict) -> dt.datetime | None:
    return iso_dt(item.get("timestamp") or item.get("dateTime") or item.get("datetime") or item.get("date"))


def upcoming_events(feed: dict | None, now: dt.datetime, days: int = 7) -> list[dict]:
    if not feed:
        return []
    events = []
    for item in feed.get("events", []):
        when = event_time(item)
        if not when or when < now or when > now + dt.timedelta(days=days):
            continue
        events.append((when, item))
    events.sort(key=lambda pair: pair[0])
    out = []
    for when, item in events[:12]:
        out.append(
            {
                "id": item.get("id"),
                "title": item.get("title") or item.get("name"),
                "dateTime": when.isoformat().replace("+00:00", "Z"),
                "timePrecision": item.get("timePrecision"),
                "impactScore": number(item.get("impactScore")),
                "impact": item.get("impactLabel") or item.get("impact") or "Scheduled",
                "category": item.get("category"),
                "primaryExposure": item.get("primaryExposure") or [],
                "sourceName": item.get("source") or item.get("sourceName"),
                "sourceUrl": item.get("sourceUrl"),
                "official": item.get("official"),
            }
        )
    return out


def next_policy(feed: dict | None, now: dt.datetime) -> list[dict]:
    if not feed:
        return []
    rows = []
    for bank in feed.get("banks", []):
        meeting = iso_dt(bank.get("nextMeeting"))
        if not meeting:
            # date-only values parse at midnight UTC, which is sufficient for ordering.
            try:
                meeting = dt.datetime.fromisoformat(str(bank.get("nextMeeting"))).replace(tzinfo=dt.timezone.utc)
            except Exception:
                continue
        if meeting < now - dt.timedelta(days=1):
            continue
        rows.append((meeting, bank))
    rows.sort(key=lambda pair: pair[0])
    return [
        {
            "id": bank.get("id"),
            "bank": bank.get("name"),
            "date": when.date().isoformat(),
            "displayRate": bank.get("displayRate"),
            "decision": bank.get("decision"),
            "decisionDate": bank.get("decisionDate"),
            "changeBp": number(bank.get("changeBp")),
            "stance": bank.get("stance"),
            "direction": bank.get("direction"),
            "sourceName": bank.get("sourceName"),
            "sourceUrl": bank.get("sourceUrl"),
            "scheduleUrl": bank.get("scheduleUrl"),
        }
        for when, bank in rows[:7]
    ]


def macro_impulse(rows: list[dict]) -> tuple[str, int, dict]:
    """Return descriptive macro direction; deliberately not a causal market forecast."""
    cooling = heating = unchanged = 0
    evidence = []
    for row in rows:
        value, previous = row.get("value"), row.get("previous")
        if value is None or previous is None or value == previous:
            unchanged += 1
            continue
        group = str(row.get("group") or "").lower()
        name = str(row.get("name") or "").lower()
        delta = value - previous
        # Direction semantics are domain-specific and intentionally simple/transparent.
        cool = False
        heat = False
        if "inflation" in group or "cpi" in name or "pce" in name or "hicp" in name:
            cool, heat = delta < 0, delta > 0
        elif "unemployment" in name:
            cool, heat = delta > 0, delta < 0
        elif "payroll" in name or "gdp" in name or "growth" in group or "labour" in group:
            cool, heat = delta < 0, delta > 0
        if cool:
            cooling += 1
            evidence.append(row.get("id"))
        elif heat:
            heating += 1
            evidence.append(row.get("id"))
    total = cooling + heating
    score = round(100 * (heating - cooling) / total) if total else 0
    if total == 0:
        label = "Stable"
    elif cooling >= heating * 2 and cooling >= 2:
        label = "Cooling"
    elif heating >= cooling * 2 and heating >= 2:
        label = "Firming"
    else:
        label = "Mixed"
    return label, score, {"cooling": cooling, "heating": heating, "unchanged": unchanged, "evidence": evidence}


def rates_state(markets: list[dict]) -> tuple[str, int, dict]:
    fresh = [m for m in markets if m.get("changeBp") is not None]
    if not fresh:
        return "Awaiting", 0, {"fresh": 0, "rising": 0, "falling": 0, "averageBp": None, "breadth": 0}
    rising = sum(m["changeBp"] > 0 for m in fresh)
    falling = sum(m["changeBp"] < 0 for m in fresh)
    average = sum(m["changeBp"] for m in fresh) / len(fresh)
    breadth = (rising - falling) / len(fresh)
    directional = max(-100, min(100, round(average * 6 + breadth * 40)))
    if falling >= max(3, rising * 2):
        label = "Lower"
    elif rising >= max(3, falling * 2):
        label = "Higher"
    else:
        label = "Mixed"
    return label, directional, {"fresh": len(fresh), "rising": rising, "falling": falling, "averageBp": round(average, 1), "breadth": round(breadth, 2)}


def policy_state(feed: dict | None) -> tuple[str, dict]:
    banks = (feed or {}).get("banks", [])
    stances = [str(b.get("stance") or "").lower() for b in banks]
    restrictive = sum("restrict" in x for x in stances)
    accommodative = sum(("accommod" in x or "easy" in x) for x in stances)
    recent_moves = [number(b.get("changeBp")) for b in banks]
    recent_moves = [x for x in recent_moves if x is not None]
    if restrictive >= max(3, accommodative * 2):
        label = "Mostly restrictive"
    elif accommodative >= max(3, restrictive * 2):
        label = "Mostly accommodative"
    else:
        label = "Mixed"
    return label, {"restrictive": restrictive, "accommodative": accommodative, "banks": len(banks), "netRecentBp": round(sum(recent_moves), 1) if recent_moves else 0}


def event_risk(events: list[dict], now: dt.datetime) -> tuple[str, int, dict]:
    if not events:
        return "Low", 15, {"nextCriticalHours": None, "critical72h": 0}
    critical_hours = []
    for event in events:
        when = iso_dt(event.get("dateTime"))
        score = number(event.get("impactScore")) or 0
        if when and score >= 90:
            critical_hours.append((when - now).total_seconds() / 3600)
    critical72 = sum(0 <= h <= 72 for h in critical_hours)
    if critical_hours:
        next_hours = min(h for h in critical_hours if h >= 0) if any(h >= 0 for h in critical_hours) else None
    else:
        next_hours = None
    if next_hours is not None and next_hours <= 24:
        return "Immediate", 95, {"nextCriticalHours": round(next_hours, 1), "critical72h": critical72}
    if critical72:
        return "Elevated", 80, {"nextCriticalHours": round(next_hours, 1) if next_hours is not None else None, "critical72h": critical72}
    return "Normal", 35, {"nextCriticalHours": round(next_hours, 1) if next_hours is not None else None, "critical72h": critical72}


def find_previous_value(previous: dict | None, section: str, item_id: str, key: str = "value") -> Any:
    if not previous:
        return None
    for row in previous.get(section, []):
        if row.get("id") == item_id:
            return row.get(key)
    return None


def history_move_stats(histories: list[dict], market_id: str, current_abs: float) -> dict:
    samples = []
    for brief in histories:
        for row in brief.get("markets", []):
            if row.get("id") == market_id and number(row.get("changeBp")) is not None:
                samples.append(abs(float(row["changeBp"])))
                break
    if not samples:
        return {"observations": 0, "percentile": None, "largestInObservations": False}
    percentile = round(100 * sum(x <= current_abs for x in samples) / len(samples))
    return {
        "observations": len(samples),
        "percentile": percentile,
        "largestInObservations": current_abs > max(samples),
    }


def build_signals(markets: list[dict], macro: list[dict], policy_feed: dict | None, previous: dict | None, histories: list[dict]) -> list[dict]:
    signals: list[dict] = []

    # Daily market moves — only fresh daily observations qualify.
    fresh = [m for m in markets if m.get("changeBp") is not None]
    fresh.sort(key=lambda row: abs(row["changeBp"]), reverse=True)
    for row in fresh[:5]:
        absolute = abs(row["changeBp"])
        memory = history_move_stats(histories, row["id"], absolute)
        percentile = memory.get("percentile")
        strength = min(98, round(38 + absolute * 4 + (10 if isinstance(percentile, (int, float)) and percentile >= 90 else 0)))
        direction = "rose" if row["changeBp"] > 0 else "fell"
        memory_text = None
        if memory["observations"] >= 5:
            if memory["largestInObservations"]:
                memory_text = f"Largest absolute move in the last {memory['observations'] + 1} archived observations."
            elif memory["percentile"] is not None:
                memory_text = f"Move ranks around the {memory['percentile']}th percentile of {memory['observations']} prior archived observations."
        signals.append(
            {
                "id": f"rates:{row['id']}",
                "kicker": "RATES",
                "headline": f"{row['label']} yield {direction} {absolute:.1f} bp",
                "body": "A verified fresh daily sovereign-yield move. BondStats reports the observed change without assigning a news-driven cause.",
                "strength": strength,
                "novelty": memory.get("percentile"),
                "memory": memory_text,
                "sourceName": row.get("source"),
                "sourceUrl": None,
            }
        )

    # Macro only becomes a new signal when the upstream value changed versus the prior archived brief.
    for row in macro:
        current = row.get("value")
        prior_archived = find_previous_value(previous, "macro", row.get("id"), "value")
        if current is None or prior_archived is None or current == prior_archived:
            continue
        previous_observation = row.get("previous")
        if previous_observation is None:
            continue
        verb = "fell" if current < previous_observation else "rose"
        relevance = str(row.get("relevance") or "").lower()
        strength = 82 if relevance == "critical" else 70 if relevance == "high" else 58
        signals.append(
            {
                "id": f"macro:{row['id']}",
                "kicker": str(row.get("group") or "MACRO").upper(),
                "headline": f"New {row['region']} {row['name']} observation",
                "body": f"{row['name']} {verb} to {current:g}{row.get('unit') or ''} from {previous_observation:g}{row.get('unit') or ''} ({row.get('period')}).",
                "strength": strength,
                "novelty": 100,
                "memory": "New official observation versus the previous archived Daily Signal Brief.",
                "sourceName": row.get("sourceName"),
                "sourceUrl": row.get("sourceUrl"),
            }
        )

    # Policy changes are new only if decision date/rate change differs from previous archived state.
    previous_policy = {p.get("id"): p for p in (previous or {}).get("policy", [])}
    for bank in (policy_feed or {}).get("banks", []):
        bank_id = bank.get("id")
        prev = previous_policy.get(bank_id, {})
        changed = bool(prev) and (
            bank.get("decisionDate") != prev.get("decisionDate")
            or bank.get("displayRate") != prev.get("displayRate")
        )
        if not changed:
            continue
        signals.append(
            {
                "id": f"policy:{bank_id}",
                "kicker": "POLICY",
                "headline": f"{bank.get('name')} policy setting updated",
                "body": f"Latest decision: {bank.get('decision') or 'updated'} · {bank.get('displayRate') or 'rate unavailable'} · decision date {bank.get('decisionDate') or 'n/a'}.",
                "strength": 90 if number(bank.get("changeBp")) not in (None, 0) else 78,
                "novelty": 100,
                "memory": "New central-bank decision versus the previous archived Daily Signal Brief.",
                "sourceName": bank.get("sourceName"),
                "sourceUrl": bank.get("sourceUrl"),
            }
        )

    signals.sort(key=lambda item: (item.get("strength") or 0, item.get("novelty") or 0), reverse=True)
    return signals[:8]


def build_dislocations(markets: list[dict], macro: list[dict], rates_label: str, macro_label: str) -> list[dict]:
    out: list[dict] = []
    us = next((m for m in markets if str(m.get("id", "")).lower() in {"usa", "us", "united states"}), None)
    inflation = next((m for m in macro if m.get("id") in {"US_CPI", "US_CORE_CPI"}), None)
    if us and us.get("changeBp") is not None and inflation and inflation.get("value") is not None and inflation.get("previous") is not None:
        inflation_delta = inflation["value"] - inflation["previous"]
        if us["changeBp"] < 0 and inflation_delta > 0:
            out.append({
                "id": "us-yields-down-inflation-up",
                "pair": "YIELDS ↓ / INFLATION ↑",
                "title": "Rates and the latest inflation direction diverge",
                "body": "A fresh decline in the U.S. sovereign-yield feed sits against a higher latest inflation observation. This is a cross-signal divergence, not a causal claim.",
                "severity": 78,
            })
        elif us["changeBp"] > 0 and inflation_delta < 0:
            out.append({
                "id": "us-yields-up-inflation-down",
                "pair": "YIELDS ↑ / INFLATION ↓",
                "title": "Rates rose against softer latest inflation",
                "body": "The latest inflation observation eased while the verified fresh U.S. sovereign-yield move was higher. BondStats flags the mismatch for further analysis.",
                "severity": 78,
            })
    if rates_label == "Higher" and macro_label == "Cooling":
        out.append({
            "id": "broad-rates-higher-macro-cooling",
            "pair": "RATES ↑ / MACRO COOLING",
            "title": "Broad rate direction is not following the latest macro impulse",
            "body": "The qualified daily rate tape is tilted higher while the latest macro observations lean cooler. The brief records the disagreement without assigning a cause.",
            "severity": 72,
        })
    if rates_label == "Lower" and macro_label == "Firming":
        out.append({
            "id": "broad-rates-lower-macro-firming",
            "pair": "RATES ↓ / MACRO FIRMING",
            "title": "Broad rate direction diverges from firmer latest macro data",
            "body": "The qualified daily rate tape leans lower while the latest macro observations lean firmer. This is an observed cross-signal mismatch only.",
            "severity": 72,
        })
    # deduplicate while preserving order
    seen = set()
    unique = []
    for row in out:
        if row["id"] not in seen:
            seen.add(row["id"])
            unique.append(row)
    return unique[:4]


def market_state(rates_label: str, rates_score: int, macro_label: str, event_label: str, dislocations: list[dict], fresh_count: int) -> tuple[str, int, str]:
    intensity = 20
    intensity += min(40, abs(rates_score) * 0.35)
    intensity += 16 if dislocations else 0
    intensity += 18 if event_label == "Immediate" else 10 if event_label == "Elevated" else 0
    intensity = max(10, min(100, round(intensity)))
    if fresh_count == 0:
        if event_label in {"Immediate", "Elevated"}:
            return "Event Window", intensity, "Scheduled risk is dominant while the fresh daily rates tape is unavailable."
        return "Data Quiet", max(18, intensity - 8), "No broad fresh daily rates signal currently qualifies."
    if dislocations and abs(rates_score) >= 25:
        return "Cross-Signal Tension", max(intensity, 68), "Rates and macro signals are not lining up cleanly."
    if rates_label == "Lower" and abs(rates_score) >= 25:
        return "Rates Repricing Lower", max(intensity, 60), "Qualified sovereign yields are moving lower with meaningful breadth."
    if rates_label == "Higher" and abs(rates_score) >= 25:
        return "Rates Repricing Higher", max(intensity, 60), "Qualified sovereign yields are moving higher with meaningful breadth."
    if event_label == "Immediate":
        return "Policy Event Window", max(intensity, 66), "A critical scheduled event is inside the next 24 hours."
    if macro_label == "Cooling":
        return "Macro Cooling", max(intensity, 48), "The latest macro direction leans cooler, without a dominant broad rates move."
    if macro_label == "Firming":
        return "Macro Firming", max(intensity, 48), "The latest macro direction leans firmer, without a dominant broad rates move."
    return "Mixed", intensity, "No single qualified cross-market direction dominates the current signal set."


def signal_stack(rates_label: str, macro_label: str, policy_label: str, event_label: str, dislocations: list[dict], fresh_count: int) -> list[dict]:
    return [
        {"name": "Rates", "value": rates_label, "status": "active" if fresh_count else "limited"},
        {"name": "Macro", "value": macro_label, "status": "active"},
        {"name": "Policy", "value": policy_label, "status": "active"},
        {"name": "Event risk", "value": event_label, "status": "watch" if event_label in {"Immediate", "Elevated"} else "active"},
        {"name": "Divergence", "value": "Active" if dislocations else "None qualified", "status": "watch" if dislocations else "active"},
    ]


def state_memory(histories: list[dict], current_state: str, current_date: dt.date) -> dict:
    same_dates: list[dt.date] = []
    streak = 1
    previous_states = []
    for brief in histories:
        label = brief.get("marketState", {}).get("label")
        date_text = brief.get("meta", {}).get("date")
        try:
            date_value = dt.date.fromisoformat(date_text)
        except Exception:
            continue
        previous_states.append((date_value, label))
        if label == current_state:
            same_dates.append(date_value)
    previous_states.sort(reverse=True)
    for _, label in previous_states:
        if label == current_state:
            streak += 1
        else:
            break
    last_seen = max(same_dates) if same_dates else None
    return {
        "previousState": previous_states[0][1] if previous_states else None,
        "lastSeenDate": last_seen.isoformat() if last_seen else None,
        "daysSinceLastSeen": (current_date - last_seen).days if last_seen else None,
        "consecutiveDays": streak,
        "archiveObservations": len(histories),
    }


def source_integrity(health: dict[str, dict]) -> dict:
    live = sum(row.get("status") == "live" for row in health.values())
    degraded = sum(row.get("status") == "degraded" for row in health.values())
    unavailable = sum(row.get("status") == "unavailable" for row in health.values())
    if unavailable:
        label = "Partial"
    elif degraded:
        label = "Degraded"
    else:
        label = "Verified live"
    return {"label": label, "live": live, "degraded": degraded, "unavailable": unavailable, "total": len(health)}


def one_thing(signals: list[dict], state_label: str, state_reason: str, dislocations: list[dict], memory: dict) -> dict:
    if dislocations:
        d = dislocations[0]
        return {
            "kicker": "THE ONE THING",
            "headline": d["title"],
            "body": d["body"],
            "score": max(70, d.get("severity", 70)),
            "tag": "CROSS-SIGNAL",
        }
    if signals:
        s = signals[0]
        return {
            "kicker": "THE ONE THING",
            "headline": s["headline"],
            "body": s["body"] + (f" {s['memory']}" if s.get("memory") else ""),
            "score": s.get("strength", 60),
            "tag": s.get("kicker", "SIGNAL"),
        }
    quiet_memory = ""
    if memory.get("consecutiveDays", 1) > 1:
        quiet_memory = f" This state has persisted for {memory['consecutiveDays']} archived days."
    return {
        "kicker": "THE ONE THING",
        "headline": "Quiet is a signal when nothing qualifies",
        "body": state_reason + quiet_memory + " BondStats does not manufacture a narrative simply to fill the page.",
        "score": 35,
        "tag": "QUIET SIGNAL",
    }


def policy_snapshot(feed: dict | None) -> list[dict]:
    rows = []
    for bank in (feed or {}).get("banks", []):
        rows.append({
            "id": bank.get("id"),
            "name": bank.get("name"),
            "displayRate": bank.get("displayRate"),
            "decision": bank.get("decision"),
            "decisionDate": bank.get("decisionDate"),
            "changeBp": number(bank.get("changeBp")),
            "stance": bank.get("stance"),
            "nextMeeting": bank.get("nextMeeting"),
            "sourceName": bank.get("sourceName"),
            "sourceUrl": bank.get("sourceUrl"),
        })
    return rows


def main() -> None:
    now = utcnow()
    DATA.mkdir(parents=True, exist_ok=True)
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)

    histories = load_previous_briefs()
    previous = histories[0] if histories else read_json(DATA / "latest.json")
    sources, health = load_sources(now)

    # Macro, policy and calendar are core context. If all three are unavailable and no
    # prior brief exists, fail instead of publishing a false-looking empty product.
    core_available = sum(bool(sources.get(k)) for k in ("macro", "policy", "calendar"))
    if core_available == 0 and not previous:
        raise SystemExit("No core source or last-known-good brief is available; refusing to publish.")

    markets_all = market_rows(sources.get("yields"))
    markets = [row for row in markets_all if row.get("freshDaily")]
    macro = macro_rows(sources.get("macro"))
    events = upcoming_events(sources.get("calendar"), now)
    policy_next = next_policy(sources.get("policy"), now)
    policy_rows = policy_snapshot(sources.get("policy"))

    rates_label, rates_score, rates_detail = rates_state(markets_all)
    macro_label, macro_score, macro_detail = macro_impulse(macro)
    policy_label, policy_detail = policy_state(sources.get("policy"))
    event_label, event_score, event_detail = event_risk(events, now)

    signals = build_signals(markets_all, macro, sources.get("policy"), previous, histories)
    dislocations = build_dislocations(markets_all, macro, rates_label, macro_label)
    state_label, intensity, state_reason = market_state(
        rates_label, rates_score, macro_label, event_label, dislocations, len(markets)
    )
    memory = state_memory(histories, state_label, now.date())
    one = one_thing(signals, state_label, state_reason, dislocations, memory)
    stack = signal_stack(rates_label, macro_label, policy_label, event_label, dislocations, len(markets))
    integrity = source_integrity(health)

    brief = {
        "meta": {
            "product": PRODUCT,
            "date": now.date().isoformat(),
            "generatedAt": now.isoformat().replace("+00:00", "Z"),
            "version": VERSION,
            "engine": "BondStats Signal Engine v2",
            "copyrightMethod": "Original deterministic analysis from factual official-source observations and BondStats data feeds; no third-party news articles, headlines, screenshots or editorial text are ingested, summarized or rewritten.",
            "sourceHealth": health,
            "sourceIntegrity": integrity,
        },
        "marketState": {
            "label": state_label,
            "intensity": intensity,
            "reason": state_reason,
            "previousLabel": memory.get("previousState"),
            "freshDailyMarkets": len(markets),
            "rising": rates_detail.get("rising"),
            "falling": rates_detail.get("falling"),
        },
        "oneThing": one,
        "signalStack": stack,
        "signalMemory": memory,
        "diagnostics": {
            "rates": {"label": rates_label, "score": rates_score, **rates_detail},
            "macro": {"label": macro_label, "score": macro_score, **macro_detail},
            "policy": {"label": policy_label, **policy_detail},
            "eventRisk": {"label": event_label, "score": event_score, **event_detail},
        },
        "signals": signals,
        "dislocations": dislocations,
        "markets": markets[:16],
        "macro": macro,
        "policy": policy_rows,
        "nextEvents": events,
        "nextPolicy": policy_next,
        "methodology": [
            "No third-party news articles, headlines, screenshots or editorial text are scraped, copied, summarized or rewritten.",
            "Narrative text is generated deterministically from structured facts, official-source observations and BondStats data feeds.",
            "Causality is not inferred from coincident market moves; divergences are labeled as observations.",
            "Daily yield-change claims require daily frequency, non-fallback status and staleness of seven days or less.",
            "New macro and policy signals are emitted only when the structured upstream value changed versus the prior archived brief.",
            "If a source fails, the engine may use a last-known-good snapshot and visibly marks the source degraded; unavailable sources are never silently treated as live.",
            "A daily archive snapshot is immutable after creation, preserving what BondStats showed on that date.",
            "No consensus forecasts are fabricated or inferred.",
        ],
    }

    write_json_atomic(DATA / "latest.json", brief)

    # Archive is deliberately immutable. Re-runs refresh latest.json but do not rewrite
    # the day's historical record after it has been created.
    archive_path = ARCHIVE / f"{now.date().isoformat()}.json"
    if not archive_path.exists():
        write_json_atomic(archive_path, brief)

    manifest = []
    for path in sorted(ARCHIVE.glob("*.json"), reverse=True):
        archived = read_json(path)
        if not archived:
            continue
        manifest.append({
            "date": archived.get("meta", {}).get("date"),
            "marketState": archived.get("marketState", {}).get("label"),
            "intensity": archived.get("marketState", {}).get("intensity"),
            "oneThing": archived.get("oneThing", {}).get("headline"),
            "signals": len(archived.get("signals", [])),
            "dislocations": len(archived.get("dislocations", [])),
            "sourceIntegrity": archived.get("meta", {}).get("sourceIntegrity", {}).get("label"),
        })
    write_json_atomic(DATA / "archive.json", {
        "product": PRODUCT,
        "version": VERSION,
        "updatedAt": now.isoformat().replace("+00:00", "Z"),
        "days": manifest,
    })

    print(json.dumps({
        "date": now.date().isoformat(),
        "state": state_label,
        "intensity": intensity,
        "signals": len(signals),
        "dislocations": len(dislocations),
        "freshMarkets": len(markets),
        "sourceIntegrity": integrity,
    }, indent=2))


if __name__ == "__main__":
    main()
