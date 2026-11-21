# epfo-pf

This family of the s1d-labs scrape pool collects public records of three Indian social-security organisations:

| Project | Organisation | Site | Sections | Queue items | Access |
|---|---|---|---|---|---|
| `epfo-pf-epfo` | Employees' Provident Fund Organisation (EPFO) | www.epfo.gov.in | 17 | 17 | Indian proxy (`proxy="IN"`) |
| `epfo-pf-esic` | Employees' State Insurance Corporation (ESIC) | esic.gov.in | 18 | 113 | Indian proxy (`proxy="IN"`) |
| `epfo-pf-cmpfo` | Coal Mines Provident Fund Organisation (CMPFO) | cmpfo.gov.in | 12 | 12 | direct |

The scraper does not collect the Pension Fund Regulatory and Development Authority (PFRDA, www.pfrda.org.in). The robots.txt file of
that site disallows all crawlers except Googlebot (checked on 2026-11-15).

## What the scraper collects

The `harvest` task crawls each section of a site from its seed pages. It stores three kinds of records:

- `doc:<id>`: one record for each linked document (PDF, office file, image, archive). The record holds the link text, the
  text of the table row, the column name, the dates in the row, the categories, the size, the checksums and the path in the bucket.
- `page:<id>`: one record for each HTML page. The bucket holds a copy of the page.
- `section:<key>`: one record for each section or page range, with counts of pages, documents and failures.

The `id` is the SHA-1 of the canonical URL. The scraper gives one canonical host to files that several hosts serve.

The family's bucket holds the files, under the project name:

- `docs/<ext>/<id[:2]>/<id>.<ext>`: the documents. The field `ocr` is `pending` for scans and office files, for a later OCR step.
- `pages/<id[:2]>/<id>.html.gz`: the HTML pages.
- `state/<section>.json.gz`: the manifest of stored documents. A new run downloads only documents that are not in the manifest.

## Sections

The site maps are from 2026-11-15. `sources.py` holds all sections with their seed URLs.

- EPFO: circulars (about 1,880, from 2006), tenders and notices, meetings of the Central Board of Trustees (agenda and minutes),
  annual reports (from 1952), annual accounts (from 1982-83), monthly payroll data, press releases, publications, Parliament
  questions, manuals and recruitment rules, acts and schemes, exempted establishments, recruitment, appointments, directory, RTI.
- ESIC: tenders (current list and archive from 2014, about 17,000 rows), circulars (archive from 2015), recruitment, press
  releases, news, publications (annual reports, budget, statistics), defaulting employers, tie-up hospitals, pensioners,
  admissions, public procurement, acts and rules, RTI, directories.
- CMPFO: office orders, tenders, disclosures (acts, Parliament questions, action taken on audit paras), RTI, acts and schemes,
  monthly progress reports and annual report, recruitment, forms and manuals, news, vigilance, directories, official language.

Each category in the request has its source in this table. Some categories have no page on the sites.

| Category | Where the scraper finds it |
|---|---|
| Tenders, corrigenda, results | EPFO and CMPFO tender pages (few rows); the ESIC tender list and archive |
| Budget, accounts | EPFO annual accounts; ESIC publications ("Financial Estimates and Performance Budget") |
| Statistics | EPFO payroll data and exempted establishments; ESIC press releases and publications; CMPFO progress reports |
| Investments | EPFO agenda of Board meetings; circulars of the EPFO investment division |
| Audit | CMPFO action taken report on audit paras. EPFO and ESIC publish no audit pages |
| Parliament | EPFO Parliament questions; CMPFO questions pq1-pq4. ESIC publishes none |
| Vendor debarment | ESIC tie-up hospitals and the drug "not of standard quality" circulars. No site publishes a debarment list |

## Other sources of the same records

The team database `scrape_hub` already holds some records of these organisations. Use them to correlate before you scrape more:

- `eprocure.tender_facts`: CPPP tenders of ESIC (4,406), EPFO (360) and CMPFO (29), with bids and awards.
- `public.records` of project `cag-reports`: about 27,500 CAG audit report files.
- The GeM projects (`gem-*`): GeM bids. EPFO, ESIC and CMPFO now buy much through GeM.

Other public sources: sansad.in (Parliament questions), egazette.gov.in (notifications), pib.gov.in (older press releases).

## Run and check

1. Install the packages:
   `pip install -r requirements.txt pytest "scrape-hub-client @ git+https://github.com/s1d-labs/runner@sdk-stable#subdirectory=sdk"`
2. Run the tests (offline): `python -m pytest tests -q`.
3. Run one section without the hub: `python harvest.py --local cmpfo tenders --max-pages 2 --max-docs 2`.
4. Check a project against the local test hub. Always set the limits:
   `scrape-check --items 2 --project epfo-pf-cmpfo --env HARVEST_MAX_PAGES=2 --env HARVEST_MAX_DOCS=2`.
5. Run the **setup** workflow (Actions, then setup). It registers the projects and fills the queues.

To crawl all sections again, change `ROUND` in `family.py` and run the **setup** workflow again.

## Rules that the scraper obeys

- It reads the robots.txt file of each host and obeys it.
- It uses the speed from the hub (`threads`, `delay_ms`). It waits at least 0.5 s between two requests of one thread.
- It does not use logins, member or employer portals, search forms or POST requests.
- It does not use the WordPress REST API of EPFO. That API requires a login.
- Directory pages contain names and telephone numbers of officials. The scraper stores these pages but does not parse them.
  Do not publish personal data from them.
