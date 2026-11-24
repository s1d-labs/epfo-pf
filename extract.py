"""Pure helpers for the harvest task: URL rules, link extraction, document detection, categories and dates.

Nothing here touches the network or the hub, so tests/test_extract.py runs on saved pages without either.
"""
import hashlib
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

# file extensions that are documents (stored in the bucket for later OCR / parsing), not pages to crawl
DOC_EXT = {
    "pdf", "doc", "docx", "rtf", "odt", "xls", "xlsx", "xlsm", "ods", "csv", "ppt", "pptx", "odp", "txt", "xml",
    "zip", "rar", "7z", "gz", "jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "webp",
}
SKIP_EXT = {"css", "js", "ico", "svg", "woff", "woff2", "ttf", "eot", "mp3", "mp4", "avi", "mov", "wmv", "flv", "exe", "apk", "msi"}
DOC_TYPES = (
    "application/pdf", "application/msword", "application/vnd.", "application/zip", "application/x-zip", "application/x-rar",
    "application/rtf", "application/octet-stream", "application/x-7z", "application/gzip", "text/csv", "text/plain",
    "text/xml", "application/xml", "image/",
)
# image types that need OCR; spreadsheets, CSV and text files are already machine-readable
OCR_EXT = {"pdf", "jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "webp", "doc", "docx", "rtf", "odt", "ppt", "pptx", "odp"}
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "_ga"}


def normalize(url):
    """Canonical form of a URL: lower-case scheme and host, no fragment, no tracking parameters, no default port, a path."""
    url = url.strip().replace("\\", "/").replace(" ", "%20")
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if p.port and not ((p.scheme == "http" and p.port == 80) or (p.scheme == "https" and p.port == 443)):
        host = f"{host}:{p.port}"
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS])
    return urlunsplit((p.scheme.lower(), host, p.path or "/", query, ""))


def url_id(url):
    """Stable id of a URL (40 hex chars): the record id and the bucket file name both use it."""
    return hashlib.sha1(normalize(url).encode()).hexdigest()


def host_of(url):
    return (urlsplit(url).hostname or "").lower()


def host_allowed(url, hosts):
    """True when the URL's host is one of `hosts` or a subdomain of one that starts with '.' (e.g. '.esic.gov.in')."""
    h = host_of(url)
    for a in hosts:
        a = a.lower()
        if h == a.lstrip(".") or (a.startswith(".") and h.endswith(a)):
            return True
    return False


def ext_of(url):
    path = urlsplit(url).path.lower()
    last = path.rsplit("/", 1)[-1]
    return last.rsplit(".", 1)[-1] if "." in last else ""


def looks_like_document(url):
    """Decide from the URL alone: True = document, False = page or asset, None = unknown (the answer's Content-Type decides)."""
    e = ext_of(url)
    if e in DOC_EXT:
        return True
    if e in SKIP_EXT:
        return False
    q = urlsplit(url).query.lower()
    if re.search(r"(^|&)(download|file|attachment|doc)(_?id)?=", q) or re.search(r"/(download|getfile|viewfile|showfile)", url.lower()):
        return None
    return False


def is_document_type(content_type, disposition=""):
    ct = (content_type or "").split(";")[0].strip().lower()
    if "attachment" in (disposition or "").lower():
        return True
    return ct.startswith(DOC_TYPES) and not ct.startswith(("text/html", "application/xhtml"))


def ext_from_type(content_type, disposition="", url=""):
    """File extension for the bucket: from the file name in Content-Disposition, the URL, or the Content-Type."""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', disposition or "", re.I)
    for name in ([m.group(1)] if m else []) + [urlsplit(url).path]:
        e = name.rsplit(".", 1)[-1].lower() if "." in name.rsplit("/", 1)[-1] else ""
        if e in DOC_EXT:
            return e
    ct = (content_type or "").split(";")[0].strip().lower()
    table = {"application/pdf": "pdf", "application/msword": "doc", "application/vnd.ms-excel": "xls", "text/csv": "csv",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
             "application/vnd.ms-powerpoint": "ppt", "application/zip": "zip", "image/jpeg": "jpg", "image/png": "png",
             "image/gif": "gif", "image/tiff": "tif", "text/plain": "txt", "application/xml": "xml", "text/xml": "xml"}
    return table.get(ct, "bin")


def in_scope(url, follow_prefixes, exclude):
    """A page URL the crawler may follow: it starts with one of `follow_prefixes` (any when empty) and matches no `exclude` regex."""
    n = normalize(url)
    if any(re.search(x, n, re.I) for x in exclude):
        return False
    if not follow_prefixes:
        return True
    return any(n.startswith(normalize(p).rstrip("/")) for p in follow_prefixes)


def clean(text, limit=None):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t[:limit] if limit else t


ROW_TAGS = ("tr", "li", "dd", "dt", "p", "article", "section", "div")


def _row_text(a):
    """Text of the smallest table row / list item / paragraph around a link: it holds the title, number and date of the document."""
    node = a
    for _ in range(6):
        node = node.parent
        if node is None or node.name in ("body", "html", "[document]"):
            break
        if node.name in ROW_TAGS:
            t = clean(node.get_text(" "))
            if len(t) >= len(clean(a.get_text(" "))) + 3 or node.name in ("tr", "li"):
                return t[:600]
    return ""


def _column(a):
    """Header text of the table column that holds the link ('Agenda', 'Minute', 'English', ...), or ''."""
    td = a.find_parent(["td", "th"])
    tr = td.find_parent("tr") if td else None
    table = tr.find_parent("table") if tr else None
    if table is None:
        return ""
    idx = 0
    for cell in tr.find_all(["td", "th"], recursive=False):
        if cell is td:
            break
        idx += int(cell.get("colspan", 1) or 1) if str(cell.get("colspan", "1")).isdigit() else 1
    head = table.find("thead")
    hrow = head.find("tr") if head else None
    if hrow is None:
        first = table.find("tr")
        hrow = first if first is not None and first is not tr and first.find("th") else None
    if hrow is None:
        return ""
    pos = 0
    for cell in hrow.find_all(["th", "td"], recursive=False):
        span = int(cell.get("colspan", 1)) if str(cell.get("colspan", "1")).isdigit() else 1
        if pos <= idx < pos + span:
            return clean(cell.get_text(" "), 80)
        pos += span
    return ""


CHROME_TAGS = ("header", "nav", "footer")
CHROME_CLASS = re.compile(r"(^|[\s_-])(header|navbar|nav|menu|megamenu|footer|breadcrumb|top-?bar|skip|social|sidebar)([\s_-]|$)", re.I)


def _in_chrome(a):
    """True for links in the site's header, menus, footer or sidebar: the same on every page, not part of the listing."""
    for node in a.parents:
        if node.name in ("body", "html", "[document]", "main"):
            return False
        if node.name in CHROME_TAGS:
            return True
        ident = " ".join(node.get("class", []) or []) + " " + (node.get("id") or "")
        if CHROME_CLASS.search(ident) or node.get("role") in ("navigation", "banner", "contentinfo"):
            return True
    return False


def parse_page(html, base_url, chrome_css=()):
    """(title, links) of an HTML page. chrome_css: CSS selectors of the site's own menu areas (links in them get chrome=True). links: [{"url", "text", "context"}] in page order, unique by URL, absolute, no fragments.

    Also reads iframe/embed/object sources (PDF viewers) and onclick="window.open('...')" handlers."""
    soup = BeautifulSoup(html, "lxml")
    base = soup.find("base", href=True)
    base_url = urljoin(base_url, base["href"]) if base else base_url
    title = clean(soup.title.get_text(" ")) if soup.title else ""
    out, seen = [], set()
    menu = {id(a) for sel in chrome_css for box in soup.select(sel) for a in box.find_all("a")}

    def add(raw, text, context, column="", chrome=False):
        raw = (raw or "").strip()
        if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return
        u = normalize(urljoin(base_url, raw))
        if not u.startswith(("http://", "https://")) or u in seen:
            return
        seen.add(u)
        out.append({"url": u, "text": clean(text, 300), "context": context, "column": column, "chrome": chrome})

    for a in soup.find_all("a"):
        text = a.get_text(" ") or a.get("title", "") or a.get("aria-label", "")
        ctx, col, chrome = _row_text(a), _column(a), id(a) in menu or _in_chrome(a)
        if a.get("href"):
            add(a["href"], text, ctx, col, chrome)
        m = re.search(r"""(?:window\.open|location\.href\s*=)\s*\(?\s*['"]([^'"]+)['"]""", a.get("onclick", "") or "")
        if m:
            add(m.group(1), text, ctx, col, chrome)
    for tag, attr in (("iframe", "src"), ("embed", "src"), ("object", "data"), ("frame", "src"), ("area", "href")):
        for el in soup.find_all(tag):
            if el.get(attr):
                add(el[attr], el.get("title", "") or el.get("alt", ""), "")
    return title, out


# category rules: (slug, regex on "anchor text | row text | URL | section title"); a link may get several
CATEGORY_RULES = [
    ("tenders", r"tender|\bnit\b|\brfp\b|\brfq\b|\beoi\b|expression of interest|request for (proposal|quotation)|e-?procure|bid\b|bids\b|bidder|"
                r"quotation|corrigend|addend|re-?tender|cancell?ation of tender|\bboq\b|bill of quantit|rate contract|empanel|"
                r"work order|purchase order|letter of award|\bloa\b|contract award|award of contract|gem\b|निविदा"),
    ("tender_results", r"technical bid|financial bid|bid (opening|evaluation)|result of tender|tender result|\bl-?1\b|comparative statement|"
                       r"award of contract|contract award|letter of award|work order|purchase order|successful bidder"),
    ("corrigenda", r"corrigend|addend|amendment to tender|extension of (bid|tender|date)|cancell?ation|re-?tender|शुद्धिपत्र"),
    ("acts_rules", r"\bact\b|\bacts\b|regulation|\brules?\b|amendment|gazette|ordinance|statut|अधिनियम|नियम"),
    ("schemes_policies", r"scheme|policy|policies|guideline|manual|procedure|charter|sop\b|योजना|नीति"),
    ("circulars", r"circular|परिपत्र"),
    ("office_orders", r"office order|office memorand|\bo\.?m\.?\b|order no|कार्यालय आदेश"),
    ("notifications", r"notification|notice|अधिसूचना|सूचना"),
    ("press_releases", r"press release|press note|press|media|news|प्रेस"),
    ("annual_reports", r"annual report|वार्षिक रिपोर्ट|वार्षिक प्रतिवेदन"),
    ("periodic_reports", r"monthly|quarterly|half[- ]yearly|payroll|bulletin|newsletter|मासिक|त्रैमासिक"),
    ("financial_statements", r"financial statement|annual accounts?|balance sheet|income (and|&) expenditure|receipts? (and|&) payments?|"
                             r"budget|revised estimate|\bbe\b|\bre\b|expenditure|outlay|grant|बजट|लेखा"),
    ("investments", r"invest|portfolio|fund manager|\betf\b|securities|corpus|interest rate|rate of interest|निवेश"),
    ("statistics", r"statistic|data\b|figures|claims? settle|settlement|contribut|subscriber|member(s)? count|pensioner|beneficiar|"
                   r"insured persons|\bip\b|coverage|सांख्यिकी"),
    ("audit", r"audit|\bcag\b|comptroller|inspection report|para\b|paras\b|लेखापरीक्षा"),
    ("parliament", r"parliament|lok sabha|rajya sabha|starred|unstarred|question|committee on|standing committee|\bpac\b|संसद"),
    ("vigilance", r"vigilance|\bcvc\b|\bcvo\b|integrity pact|complaint|सतर्कता"),
    ("recruitment", r"recruit|vacanc|career|deputation|walk-?in|admit card|selected candidates|interview (schedule|result)|"
                    r"\bexam(ination)? (result|notice|schedule)|भर्ती|रिक्ति"),
    ("directory", r"directory|contact (us|details)|addresses|office(s)? list|who'?s who|telephone|निर्देशिका"),
    ("org_structure", r"organi[sz]ation(al)? (structure|chart)|organogram|hierarchy|board of trustees|\bcbt\b|corporation members|"
                      r"about us|functions|delegation of powers|संगठन"),
    ("vendors_debarment", r"debar|blacklist|black-list|banned|suspension of business|not of standard quality|\bnsq\b|empanell?ed|"
                          r"empanell?ment|termination of (agreement|contract)|registered (firms|vendors|agencies)|approved vendors"),
    ("meetings", r"minutes|agenda|meeting|proceedings|बैठक|कार्यवृत्त"),
    ("rti", r"\brti\b|right to information|4\(1\)\(b\)|suo moto|suo motu|सूचना का अधिकार"),
    ("payments", r"payment|paid|bills? (passed|paid)|disbursement|sanction|release of fund|भुगतान"),
]
_RULES = [(slug, re.compile(rx, re.I)) for slug, rx in CATEGORY_RULES]


def categorize(*texts, default=()):
    """Category slugs for a link, from its anchor text, row text, URL and the section's own categories (`default`)."""
    blob = " | ".join(t for t in texts if t)
    found = [slug for slug, rx in _RULES if rx.search(blob)]
    out = list(dict.fromkeys([*default, *found]))
    return out or ["other"]


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_D_NUM = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b")
_D_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_D_TXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[ \-.,]*(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?[ \-.,]*(\d{4})\b", re.I)
_D_TXT2 = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?[ \-]*(\d{1,2})(?:st|nd|rd|th)?,?[ \-]*(\d{4})\b", re.I)


def _ok(y, m, d):
    try:
        x = date(y, m, d)
    except ValueError:
        return None
    return x.isoformat() if 1950 <= y <= 2100 else None


def find_dates(text):
    """ISO dates written in the text (dd/mm/yyyy, dd-mm-yy, yyyy-mm-dd, 5 March 2024, March 5, 2024), in order, unique."""
    out = []
    t = text or ""
    for m in _D_ISO.finditer(t):
        out.append(_ok(int(m[1]), int(m[2]), int(m[3])))
    for m in _D_NUM.finditer(t):
        y = int(m[3]) if len(m[3]) == 4 else 2000 + int(m[3])
        out.append(_ok(y, int(m[2]), int(m[1])))            # Indian sites write day first
    for m in _D_TXT.finditer(t):
        out.append(_ok(int(m[3]), MONTHS[m[2][:3].lower()], int(m[1])))
    for m in _D_TXT2.finditer(t):
        out.append(_ok(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])))
    return list(dict.fromkeys(d for d in out if d))


def ocr_state(ext):
    """'pending' for scans and office files that a later OCR / text step reads, 'not_needed' for data files."""
    return "pending" if ext in OCR_EXT else "not_needed"


GENERIC = re.compile(r"^(download|view|click here|here|pdf|open|read more|more|details?|link|file|size.*|\(?\d+(\.\d+)?\s*[km]b\)?|"
                     r"english|hindi|डाउनलोड|देखें|हिंदी)\W*$", re.I)


def doc_title(text, context):
    """The document's title: the link text, or the row text when the link only says 'Download', 'View', '(2.1 MB)' ..."""
    t = clean(text)
    bare = clean(re.sub(r"[^\w\s().,-]", " ", t))           # without icons and emoji
    if bare and not GENERIC.match(bare) and len(bare) > 3:
        return t
    return clean(context, 300) or t


def canonical(url, aliases):
    """The URL, normalized, with its host replaced by the canonical host. aliases: {"www.x.gov.in": "x.gov.in"} for a whole host,
    or {"www.x.gov.in/wp-content/uploads/": "cdn.x.gov.in"} for one path prefix (the same files served by several hosts)."""
    n = normalize(url)
    p = urlsplit(n)
    h = (p.hostname or "").lower()
    for key, target in aliases.items():
        kh, _, kp = key.partition("/")
        if h == kh and p.path.startswith("/" + kp):
            return urlunsplit((p.scheme, target, p.path, p.query, ""))
    return n


def parse_sitemap(xml):
    """URLs in a sitemap or sitemap index (<loc>), or None when the text is not a sitemap."""
    head = xml[:2000].lower()
    if "<urlset" not in head and "<sitemapindex" not in head:
        return None
    return [normalize(u) for u in re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)", xml)]


def _cells(tr):
    """(cell, colspan) of a table row, direct children only."""
    out = []
    for c in tr.find_all(["td", "th"], recursive=False):
        span = c.get("colspan", "1")
        out.append((c, int(span) if str(span).isdigit() else 1))
    return out


def table_rows(html, base_url, chrome_css=()):
    """Rows of every table that has a header row, as [{"cells": {header: text}, "links": [url, ...]}].

    Header names come from <thead> or from a first row of <th>. Rows without any text are skipped, and so are tables in the
    site's menus. Pure: tests run it on saved pages."""
    soup = BeautifulSoup(html, "lxml")
    menu = {id(t) for sel in chrome_css for box in soup.select(sel) for t in box.find_all("table")}
    out = []
    for table in soup.find_all("table"):
        if id(table) in menu or table.find_parent(CHROME_TAGS):
            continue
        rows = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
        head = table.find("thead")
        hrow = head.find("tr") if head else (rows[0] if rows and rows[0].find("th") and not rows[0].find("td") else None)
        if hrow is None:
            continue
        names = []
        for c, span in _cells(hrow):
            n = clean(c.get_text(" "), 60) or f"col{len(names) + 1}"
            names += [n] * span if span > 1 else [n]
        seen = {}
        for i, n in enumerate(names):                         # unique names: "Hindi", "Hindi_2"
            seen[n] = seen.get(n, 0) + 1
            names[i] = n if seen[n] == 1 else f"{n}_{seen[n]}"
        for tr in rows:
            if tr is hrow or tr.find_parent("thead"):
                continue
            cells, pos = {}, 0
            for c, span in _cells(tr):
                if pos < len(names):
                    t = clean(c.get_text(" "), 600)
                    if t:
                        cells[names[pos]] = t
                pos += span
            if not cells:
                continue
            links = []
            for a in tr.find_all(["a", "object", "iframe"]):
                raw = (a.get("href") or a.get("data") or a.get("src") or "").strip()
                if raw and not raw.startswith(("#", "javascript:", "mailto:", "tel:")):
                    u = normalize(urljoin(base_url, raw))
                    if u not in links:
                        links.append(u)
            out.append({"cells": cells, "links": links})
    return out


ROW_ID_HEADER = re.compile(r"console|reference|ref\.? ?no|tender (id|no)|bid no|circular no|order no", re.I)


def row_id(section, row, aliases=None):
    """Stable record id of a table row: the row's own reference number (ESIC 'Console Sl. No.') when it has one, else its first
    link, else its text. The id ignores the page and an '-archive' suffix of the section, so a row that moves from the current
    list to the archive keeps its id."""
    base = re.sub(r"-archive$", "", section)
    ref = next((v for k, v in row["cells"].items() if ROW_ID_HEADER.search(k) and v and v != "View"), None)
    key = ref or (canonical(row["links"][0], aliases or {}) if row["links"] else " | ".join(row["cells"].values()))
    return "row:" + hashlib.sha1(f"{base}|{key}".encode()).hexdigest()
