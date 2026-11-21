"""The family's `harvest` task (see scrape.json): one queue item = one section of one organisation's website.

For each item the task:
1. crawls the section's pages from its seed URLs (breadth first, inside the section's URL prefixes, up to max_pages / max_depth),
   obeying the host's robots.txt and the hub's speed settings;
2. stores every HTML page in the family's bucket (pages/<id>.html.gz) and one `page:<id>` record per page;
3. downloads every linked document (PDF, office file, image, archive) on the organisation's hosts that the section's
   manifest does not list yet, stores the file in the bucket (docs/<ext>/<id[:2]>/<id>.<ext>, for OCR later) and one
   `doc:<id>` record with its link text, row text, dates, categories, size and checksums;
4. keeps a manifest (state/<section>.json.gz) of stored documents, so a rerun or a later round fetches only new ones.

Run one section without the hub (prints records, saves nothing unless --save DIR):
    python harvest.py --local epfo circulars [--max-pages 3] [--max-docs 2] [--save /tmp/out]

Env (from the project's pool entry): ORG. Test limits: HARVEST_MAX_PAGES, HARVEST_MAX_DOCS (0 = section's own limits).
"""
import gzip
import io
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.robotparser
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from scrape_hub_client import HubClient, HubRejected, LocalHub, ca_bundle, stop_flag, timed_get

import extract as X
from sources import SOURCES

PROJECT = os.environ.get("SCRAPE_POOL_PROJECT", "")
BUDGET = float(os.environ.get("SCRAPE_MAX_HOURS", "1")) * 3600
DEADLINE = time.time() + BUDGET - min(300, BUDGET * 0.1)     # stop work and save the manifest before the runner stops us
UA = "Mozilla/5.0 (compatible; s1d-labs-research/1.0; +https://github.com/s1d-labs/epfo-pf)"
MAX_DOC_BYTES = int(float(os.environ.get("HARVEST_MAX_DOC_MB", "250")) * 1e6)
MAX_PAGE_BYTES = 15_000_000
MAX_THREADS = 4                      # never more than this many parallel downloads per worker, whatever the hub allows
MIN_DELAY = 0.5                      # seconds between requests of one thread, at the least
CLAIM_MARGIN = min(900, BUDGET * 0.25)   # do not start a new item this close to the end of the time budget
LIMIT_PAGES = int(os.environ.get("HARVEST_MAX_PAGES", "0"))
LIMIT_DOCS = int(os.environ.get("HARVEST_MAX_DOCS", "0"))
STOP = stop_flag(install=False)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Stats(dict):
    """Counters of one section, safe to add to from the download threads."""
    lock = threading.Lock()

    def add(self, key, n=1):
        with self.lock:
            self[key] += n


class Section:
    """One queue item's work: the section config, merged with the organisation's defaults."""

    def __init__(self, org, key, pages=None):
        src = SOURCES[org]
        sec = next((s for s in src["sections"] if s["key"] == key), None)
        if sec is None:
            raise KeyError(f"no section {key!r} in sources.py for {org}")
        self.org, self.key, self.src, self.sec = org, key, src, sec
        self.hosts = src["hosts"]
        self.doc_hosts = src["hosts"] + src.get("doc_hosts", [])
        self.follow = sec.get("follow", [])
        self.exclude = src.get("exclude", []) + sec.get("exclude", [])
        self.doc_exclude = src.get("doc_exclude", []) + sec.get("doc_exclude", [])
        self.chrome = sec.get("chrome", False)          # also keep documents linked from the header, menus and footer
        self.max_pages = LIMIT_PAGES or sec.get("max_pages", 200)
        self.max_depth = sec.get("max_depth", 2)
        self.max_docs = LIMIT_DOCS or sec.get("max_docs", 0)
        self.categories = sec.get("categories", [])
        self.aliases = src.get("aliases", {})
        self.title = sec.get("title", key)
        self.seeds = list(sec.get("seeds", []))
        self.state = f"state/{key}.json.gz"
        if pages:                                             # a page-range item of a long paged list: only those listing pages
            a, b = pages
            self.seeds = [sec["paged"]["url"].format(n=n) for n in range(a, b + 1)]
            self.max_pages = LIMIT_PAGES or len(self.seeds)
            self.max_depth = 0


class Fetcher:
    """HTTP for one worker: one requests.Session per thread, the hub's delay, robots.txt per host, size caps."""

    def __init__(self, hub, src):
        self.hub, self.src = hub, src
        self.local = threading.local()
        self.robots, self.robots_lock = {}, threading.Lock()
        self.verify = ca_bundle() if src.get("ca_bundle") else True

    def session(self):
        s = getattr(self.local, "s", None)
        if s is None:
            s = self.local.s = requests.Session()
            s.verify = self.verify
            s.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})
        return s

    def pause(self):
        time.sleep(max(MIN_DELAY, self.hub.settings.get("delay_ms", 0) / 1000))

    def allowed(self, url):
        """robots.txt of the URL's host, fetched once per run, read as RFC 9309 says: a 4xx answer (no file) allows everything;
        a 5xx answer or no answer disallows the host for this run (the item fails and the hub retries it later)."""
        host = X.host_of(url)
        with self.robots_lock:
            rp = self.robots.get(host)
            if rp is None:
                rp = urllib.robotparser.RobotFileParser()
                r = timed_get(self.hub, self.session(), f"https://{host}/robots.txt", timeout=20, block_codes=())
                if r is None or r.status_code >= 500:
                    rp.disallow_all = True
                    self.hub.failure("robots", host, f"robots.txt: {getattr(r, 'status_code', 'no answer')}")
                elif r.status_code == 200 and "html" not in r.headers.get("Content-Type", "").lower():
                    rp.parse(r.text.splitlines())
                else:
                    rp.allow_all = True
                self.robots[host] = rp
        return rp.can_fetch(UA, url)

    def get(self, url, max_bytes, block_codes=(403, 429, 503)):
        """(response, body bytes) or (response or None, None). Reads at most max_bytes; a bigger body gives body None.
        block_codes: answers that count as the site refusing us (they feed the hub's back-off)."""
        r = timed_get(self.hub, self.session(), url, timeout=60, stream=True, allow_redirects=True, block_codes=block_codes)
        if r is None:
            return None, None
        try:
            if r.status_code != 200:
                return r, None
            n = int(r.headers.get("Content-Length") or 0)
            if n > max_bytes:
                return r, None
            buf = io.BytesIO()
            t = time.time()
            for chunk in r.iter_content(256 * 1024):
                buf.write(chunk)
                if buf.tell() > max_bytes:
                    return r, None
                if time.time() - t > 600:                     # a 10-minute trickle is not worth waiting for
                    return r, None
            return r, buf.getvalue()
        except requests.RequestException:
            self.hub.metric("http_error")
            self.hub.error()
            return r, None
        finally:
            r.close()


def decode(r, body):
    enc = r.encoding
    if not enc or enc.lower() == "iso-8859-1":
        enc = requests.utils.get_encodings_from_content(body[:4000].decode("ascii", "ignore"))[:1] or ["utf-8"]
        enc = enc[0]
    return body.decode(enc, errors="replace")


class Manifest:
    """state/<section>.json.gz in the bucket: {"docs": {doc_id: {"url", "sha256", "bytes", "at"}}}, one per section, shared by all
    page-range items of the section. Read at the start of an item; written every 50 new documents and at the end, merged with the
    copy in the bucket (other items of the section may have added to it), so an item cut short continues where it stopped and a
    document that moves to another page range is not fetched again. A lost update between two writers only costs a re-download."""

    SAVE_EVERY = 50

    def __init__(self, hub, section):
        self.hub, self.path = hub, section.state
        self.docs, self.new, self.lock = {}, 0, threading.Lock()

    def _remote(self):
        project = getattr(self.hub, "project", PROJECT)
        if not hasattr(self.hub, "read_urls"):
            return {}
        try:
            urls = self.hub.read_urls(project, [f"{project}/{self.path}"])
        except HubRejected as e:
            print(f"manifest not readable ({e}); starting empty", file=sys.stderr)
            self.hub.metric("manifest_unreadable")
            return {}
        for url in urls.values():
            try:
                s = requests.Session()
                s.trust_env = False                           # the bucket, not the site: never through the site's proxy
                r = s.get(url, timeout=60)
                if r.status_code == 200:
                    return json.loads(gzip.decompress(r.content)).get("docs", {})
            except (requests.RequestException, OSError, ValueError) as e:
                print(f"manifest read failed: {e}", file=sys.stderr)
        return {}

    def load(self):
        self.docs = self._remote()
        return self

    def has(self, doc_id):
        with self.lock:
            return doc_id in self.docs

    def add(self, doc_id, entry):
        with self.lock:
            self.docs[doc_id] = entry
            self.new += 1
            due = self.new % self.SAVE_EVERY == 0
        if due:
            self.save()

    def save(self):
        remote = self._remote()
        with self.lock:
            remote.update(self.docs)
            self.docs = remote
            data = gzip.compress(json.dumps({"docs": self.docs, "saved": now()}).encode())
        self.hub.upload_many([(self.path, data, "application/gzip")])


def crawl_pages(hub, f, sec, stats):
    """Breadth-first crawl of the section's pages. Returns {doc_url: link info} for every document link found."""
    frontier = deque((X.canonical(u, sec.aliases), 0, "") for u in sec.seeds)
    seen, docs = set(), {}
    while frontier and stats["pages"] < sec.max_pages:
        if STOP.is_set() or time.time() > DEADLINE:
            stats["cut"] = "time budget" if time.time() > DEADLINE else "stopped by signal"
            break
        url, depth, ref = frontier.popleft()
        if url in seen:
            continue
        seen.add(url)
        if not f.allowed(url):
            hub.metric("robots_skipped")
            continue
        r, body = f.get(url, MAX_DOC_BYTES)
        f.pause()
        if body is None:
            stats["page_fail"] += 1
            hub.failure("page", url, f"HTTP {getattr(r, 'status_code', 'no answer')}", section=sec.key, referrer=ref)
            continue
        final = X.normalize(r.url)
        ctype, disp = r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", "")
        locs = X.parse_sitemap(body[:400_000].decode("utf-8", "replace")) if "xml" in ctype.lower() or url.endswith(".xml") else None
        if locs is not None:                                  # a sitemap seed: its URLs are pages of the section
            for u in locs:
                u = X.canonical(u, sec.aliases)
                if X.host_allowed(u, sec.hosts) and u not in seen and X.in_scope(u, sec.follow, sec.exclude):
                    frontier.append((u, depth, url))
            continue
        if X.is_document_type(ctype, disp):                   # a link that looked like a page served a file
            d = docs.setdefault(url, {"url": url, "text": "", "context": "", "page": ref})
            d["prefetched"] = (r, body)
            d.pop("maybe", None)
            continue
        if "html" not in ctype.lower() and ctype:
            continue
        html = decode(r, body)
        title, links = X.parse_page(html, final, sec.src.get("chrome_css", ()))
        pid = X.url_id(url)
        info = hub.upload_many([(f"pages/{pid[:2]}/{pid}.html.gz", gzip.compress(html.encode()), "application/gzip")])[0]
        n_docs = 0
        for link in links:
            u = link["url"] = X.canonical(link["url"], sec.aliases)
            kind = X.looks_like_document(u)
            if kind is not False and X.host_allowed(u, sec.doc_hosts):
                if any(re.search(x, u, re.I) for x in sec.doc_exclude) or (link["chrome"] and not sec.chrome):
                    continue
                if kind is True:
                    n_docs += 1
                    if u not in docs:
                        docs[u] = {**link, "page": url, "page_title": title}
                    continue
            if kind is not True and X.host_allowed(u, sec.hosts) and depth < sec.max_depth and u not in seen \
                    and X.in_scope(u, sec.follow, sec.exclude):
                frontier.append((u, depth + 1, url))
                if kind is None:                               # a download link without an extension: keep its anchor text
                    docs.setdefault(u, {**link, "page": url, "page_title": title, "maybe": True})
        hub.record(f"page:{pid}", {
            "kind": "page", "org": sec.org, "section": sec.key, "url": url, "final_url": final, "title": title, "depth": depth,
            "referrer": ref, "n_links": len(links), "n_docs": n_docs, "file": info["key"], "bytes": info["bytes"],
            "sha256": info["sha256"], "fetched_at": now()})
        stats["pages"] += 1
        stats["records"] += 1
    # extensionless links that were crawled and turned out to be HTML pages are not documents
    return {u: d for u, d in docs.items() if not (d.get("maybe") and u in seen and "prefetched" not in d)}


def store_doc(hub, f, sec, man, link, stats):
    """Download one document (unless the manifest has it), store it in the bucket and record it."""
    url = link["url"]
    did = X.url_id(url)
    if man.has(did):
        stats.add("skipped")
        return
    if not f.allowed(url):
        hub.metric("robots_skipped")
        return
    if "prefetched" in link:
        r, body = link.pop("prefetched")
    else:
        r, body = f.get(url, MAX_DOC_BYTES, block_codes=(429, 503))   # a 403 on one file is a missing file (S3/CloudFront)
        f.pause()
    if body is None:
        if link.get("maybe"):
            return                                            # an extensionless link that was a page after all, or gone
        code = getattr(r, "status_code", None)
        reason = "too large" if code == 200 else f"HTTP {code or 'no answer'}"
        stats.add("doc_fail")
        hub.failure("doc", url, reason, section=sec.key, page=link.get("page", ""))
        return
    ctype, disp = r.headers.get("Content-Type", ""), r.headers.get("Content-Disposition", "")
    if not X.is_document_type(ctype, disp) and not (X.looks_like_document(url) and "html" not in ctype.lower()):
        return                                                # an HTML page (error page, viewer): not a document
    ext = X.ext_from_type(ctype, disp, r.url)
    info = hub.upload_many([(f"docs/{ext}/{did[:2]}/{did}.{ext}", body, ctype.split(";")[0] or "application/octet-stream")])[0]
    text = link.get("text", "")
    context = link.get("context", "")
    column = link.get("column", "")
    hub.record(f"doc:{did}", {
        "kind": "document", "org": sec.org, "section": sec.key, "section_title": sec.title,
        "categories": X.categorize(column, X.doc_title(text, context), url, default=sec.categories),
        "url": url, "final_url": X.normalize(r.url), "title": X.doc_title(text, context), "link_text": text, "column": column, "context": context,
        "dates": X.find_dates(f"{text} {context}"), "page": link.get("page", ""), "page_title": link.get("page_title", ""),
        "content_type": ctype, "ext": ext, "bytes": info["bytes"], "md5": info["md5"], "sha256": info["sha256"], "file": info["key"],
        "last_modified": r.headers.get("Last-Modified", ""), "etag": r.headers.get("ETag", ""), "fetched_at": now(),
        "ocr": X.ocr_state(ext)})
    hub.clear_failure("doc", url)
    man.add(did, {"url": url, "sha256": info["sha256"], "bytes": info["bytes"], "at": now()})
    hub.metric("docs_stored")
    stats.add("docs")
    stats.add("records")


def run_section(hub, org, key, pages=None):
    """Crawl one section (or one page range of it); returns (status, fetched, note)."""
    sec = Section(org, key, pages)
    f = Fetcher(hub, sec.src)
    man = Manifest(hub, sec).load()
    stats = Stats(pages=0, page_fail=0, docs=0, doc_fail=0, skipped=0, records=0, cut="")
    docs = crawl_pages(hub, f, sec, stats)
    links = list(docs.values())
    if sec.max_docs:                                          # a test limit: the section's first N documents
        links = links[:sec.max_docs]
    todo = [d for d in links if not man.has(X.url_id(d["url"]))]
    stats["skipped"] = len(links) - len(todo)
    threads = max(1, min(MAX_THREADS, int(hub.settings.get("threads", 1) or 1)))
    def one(link):
        if STOP.is_set() or time.time() > DEADLINE:
            return
        try:
            store_doc(hub, f, sec, man, link, stats)
        except HubRejected:
            raise
        except Exception as e:                                # one bad file (upload retries used up, broken answer) is not fatal
            if "507" in str(e):                               # the bucket is full: stop everything
                raise
            stats.add("doc_fail")
            hub.failure("doc", link["url"], f"{type(e).__name__}: {e}"[:300], section=sec.key)

    with ThreadPoolExecutor(threads) as pool:
        for fu in as_completed([pool.submit(one, link) for link in todo]):
            fu.result()
    if STOP.is_set() or time.time() > DEADLINE:
        stats["cut"] = stats["cut"] or ("time budget" if time.time() > DEADLINE else "stopped by signal")
    if man.new:
        man.save()
    rid = f"section:{key}" + (f":{pages[0]}-{pages[1]}" if pages else "")
    hub.record(rid, {"kind": "section", "org": org, "section": key, "pages_range": pages, "title": sec.title, "links_found": len(docs),
                                  **stats, "finished_at": now()})
    stats["records"] += 1
    note = (f"{stats['pages']} pages, {stats['docs']} new docs, {stats['skipped']} known, "
            f"{stats['page_fail']}+{stats['doc_fail']} failed")
    if stats["cut"]:
        return "failed", stats["records"], f"partial ({stats['cut']}): {note}"
    if stats["pages"] == 0:
        return "failed", stats["records"], f"no page of the section loaded: {note}"
    return "done", stats["records"], note


def main():
    stop_flag()                                               # SIGINT / SIGTERM set STOP
    hub = HubClient(PROJECT, job_index=int(os.environ.get("SCRAPE_JOB_INDEX", "0")), total_jobs=int(os.environ.get("SCRAPE_TOTAL_JOBS", "1")))
    org = os.environ.get("ORG", "")
    errors = 0
    try:
        while time.time() < DEADLINE - CLAIM_MARGIN and not STOP.is_set():   # no new item in the last minutes
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
                status, fetched, note = run_section(hub, p.get("org") or org, p["section"], p.get("pages"))
                errors = 0
            except Exception as e:                            # a bug or a broken page in one section must not stop the others
                hub.complete([item["key"]], "failed", error=f"{type(e).__name__}: {e}"[:300])
                traceback.print_exc()
                errors += 1
                if isinstance(e, HubRejected) or "507" in str(e) or errors >= 3:
                    raise
                continue
            print(f"{item['key']}: {status}: {note}", file=sys.stderr)
            hub.complete([item["key"]], status, error="" if status == "done" else note[:300], fetched=fetched)
        if STOP.is_set():
            hub.close("failed", "stopped by signal")
        else:
            hub.close()
    except BaseException as e:
        hub.close("failed", f"{type(e).__name__}: {e}"[:200])
        raise


def local(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="harvest.py --local")
    ap.add_argument("org")
    ap.add_argument("section")
    ap.add_argument("--pages", help="a page range of a paged section, e.g. 1-2")
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--max-docs", type=int, default=2)
    ap.add_argument("--save", help="save pages and documents here (default: nothing saved)")
    a = ap.parse_args(argv)
    global LIMIT_PAGES, LIMIT_DOCS
    LIMIT_PAGES, LIMIT_DOCS = a.max_pages, a.max_docs
    hub = LocalHub(project=f"local-{a.org}", save_dir=a.save, delay_ms=500)
    pages = [int(x) for x in a.pages.split("-")] if a.pages else None
    status, fetched, note = run_section(hub, a.org, a.section, pages)
    print(f"{status}: {note}; counters {hub.counts}", file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--local"]:
        local(sys.argv[2:])
    else:
        main()
