"""Offline tests of the pure helpers in extract.py (no network, no hub)."""
import extract as X


def test_normalize_drops_fragment_tracking_and_default_port():
    assert X.normalize("HTTPS://WWW.EPFO.gov.in:443/circulars/?utm_source=x&a=1#top") == "https://www.epfo.gov.in/circulars/?a=1"
    assert X.normalize("https://esic.gov.in") == "https://esic.gov.in/"
    assert X.url_id("https://esic.gov.in/#x") == X.url_id("https://esic.gov.in/")


def test_host_rules():
    assert X.host_allowed("https://pmvbry-cdn.epfindia.gov.in/a.pdf", [".epfindia.gov.in"])
    assert X.host_allowed("https://epfindia.gov.in/a.pdf", [".epfindia.gov.in"])
    assert not X.host_allowed("https://evil-epfindia.gov.in/a.pdf", [".epfindia.gov.in"])
    assert not X.host_allowed("https://example.com/a.pdf", ["esic.gov.in"])


def test_document_detection():
    assert X.looks_like_document("https://esic.gov.in/attachments/x/abc.PDF") is True
    assert X.looks_like_document("https://esic.gov.in/tenders") is False
    assert X.looks_like_document("https://esic.gov.in/style.css") is False
    assert X.looks_like_document("https://x.gov.in/Download.aspx?fileid=12") is None
    assert X.is_document_type("application/pdf")
    assert X.is_document_type("text/html", 'attachment; filename="a.pdf"')
    assert not X.is_document_type("text/html; charset=utf-8")
    assert X.ext_from_type("application/octet-stream", 'attachment; filename="Tender 12.xlsx"') == "xlsx"
    assert X.ext_from_type("application/pdf", "", "https://x/y") == "pdf"


def test_scope():
    follow = ["https://esic.gov.in/tenders"]
    assert X.in_scope("https://esic.gov.in/tenders/archive?page=2", follow, [])
    assert not X.in_scope("https://esic.gov.in/recruitments", follow, [])
    assert not X.in_scope("https://esic.gov.in/tenders/hindi", follow, [r"/hindi"])
    assert X.in_scope("https://esic.gov.in/anything", [], [])


def test_dates():
    assert X.find_dates("Circular dated 05/03/2024 and 2023-12-31") == ["2023-12-31", "2024-03-05"]
    assert X.find_dates("issued on 5th March, 2024; corrigendum Mar 7, 2024") == ["2024-03-05", "2024-03-07"]
    assert X.find_dates("31-13-2024 is not a date, nor 00/00/0000") == []


def test_categories():
    c = X.categorize("Corrigendum No. 2 to Tender for housekeeping services", "", "https://esic.gov.in/tenders/x.pdf")
    assert "tenders" in c and "corrigenda" in c
    assert X.categorize("Annual Report 2022-23")[0] == "annual_reports"
    assert X.categorize("Something", default=["circulars"]) == ["circulars"]
    assert X.categorize("") == ["other"]


def test_parse_page_links_rows_and_viewers():
    html = """<html><head><title> Circulars </title></head><body>
      <table><tr><td>12/01/2024</td><td>Rate of interest for 2023-24</td><td><a href="/docs/c1.pdf">Download</a></td></tr></table>
      <ul><li><a href="list?page=2#x">Next</a></li><li><a href="javascript:void(0)" onclick="window.open('/docs/c2.pdf')">View</a></li></ul>
      <iframe src="https://cdn.example.gov.in/v.pdf"></iframe><a href="mailto:a@b">mail</a></body></html>"""
    title, links = X.parse_page(html, "https://www.epfo.gov.in/circulars/")
    assert title == "Circulars"
    urls = [l["url"] for l in links]
    assert urls == ["https://www.epfo.gov.in/docs/c1.pdf", "https://www.epfo.gov.in/circulars/list?page=2",
                    "https://www.epfo.gov.in/docs/c2.pdf", "https://cdn.example.gov.in/v.pdf"]
    row = links[0]["context"]
    assert "Rate of interest" in row and "12/01/2024" in row
    assert X.find_dates(row) == ["2024-01-12"]


def test_ocr_state():
    assert X.ocr_state("pdf") == "pending" and X.ocr_state("csv") == "not_needed"


def test_doc_title_falls_back_to_row_text():
    assert X.doc_title("Download", "12/01/2024 Rate of interest Download") == "12/01/2024 Rate of interest Download"
    assert X.doc_title("Rate of interest", "row") == "Rate of interest"
    assert X.doc_title("(2.1 MB)", "Annual Report") == "Annual Report"


def test_canonical_host_alias():
    assert X.canonical("https://www.cmpfo.gov.in/pdf/a b.pdf#x", {"www.cmpfo.gov.in": "cmpfo.gov.in"}) == "https://cmpfo.gov.in/pdf/a%20b.pdf"


def test_canonical_path_alias():
    al = {"www.epfo.gov.in/wp-content/uploads/": "pmvbry-cdn.epfindia.gov.in"}
    assert X.canonical("https://www.epfo.gov.in/wp-content/uploads/2025/11/a.pdf", al) == \
        "https://pmvbry-cdn.epfindia.gov.in/wp-content/uploads/2025/11/a.pdf"
    assert X.canonical("https://www.epfo.gov.in/circulars/", al) == "https://www.epfo.gov.in/circulars/"


def test_sitemap():
    xml = '<?xml version="1.0"?><urlset xmlns="x"><url><loc>https://www.epfo.gov.in/notices/a/</loc></url>' \
          '<url><loc><![CDATA[https://www.epfo.gov.in/notices/b/]]></loc></url></urlset>'
    assert X.parse_sitemap(xml) == ["https://www.epfo.gov.in/notices/a/", "https://www.epfo.gov.in/notices/b/"]
    assert X.parse_sitemap("<html></html>") is None


def test_menu_links_are_marked_chrome():
    html = '<body><nav><a href="/m.pdf">Menu doc</a></nav><div class="footer-links"><a href="/f.pdf">F</a></div>' \
           '<main><table><tr><td><a href="/r.pdf">Row doc</a></td></tr></table></main></body>'
    _, links = X.parse_page(html, "https://x.gov.in/")
    assert {l["url"].rsplit("/", 1)[1]: l["chrome"] for l in links} == {"m.pdf": True, "f.pdf": True, "r.pdf": False}
    assert X.doc_title("📄 (1387.2 KB)", "RFP for portfolio managers") == "RFP for portfolio managers"


def test_row_id_prefers_reference_number_and_ignores_archive_suffix():
    row = {"cells": {"Subject": "GeM bid", "Console Sl. No.": "17646/2026"}, "links": ["https://esic.gov.in/a.pdf"]}
    assert X.row_id("tenders", row) == X.row_id("tenders-archive", row)
    other = {"cells": {"Subject": "GeM bid", "Console Sl. No.": "17647/2026"}, "links": ["https://esic.gov.in/a.pdf"]}
    assert X.row_id("tenders", row) != X.row_id("tenders", other)
    nolink = {"cells": {"Name": "Office A", "City": "Delhi"}, "links": []}
    assert X.row_id("directory", nolink) == X.row_id("directory", {"cells": dict(nolink["cells"]), "links": []})
