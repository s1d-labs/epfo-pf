"""Link extraction on saved pages of each site (tests/pages/<org>/). Offline."""
import gzip
import re
from pathlib import Path

import extract as X
from sources import SOURCES

PAGES = Path(__file__).parent / "pages"


def docs_on(org, name, url):
    """The document links the harvest task keeps from a saved page: same aliases, hosts and doc_exclude rules."""
    f = PAGES / org / name
    raw = gzip.decompress(f.read_bytes()) if name.endswith(".gz") else f.read_bytes()
    src = SOURCES[org]
    title, links = X.parse_page(raw.decode("utf-8", "replace"), url, src.get("chrome_css", ()))
    hosts = src["hosts"] + src.get("doc_hosts", [])
    out = []
    for l in links:
        l["url"] = X.canonical(l["url"], src.get("aliases", {}))
        if X.looks_like_document(l["url"]) and X.host_allowed(l["url"], hosts) \
                and not any(re.search(x, l["url"], re.I) for x in src.get("doc_exclude", [])):
            out.append(l)
    return title, out


def test_cmpfo_office_orders_table():
    _, docs = docs_on("cmpfo", "office_orders.html", "https://cmpfo.gov.in/office_orders.html")
    assert len(docs) >= 150                                   # 160 rows on 2026-11-15
    first = docs[0]
    assert first["url"] == "https://cmpfo.gov.in/office_order/Final_Seniority_Lists_2026.pdf"
    assert "OFFICE ORDER NO. 107 OF 2026" in X.doc_title(first["text"], first["context"])
    assert X.find_dates(first["context"]) == ["2026-11-10"]
    assert "office_orders" in X.categorize(first["text"], first["context"], first["url"])


def test_cmpfo_tender_rows_have_gem_bid_numbers_and_dates():
    _, docs = docs_on("cmpfo", "recent_tenders.html", "https://cmpfo.gov.in/recent_tenders.html")
    assert len(docs) >= 10
    assert all(d["url"].startswith("https://cmpfo.gov.in/tender/") for d in docs)
    assert "GEM/2026/B/8235901" in docs[0]["context"] and X.find_dates(docs[0]["context"]) == ["2026-11-03"]
    assert "tenders" in X.categorize(docs[0]["text"], docs[0]["context"], docs[0]["url"])


def test_cmpfo_object_embedded_pdf():
    _, docs = docs_on("cmpfo", "cpio_object_embed.html", "https://cmpfo.gov.in/cpio.html")
    assert [d["url"] for d in docs] == ["https://cmpfo.gov.in/pdf/Updated%20cpio%20list.pdf"]


def test_every_section_is_well_formed():
    for org, src in SOURCES.items():
        assert src["target"] and src["probe_url"].startswith("https://") and src["probe_expect"]
        keys = [s["key"] for s in src["sections"]]
        assert len(keys) == len(set(keys)), org
        for s in src["sections"]:
            assert s["seeds"] and all(u.startswith("https://") for u in s["seeds"]), (org, s["key"])
            assert all(X.host_allowed(u, src["hosts"]) for u in s["seeds"]), (org, s["key"])


def test_epfo_circulars_one_page_holds_the_archive():
    _, docs = docs_on("epfo", "circulars.html.gz", "https://www.epfo.gov.in/circulars/")
    assert len(docs) >= 1700                                  # 1884 rows on 2026-11-15
    assert all(X.host_of(d["url"]) in ("pmvbry-cdn.epfindia.gov.in", "www.epfo.gov.in") for d in docs)
    dated = [d for d in docs if X.find_dates(d["context"])]
    assert len(dated) >= 1500
    assert len({d["url"] for d in docs}) == len(docs)


def test_epfo_parliament_questions_skip_hindi_copies():
    _, docs = docs_on("epfo", "parliament-questions.html", "https://www.epfo.gov.in/parliament-questions/")
    assert 50 <= len(docs) <= 80
    assert not any("hindi" in d["url"].lower() for d in docs)
    assert all("parliament" in X.categorize(d["text"], d["context"], d["url"], default=["parliament"]) for d in docs)


def test_epfo_cbt_agenda_and_minutes():
    _, docs = docs_on("epfo", "cbt.html", "https://www.epfo.gov.in/cbt/")
    assert len(docs) >= 90
    cols = {d["column"] for d in docs if "238th" in d["context"]}
    assert cols == {"Agenda", "Minute"}
    minutes = next(d for d in docs if d["column"] == "Minute" and "238th" in d["context"])
    assert "meetings" in X.categorize(minutes["column"], minutes["text"], minutes["context"], minutes["url"])


def test_esic_tender_archive_rows():
    _, docs = docs_on("esic", "tenders-archive.html", "https://esic.gov.in/tenders?tender_type=archive")
    docs = [d for d in docs if not d["chrome"]]
    assert len(docs) >= 20                                    # 20 rows, 1-5 PDFs each
    assert all("/attachments/tenderfile/" in d["url"] for d in docs)
    assert all(X.find_dates(d["context"]) for d in docs)      # publish and last dates in each row
    assert all("tenders" in X.categorize(d["column"], d["text"], d["context"], d["url"], default=["tenders"]) for d in docs)


def test_esic_press_release_cards():
    _, docs = docs_on("esic", "press-releases.html", "https://esic.gov.in/press-release")
    docs = [d for d in docs if not d["chrome"]]
    assert len(docs) >= 20 and all("/attachments/pressfile/" in d["url"] for d in docs)
    assert sum(bool(X.find_dates(d["context"])) for d in docs) >= len(docs) * 0.8


def test_esic_rti_page():
    _, docs = docs_on("esic", "rti.html.gz", "https://esic.gov.in/rti-act")
    assert len([d for d in docs if "/attachments/rtifile/" in d["url"]]) >= 25


def test_items_weekly_backfill_and_pilot():
    import family
    from sources import SOURCES
    esic = family._project("esic", SOURCES["esic"])
    assert len(esic["items"]) == (family.PILOT or len(esic["items"]))
    family_pilot, family.PILOT = family.PILOT, None
    try:
        items = family._project("esic", SOURCES["esic"])["items"]
    finally:
        family.PILOT = family_pilot
    keys = [i["key"] for i in items]
    assert len(keys) == len(set(keys)) and all(len(k) <= 200 for k in keys)
    weekly = [i for i in items if i["key"].startswith(family.WEEK)]
    assert len(weekly) == len(SOURCES["esic"]["sections"]) and items[:len(weekly)] == weekly
    arch = [i for i in items if i["payload"]["section"] == "tenders-archive" and i["key"].startswith(family.ROUND)]
    assert arch[0]["payload"]["pages"] == [1, 10] and arch[-1]["payload"]["pages"][1] == 880
    assert max(i["payload"]["expected"] for i in items) <= 450              # items stay well under the 60-minute assignment


def rows_on(org, name, url):
    f = PAGES / org / name
    raw = gzip.decompress(f.read_bytes()) if name.endswith(".gz") else f.read_bytes()
    return X.table_rows(raw.decode("utf-8", "replace"), url, SOURCES[org].get("chrome_css", ()))


def test_esic_tender_rows_have_named_columns():
    rows = rows_on("esic", "tenders-archive.html", "https://esic.gov.in/tenders?tender_type=archive")
    rows = [r for r in rows if any("tenderfile" in u for u in r["links"])]
    assert len(rows) == 20
    keys = set(rows[0]["cells"])
    assert {"Publish Date", "Last Date"} <= keys and any("Console" in k for k in keys), keys
    assert all(X.find_dates(r["cells"]["Publish Date"]) for r in rows)


def test_cmpfo_and_epfo_tables():
    rows = rows_on("cmpfo", "office_orders.html", "https://cmpfo.gov.in/office_orders.html")
    assert len([r for r in rows if r["links"]]) >= 150
    cbt = rows_on("epfo", "cbt.html", "https://www.epfo.gov.in/cbt/")
    r238 = next(r for r in cbt if "238th" in " ".join(r["cells"].values()))
    assert r238["cells"]["Agenda"] == "View" and r238["cells"]["Date"] == "13-10-25"
    assert [u.rsplit("/", 1)[1] for u in r238["links"]] == ["Agenda_Book_238th_CBT.pdf", "Draft_Minutes_of_238th_CBT.pdf"]
