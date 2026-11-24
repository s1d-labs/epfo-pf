"""The family's `recover` task: documents that left the live web, fetched back from the Internet Archive.

data/wayback_lost.csv.gz lists them (built from the Wayback CDX inventory): the old EPFO site (epfindia.gov.in/site_docs,
/site_en) and the dead ESIC domain esic.nic.in. One queue item = a range of rows in that file (family.py builds them).
For each row the task fetches the archived file (`/web/<ts>id_/<url>` returns the original bytes), stores it in the bucket
under the same `docs/` layout as `harvest`, and records `doc:<sha1 of the original URL>` with `source: "wayback"`.

Common Crawl captures stop at 5 MiB, so a large PDF can be truncated in the archive. The task detects that from the
archive's headers and tries up to three other captures of the same URL; a file that stays truncated is stored and marked
`truncated: true`.

Run rows without the hub: python recover.py --local --rows 0-1
"""
import csv
import gzip
import json
import os
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

from scrape_hub_client import HubClient, HubRejected, LocalHub, stop_flag

import extract as X
from harvest import CLAIM_MARGIN, DEADLINE, MAX_DOC_BYTES, STOP, Fetcher, Manifest, now

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
DATA = Path(__file__).parent / "data" / "wayback_lost.csv.gz"
CC_CAP = 5 * 1024 * 1024
CDX = "https://web.archive.org/cdx/search/cdx"
_rows = None


def load_rows(path=DATA):
    """All rows of the data file, in file order (the queue items refer to row numbers)."""
    global _rows
    if _rows is None or path != DATA:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        if path != DATA:
            return rows
        _rows = rows
    return _rows


def chunks(rows, size=100):
    """[(start, end_inclusive, org, category)]: consecutive rows of one org and category, at most `size` rows each."""
    out, i = [], 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and j + 1 - i < size and (rows[j + 1]["org"], rows[j + 1]["category"]) == (rows[i]["org"], rows[i]["category"]):
            j += 1
        out.append((i, j, rows[i]["org"], rows[i]["category"]))
        i = j + 1
    return out


def truncated(headers, body_len):
    """True when the archive holds only part of the original response."""
    if body_len == CC_CAP:
        return True
    for h in ("x-archive-orig-x-crawler-content-length", "x-archive-orig-content-length"):
        try:
            if int(headers.get(h) or 0) > body_len:
                return True
        except ValueError:
            pass
    return False


def capture_ts(wayback_url):
    part = wayback_url.split("/web/", 1)[-1]
    return part.split("id_", 1)[0][:14]


def alternatives(f, original_url, used_ts, limit=3):
    """Other 200 captures of the same URL, largest stored record first."""
    r, body = f.get(f"{CDX}?url={original_url}&output=json&fl=timestamp,length&filter=statuscode:200&limit=50", 2_000_000)
    f.pause()
    if not body:
        return []
    try:

        caps = [(int(c[1]) if c[1].isdigit() else 0, c[0]) for c in json.loads(body)[1:]]
    except (ValueError, IndexError):
        return []
    caps = sorted((c for c in caps if c[1] != used_ts), reverse=True)[:limit]
    return [f"https://web.archive.org/web/{ts}id_/{original_url}" for _, ts in caps]


def recover_row(hub, f, man, row, stats):
    did = X.url_id(row["original_url"])
    if man.has(did):
        stats.add("skipped")
        return
    candidates, best, i = [row["wayback_url"]], None, 0      # best = (response, body, url, truncated)
    while i < len(candidates) and i < 4:
        url = candidates[i]
        r, body = f.get(url, MAX_DOC_BYTES, block_codes=(429, 503))
        f.pause()
        ctype = r.headers.get("Content-Type", "") if r is not None else ""
        if body is not None and not ("html" in ctype.lower() and not row["original_url"].lower().endswith((".htm", ".html"))):
            cut = truncated(r.headers, len(body))
            if best is None or (best[3] and not cut) or (best[3] == cut and len(body) > len(best[1])):
                best = (r, body, url, cut)
            if not cut:
                break                                          # a complete copy: stop here
        if i == 0:
            candidates += alternatives(f, row["original_url"], capture_ts(url))
        i += 1
    if best is None:
        stats.add("doc_fail")
        hub.failure("wayback", row["original_url"], "no complete archived copy", wayback=row["wayback_url"])
        return
    r, body, used, cut = best
    ctype = r.headers.get("Content-Type", "").split(";")[0]
    ext = X.ext_from_type(ctype, "", row["original_url"])
    info = hub.upload_many([(f"docs/{ext}/{did[:2]}/{did}.{ext}", body, ctype or "application/octet-stream")])[0]
    hub.record(f"doc:{did}", {
        "kind": "document", "source": "wayback", "org": row["org"], "section": f"wayback-{row['category']}",
        "categories": [row["category"]], "url": row["original_url"], "wayback_url": used, "captured": capture_ts(used),
        "host": row["host"], "lost_from_live": True, "content_type": ctype, "ext": ext, "bytes": info["bytes"],
        "md5": info["md5"], "sha256": info["sha256"], "file": info["key"], "truncated": cut,
        "dates": X.find_dates(row["original_url"]), "ocr": X.ocr_state(ext), "fetched_at": now()})
    hub.clear_failure("wayback", row["original_url"])
    man.add(did, {"url": row["original_url"], "sha256": info["sha256"], "bytes": info["bytes"], "truncated": cut, "at": now()})
    stats.add("docs")
    stats.add("truncated", int(cut))


class Stats(dict):
    def add(self, k, n=1):
        self[k] = self.get(k, 0) + n


def run_item(hub, start, end):
    rows = load_rows()[start:end + 1]
    if int(os.environ.get("RECOVER_MAX_ROWS", "0")):          # test limit for scrape-check
        rows = rows[:int(os.environ["RECOVER_MAX_ROWS"])]
    f = Fetcher(hub, {"ca_bundle": False})
    man = Manifest(hub, SimpleNamespace(state=f"state/recover/{start:05d}-{end:05d}.json.gz")).load()
    stats = Stats(docs=0, skipped=0, doc_fail=0, truncated=0)
    for row in rows:
        if STOP.is_set() or time.time() > DEADLINE:
            break
        try:
            recover_row(hub, f, man, row, stats)
        except HubRejected:
            raise
        except Exception as e:
            if "507" in str(e):
                raise
            stats.add("doc_fail")
            hub.failure("wayback", row["original_url"], f"{type(e).__name__}: {e}"[:300])
    if man.new:
        man.save()
    note = f"{stats['docs']} stored ({stats['truncated']} truncated), {stats['skipped']} known, {stats['doc_fail']} failed"
    done = stats["docs"] + stats["skipped"] + stats["doc_fail"]
    first = rows[0] if rows else {}
    hub.record(f"range:{start:05d}-{end:05d}", {"kind": "range", "start": start, "end": end, "org": first.get("org"),
                                              "category": first.get("category"), "rows": len(rows), **stats,
                                              "finished_at": now()})
    if done < len(rows):
        return "failed", stats["docs"] + 1, f"partial: {note}"
    return "done", stats["docs"] + 1, note


def main():
    stop_flag()
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    errors = 0
    try:
        while time.time() < DEADLINE - CLAIM_MARGIN and not STOP.is_set():
            if hub.settings.get("paused"):
                time.sleep(20)
                continue
            items = hub.claim(1, steal=True, retry_failed=True)
            if not items:
                if hub.settings.get("paused"):
                    continue
                break
            item = items[0]
            p = item["payload"]
            try:
                status, fetched, note = run_item(hub, p["start"], p["end"])
                errors = 0
            except Exception as e:
                hub.complete([item["key"]], "failed", error=f"{type(e).__name__}: {e}"[:300])
                traceback.print_exc()
                errors += 1
                if isinstance(e, HubRejected) or "507" in str(e) or errors >= 3:
                    raise
                continue
            print(f"{item['key']}: {status}: {note}", file=sys.stderr)
            hub.complete([item["key"]], status, error="" if status == "done" else note[:300], fetched=fetched)
        hub.close("failed", "stopped by signal") if STOP.is_set() else hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        a, b = (int(x) for x in sys.argv[sys.argv.index("--rows") + 1].split("-")) if "--rows" in sys.argv else (0, 0)
        hub = LocalHub(project="local-archive", delay_ms=2000)
        status, fetched, note = run_item(hub, a, b)
        print(f"{status}: {note}; counters {hub.counts}", file=sys.stderr)
    else:
        main()
