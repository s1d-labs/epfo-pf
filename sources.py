"""The sites and sections this family crawls. One entry per organisation; one queue item per section.

Organisation keys:
  title, target (host for the hub's per-site limits), probe_url, probe_expect (health check), hosts (page hosts; a leading '.'
  allows subdomains), doc_hosts (extra hosts for documents only), aliases (host -> canonical host, for de-duplication),
  ca_bundle (True when the server does not send its intermediate certificate), proxy ("IN" when the site refuses GitHub runners),
  threads / delay_ms / max_workers (speed in the pool), exclude (regexes of URLs never to follow), enabled, sections.
Section keys:
  key, title, categories (default categories of its documents), seeds, follow (URL prefixes the crawler may follow; [] = any page on
  the hosts), exclude, max_pages, max_depth, max_docs (0 = no limit), expected (records, for progress on the dashboard).

Site maps were made on 2026-11-15 from the box (Mumbai). Categories: see extract.CATEGORY_RULES.
"""

SOCIAL = r"facebook\.com|twitter\.com|x\.com/|instagram\.com|youtube\.com|linkedin\.com|threads\.(net|com)|whatsapp\.com|t\.me/"
COMMON_EXCLUDE = [
    r"login|signin|sign-in|logout|register\.(html|aspx|php)|captcha", r"/(wp-admin|wp-login|wp-json|xmlrpc\.php|feed)/?",
    r"[?&](print|share|replytocom|lang)=", r"/(search|print)(/|\?|$)", r"\.(css|js|ico|svg|woff2?|ttf|mp4|mp3)(\?|$)", SOCIAL,
    r"photo[-_]?gallery|video[-_]?gallery|/gallery", r"/calendar|/event-calendar",
]


def _cm(path):
    return f"https://cmpfo.gov.in/{path}"


CMPFO = {
    "title": "CMPFO public records (cmpfo.gov.in)",
    "target": "cmpfo.gov.in",
    "probe_url": "https://cmpfo.gov.in/office_orders.html",
    "probe_expect": "Office Order",
    "hosts": ["cmpfo.gov.in", "www.cmpfo.gov.in"],
    "aliases": {"www.cmpfo.gov.in": "cmpfo.gov.in"},
    "ca_bundle": True,                    # the server does not send the GlobalSign GCC R46 intermediate
    "proxy": "",                          # answers from the US and Europe (check-host.net, 2026-11-15)
    "threads": 1, "delay_ms": 1500, "max_workers": 1,
    "exclude": COMMON_EXCLUDE + [
        r"_login\.html", r"ccares\.cdacb\.in|saccess\.nic\.in|pgportal\.gov\.in|portal\.cvc\.gov\.in|starrating\.coal\.gov\.in|jeevanpramaan",
        r"cmpfo\.gov\.in/h[a-z_]+\.html$",   # the Hindi mirror pages: older subsets of the English pages
        r"/(red|green|assets|theme|extraassets|extratheme)/", r"/(sitemap|header|footer|hfooter|hyperlinking_policy|privacy_policy|"
        r"terms_and_conditions|web_information_manager|SMH|FAQ|citizen_charter|budget)\.html",
    ],
    "sections": [
        {"key": "office-orders", "title": "Office orders and memoranda", "categories": ["office_orders"],
         "seeds": [_cm("office_orders.html")], "follow": [_cm("office_orders.html")], "max_pages": 3, "max_depth": 0, "expected": 165},
        {"key": "tenders", "title": "Tenders", "categories": ["tenders"],
         "seeds": [_cm("recent_tenders.html"), _cm("awarded_tenders.html")],
         "follow": [_cm("recent_tenders.html"), _cm("awarded_tenders.html")], "max_pages": 4, "max_depth": 0, "expected": 15},
        {"key": "disclosures", "title": "Acts, schemes, Parliament questions, audit ATR and RTI disclosures (menu 'BOT')",
         "categories": [], "seeds": [_cm("bot.html")], "follow": [_cm("bot.html")], "max_pages": 2, "max_depth": 0, "expected": 20},
        {"key": "rti", "title": "RTI: proactive disclosure, CPIO list, brief", "categories": ["rti"],
         "seeds": [_cm("proactive_disclosure.html"), _cm("cpio.html"), _cm("brief.html")], "follow": [_cm("cpio.html")],
         "max_pages": 4, "max_depth": 0, "expected": 5},
        {"key": "acts-schemes", "title": "CMPF Act, CMPS 1998, CMPF Scheme, CMDLI Scheme, draft rules",
         "categories": ["acts_rules", "schemes_policies"],
         "seeds": [_cm("cmpf_act1.html"), _cm("cmps_act1.html"), _cm("cmpfs.html"), _cm("cmdlis.html"), _cm("draft_rules.html")],
         "follow": [_cm("cmpf_act"), _cm("cmps_act")], "max_pages": 25, "max_depth": 2, "expected": 25},
        {"key": "reports", "title": "Monthly progress reports and annual reports", "categories": ["periodic_reports"],
         "seeds": [_cm("monthly_report.html"), _cm("annual_report.html")], "follow": [_cm("monthly_report.html")],
         "max_pages": 3, "max_depth": 0, "expected": 12},
        {"key": "recruitment", "title": "Recruitment", "categories": ["recruitment"],
         "seeds": [_cm("recruitment.html")], "follow": [_cm("recruitment.html")], "max_pages": 2, "max_depth": 0, "expected": 10},
        {"key": "forms-manuals", "title": "Forms, manuals, SOPs", "categories": ["schemes_policies"],
         "seeds": [_cm("forms.html"), _cm("manual.html")], "follow": [_cm("forms.html")], "max_pages": 3, "max_depth": 0,
         "expected": 15},
        {"key": "news", "title": "What's new, press releases, events, announcements", "categories": [],
         "seeds": [_cm("new.html"), _cm("press_release.html"), _cm("events.html"), _cm("announcements.html"), _cm("e_book.html"), _cm("")],
         "follow": [_cm("new.html")], "chrome": True, "max_pages": 7, "max_depth": 0, "expected": 8},
        {"key": "vigilance", "title": "Vigilance", "categories": ["vigilance"],
         "seeds": [_cm("meet_cvo.html"), _cm("vig_functions.html"), _cm("vig_objectives.html"), _cm("vigilance.html")],
         "follow": [_cm("vigilance.html")], "max_pages": 5, "max_depth": 0, "expected": 5},
        {"key": "org-directory", "title": "Organisation, offices and directories", "categories": ["org_structure"],
         "seeds": [_cm(p) for p in ("cmpf_india.html", "corporate_profile.html", "operation.html", "meet_cmpf_commissioner.html",
                                    "for_employees.html", "apr.html", "contact_us.html", "grievance.html", "iccwomen.html")],
         "follow": [_cm("operation.html")], "max_pages": 10, "max_depth": 0, "expected": 15},
        {"key": "rajbhasha", "title": "Official language (Rajbhasha) documents", "categories": ["acts_rules"],
         "seeds": [_cm("Rajbhasha%20Corner.html")], "follow": [_cm("Rajbhasha")], "max_pages": 2, "max_depth": 0, "expected": 8},
    ],
}

def _ep(path):
    return f"https://www.epfo.gov.in/{path}"


EPFO = {
    "title": "EPFO public records (epfo.gov.in)",
    "target": "www.epfo.gov.in",
    "probe_url": "https://www.epfo.gov.in/tender-notices/",
    "probe_expect": "Tender",
    "hosts": ["www.epfo.gov.in", "www.epfindia.gov.in"],
    "doc_hosts": ["pmvbry-cdn.epfindia.gov.in", "pmvbry.epfindia.gov.in"],
    # the same uploads are served by three hosts (checked 2026-11-15: same size and dates); keep one name per file
    "aliases": {"www.epfindia.gov.in": "www.epfo.gov.in",
                "www.epfo.gov.in/wp-content/uploads/": "pmvbry-cdn.epfindia.gov.in",
                "pmvbry.epfindia.gov.in/wp-content/uploads/": "pmvbry-cdn.epfindia.gov.in"},
    "ca_bundle": False,
    "proxy": "IN",                        # CloudFront answers 403 outside India (check-host.net US/DE/NL, 2026-11-15)
    "threads": 2, "delay_ms": 1000, "max_workers": 2,
    "exclude": COMMON_EXCLUDE + [
        r"unifiedportal-|passbook\.|mis\.epfindia|epfigms|iwu\.epfindia|epfoiwu|epfoportals|hr\.epfindia|eproceedings|esamiksha|"
        r"email\.gov\.in|rcil\.gov\.in|shramsuvidha|umang\.gov|rtionline|jeevanpramaan|epf6\.in",
        r"[?&]s=", r"/(events|event_category|creatives|video|videos-epfo|youtube-videos|outreach_activities|journey|author|post_tag|"
        r"category|faq|feedback|contact-us)/",
        r"/(payroll|parliament_questions|downloads-miscell|cbt_data|internationalworkers|exempted-estt|for_office_use|abry|jobs|"
        r"tender_auction|appointments|claim_form_questions|faq_epfo)/",            # custom-post singles: empty shells
        r"/press-release/[^/]+/", r"/directory/[^/]+/", r"/slider-\d", r"lorem-ipsum", r"/site_en/|/site_docs/|/documents/|/office-use/",
        r"pmvbry\.epfindia\.gov\.in/(?!wp-content/uploads/)",
    ],
    "doc_exclude": [r"[_-]hindi[^/]*\.pdf$", r"/wp-content/(plugins|themes/[^/]+/(?!assets/pdfs/))", r"\.(png|jpe?g|gif|svg|webp)$"],
    "sections": [
        {"key": "circulars", "title": "Circulars, office orders, gazette notifications (2006 onwards)",
         "categories": ["circulars"], "seeds": [_ep("circulars/")], "max_pages": 2, "max_depth": 0, "expected": 1890},
        {"key": "tenders", "title": "Tender notices and notices", "categories": ["tenders"],
         "seeds": [_ep("tender-notices/")], "max_pages": 2, "max_depth": 0, "expected": 15},
        {"key": "notices", "title": "Notices (single pages with attachments)", "categories": ["notifications"],
         "seeds": [_ep("notices-sitemap.xml")], "follow": [_ep("notices/")], "max_pages": 40, "max_depth": 0, "expected": 30},
        {"key": "cbt", "title": "Central Board of Trustees and Executive Committee: agenda and minutes", "categories": ["meetings"],
         "seeds": [_ep("cbt/")], "max_pages": 2, "max_depth": 0, "expected": 105},
        {"key": "annual-reports", "title": "Annual reports (1952 onwards)", "categories": ["annual_reports"],
         "seeds": [_ep("annual-reports/")], "max_pages": 2, "max_depth": 0, "expected": 72},
        {"key": "annual-accounts", "title": "Consolidated annual accounts", "categories": ["financial_statements"],
         "seeds": [_ep("annual-accounts/")], "max_pages": 2, "max_depth": 0, "expected": 41},
        {"key": "payroll", "title": "Monthly payroll data", "categories": ["periodic_reports", "statistics"],
         "seeds": [_ep("data-hub/")], "max_pages": 2, "max_depth": 0, "expected": 58},
        {"key": "press-releases", "title": "Press releases", "categories": ["press_releases"],
         "seeds": [_ep("press-release/")], "max_pages": 2, "max_depth": 0, "expected": 68},
        {"key": "publications", "title": "Newsletters, state profile booklets, e-books, study reports", "categories": ["periodic_reports"],
         "seeds": [_ep("publications/"), _ep("state-profile-booklet/"), _ep("e-books/"), _ep("study-reports/")],
         "max_pages": 5, "max_depth": 0, "expected": 35},
        {"key": "parliament-questions", "title": "Parliament questions, compiled per session", "categories": ["parliament"],
         "seeds": [_ep("parliament-questions/")], "max_pages": 2, "max_depth": 0, "expected": 78},
        {"key": "manuals-rules", "title": "Manuals, guidelines, recruitment rules, service regulations", "categories": ["acts_rules"],
         "seeds": [_ep("manuals-and-guidelines/"), _ep("unified-portal/")], "max_pages": 3, "max_depth": 0, "expected": 150},
        {"key": "acts-schemes", "title": "Act, schemes, forms and archives", "categories": ["acts_rules", "schemes_policies"],
         "seeds": [_ep(p) for p in ("downloads/", "epf-mp-act-1952/", "epf-scheme/", "pension-scheme-eps/", "insurance-scheme-edli/",
                                    "archives/", "employer-documents/", "employee-documents/", "ease-of-doing-business/",
                                    "revamped-ecr/", "about-us/", "")],
         "chrome": True, "max_pages": 13, "max_depth": 0, "expected": 75},
        {"key": "exempted-establishments", "title": "Exempted establishments: list, monthly performance, notifications",
         "categories": ["statistics"], "seeds": [_ep("exempted-establishments/")], "max_pages": 2, "max_depth": 0, "expected": 137},
        {"key": "recruitment", "title": "Recruitment and archive", "categories": ["recruitment"],
         "seeds": [_ep("recruitments/"), _ep("archive-recruitments/")], "follow": [_ep("archive-recruitments/page/")],
         "max_pages": 6, "max_depth": 2, "expected": 16},
        {"key": "appointments", "title": "Appointments, transfers and postings", "categories": ["office_orders"],
         "seeds": [_ep("appointments-transfers-postings/")], "max_pages": 2, "max_depth": 0, "expected": 3},
        {"key": "directory", "title": "Office directory, office locations, EPFO corner", "categories": ["directory"],
         "seeds": [_ep("directory/"), _ep("locate-epfo-office/"), _ep("epfo-corner/")], "max_pages": 4, "max_depth": 0, "expected": 4},
        {"key": "rti", "title": "RTI", "categories": ["rti"], "seeds": [_ep("rti-epfo/")], "max_pages": 2, "max_depth": 0, "expected": 6},
    ],
}


def _es(path):
    return f"https://esic.gov.in/{path}"


def _paged(path, last, chunk, per_page, query="", weekly=2):
    """A long paged list: one backfill item per `chunk` listing pages (about 300 documents, under 30 minutes), and a weekly item
    for pages 1..`weekly` (the newest rows). `last` has a margin: pages past the end are empty."""
    return {"url": _es(path) + "/index/page:{n}" + query, "last": last, "chunk": chunk, "per_page": per_page, "weekly": weekly}


ESIC = {
    "title": "ESIC public records (esic.gov.in)",
    "target": "esic.gov.in",
    "probe_url": "https://esic.gov.in/esi-acts",
    "probe_expect": "Act",
    "hosts": ["esic.gov.in", "www.esic.gov.in"],
    "aliases": {"www.esic.gov.in": "esic.gov.in"},
    "ca_bundle": False,
    "proxy": "IN",                        # times out outside India (check-host.net US/DE/NL, 2026-11-15)
    "threads": 2, "delay_ms": 2000, "max_workers": 3,         # pages take 3-20 s: keep the load low
    "exclude": COMMON_EXCLUDE + [
        r"/pages/changelangro", r"/index/clear-search", r"/officers/", r"officelogin", r"portal\.esic\.gov\.in", r"esic\.in/",
        r"analytics\.esic", r"mimpscheme", r"/feedback", r"/photo-album", r"/video-gallery", r"/404", r"/documents", r"actionplan\.php",
        r"/CIRCULARS/", r"/index/(state|office|key|from|to|subject|division):", r"/attachments/photos/",
    ],
    "chrome_css": ["div._expendTAB"],    # the left menu on every page (citizen's charter, holidays ...)
    "doc_exclude": [r"/attachments/photos/", r"\.(png|jpe?g|gif|svg|webp)$"],
    "sections": [
        {"key": "tenders", "title": "Tenders: current list", "categories": ["tenders"],
         "seeds": [_es("tenders")], "paged": _paged("tenders", 15, 15, 30, weekly=15)},
        {"key": "tenders-archive", "title": "Tenders: archive (2014 onwards)", "categories": ["tenders"],
         "seeds": [_es("tenders?tender_type=archive")], "paged": _paged("tenders", 880, 10, 30, "?tender_type=archive", weekly=3)},
        {"key": "circulars", "title": "Circulars and office orders: last 12 months", "categories": ["circulars"],
         "seeds": [_es("circulars")], "paged": _paged("circulars", 80, 20, 15, weekly=8)},
        {"key": "circulars-archive", "title": "Circulars and office orders: archive (2015 onwards)", "categories": ["circulars"],
         "seeds": [_es("circulars?circular_type=archive")], "paged": _paged("circulars", 450, 10, 28, "?circular_type=archive", weekly=2)},
        {"key": "recruitments", "title": "Recruitment: current list", "categories": ["recruitment"],
         "seeds": [_es("recruitments")], "paged": _paged("recruitments", 40, 20, 15, weekly=8)},
        {"key": "recruitments-archive", "title": "Recruitment: archive (2015 onwards)", "categories": ["recruitment"],
         "seeds": [_es("recruitments?recruitment_type=archive")],
         "paged": _paged("recruitments", 610, 10, 30, "?recruitment_type=archive", weekly=2)},
        {"key": "press-releases", "title": "Press releases and payroll data (2016 onwards)", "categories": ["press_releases"],
         "seeds": [_es("press-release")], "paged": _paged("PressReleases", 25, 6, 55)},
        {"key": "news-events", "title": "News and events", "categories": [],
         "seeds": [_es("newsevents")], "paged": _paged("NewsEvents", 190, 25, 12, weekly=3)},
        {"key": "publications", "title": "Publications: annual reports, budget, statistics, newsletters", "categories": [],
         "seeds": [_es("publications")], "paged": _paged("publications", 25, 25, 13)},
        {"key": "defaulters", "title": "Lists of defaulting employers", "categories": ["other"],
         "seeds": [_es("defaulters")], "paged": _paged("Defaulters", 6, 6, 10)},
        {"key": "tieup-hospitals", "title": "Tie-up hospitals: empanelment, extension, termination", "categories": ["vendors_debarment"],
         "seeds": [_es("ssts")], "paged": _paged("ssts", 10, 10, 22)},
        {"key": "pensioners", "title": "Pensioners' corner", "categories": ["circulars"],
         "seeds": [_es("pensioners")], "paged": _paged("Pensioners", 12, 12, 14)},
        {"key": "admissions", "title": "Medical college admissions", "categories": ["other"],
         "seeds": [_es("admissions")], "paged": _paged("Admissions", 10, 10, 30)},
        {"key": "public-procurement", "title": "Public procurement (Make in India, projections)", "categories": ["tenders"],
         "seeds": [_es("publicprocurements")], "max_pages": 2, "max_depth": 0, "expected": 3},
        {"key": "acts-rules", "title": "ESI Act, regulations, rules, staff regulations", "categories": ["acts_rules"],
         "seeds": [_es("esi-acts"), _es("esi-staff")], "max_pages": 3, "max_depth": 0, "expected": 10},
        {"key": "rti", "title": "RTI: manual, suo motu disclosures, returns, CPIO list", "categories": ["rti"],
         "seeds": [_es("rti-act")], "max_pages": 2, "max_depth": 0, "expected": 35},
        {"key": "org-directory", "title": "Organisation chart, members, committees, offices and hospitals", "categories": ["directory"],
         "seeds": [_es(p) for p in ("organization-chart", "who_is_who", "directory", "members-esi", "standing-committee-list",
                                    "vigilance", "regional-offices", "esic-hospital", "esis-hospital", "medical-institution",
                                    "dispensaries", "branchs", "dcbos", "tors", "esistatedirectorates", "stateesisocietys")],
         "follow": [_es(p) for p in ("regional-offices/", "esic-hospital/", "esis-hospital/", "medical-institution/",
                                     "dispensaries/index/page:", "branchs/index/page:", "dcbos/index/page:", "tors/index/page:",
                                     "zonal-office", "vigilancedivisions", "regionalsubregionaloffices", "divisional-offices",
                                     "statedirectorates", "esicesismedicals", "benefits-council", "memberregionalboards",
                                     "appellate-authority", "grievance-redressal-officers", "independent-external-monitor")],
         "max_pages": 250, "max_depth": 2, "expected": 250},
        {"key": "info-pages", "title": "Scheme pages: coverage, contribution, benefits, finance", "categories": ["schemes_policies"],
         "seeds": [_es(p) for p in ("", "about-us", "coverage", "contribution", "finance", "information-benefits", "abvky", "ab-pm-jay",
                                    "scale-of-medicals-benefit/", "wages")],
         "chrome": True, "max_pages": 11, "max_depth": 0, "expected": 20},
    ],
}


SOURCES = {
    "epfo": EPFO,
    "esic": ESIC,
    "cmpfo": CMPFO,
}
