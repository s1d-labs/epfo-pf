"""What this family scrapes, built from sources.py. Change sources.py to add a site or a section.

One project per organisation (its own queue, target host and health check). Queue items:
- weekly items, key "<week>:<section>": every section, and the first `weekly` pages of a paged section. The setup workflow runs
  every week, so each week gets new keys; the task then fetches the listing pages again and downloads only new documents
  (each section's manifest in the bucket lists the stored documents);
- backfill items, key "<ROUND>:<section>:<a>-<b>": the whole of a paged section in page ranges, seeded once per ROUND.
PILOT limits each project's queue to its first items for a first pool run; None seeds everything.
"""
import json
from datetime import date
from pathlib import Path

from sources import SOURCES

FAMILY = json.loads((Path(__file__).parent / "scrape.json").read_text())["family"]
ROUND = "r2026-11"                       # change this (e.g. "r2027-01") to crawl the paged archives again
_y, _w, _ = date.today().isocalendar()
WEEK = f"w{_y}-{_w:02d}"
PILOT = 4                                # items per project while the first pool runs are watched; None = all


def _range_item(org, s, key, a, b):
    return {"key": f"{key}:{s['key']}:{a:04d}-{b:04d}",
            "payload": {"org": org, "section": s["key"], "pages": [a, b], "expected": (b - a + 1) * s["paged"].get("per_page", 20)}}


def _items(org, s):
    """The weekly item of a section, then (for a paged section) its backfill page ranges."""
    if "paged" not in s:
        return [{"key": f"{WEEK}:{s['key']}", "payload": {"org": org, "section": s["key"], "expected": s.get("expected", 50)}}]
    pg = s["paged"]
    out = [_range_item(org, s, WEEK, 1, min(pg.get("weekly", pg["chunk"]), pg["last"]))]
    for a in range(1, pg["last"] + 1, pg["chunk"]):
        out.append(_range_item(org, s, ROUND, a, min(a + pg["chunk"] - 1, pg["last"])))
    return out


def _project(org, src):
    host = src["target"]
    items = [it for s in src["sections"] for it in _items(org, s)]
    weekly = [i for i in items if i["key"].startswith(WEEK)]
    items = weekly + [i for i in items if not i["key"].startswith(WEEK)]
    return {
        "name": f"{FAMILY}-{org}",
        "title": src["title"],
        "task": "harvest",
        "target": host,
        "env": {"ORG": org},
        "probe": f"{FAMILY}:{host}",
        "proxy": src.get("proxy", ""),
        "threads": src.get("threads", 2),
        "delay_ms": src.get("delay_ms", 1000),
        "max_workers": src.get("max_workers", 2),
        "unit_label": "section",
        "record_label": "page or document",
        "items": items[:PILOT] if PILOT else items,
    }


PROJECTS = [_project(org, src) for org, src in SOURCES.items() if src.get("enabled", True)]

# health checks the hub runs every minute; a project's work holds while its check fails
PROBES = [{"name": f"{FAMILY}:{src['target']}", "url": src["probe_url"], "expect": src["probe_expect"]}
          for org, src in SOURCES.items() if src.get("enabled", True)]
