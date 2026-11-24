"""Offline tests of the recover task's data file and helpers."""
import recover as R


def test_data_file_is_complete_and_unique():
    rows = R.load_rows()
    assert len(rows) >= 22_000
    assert len({r["original_url"] for r in rows}) == len(rows)
    assert all(r["wayback_url"].startswith("https://web.archive.org/web/") and "id_/" in r["wayback_url"] for r in rows)
    assert rows[0]["org"] == "epfo" and rows[0]["category"] == "cbt_meetings"      # most valuable first


def test_chunks_cover_every_row_once():
    rows = R.load_rows()
    ch = R.chunks(rows)
    covered = [i for a, b, _, _ in ch for i in range(a, b + 1)]
    assert covered == list(range(len(rows)))
    for a, b, org, cat in ch:
        assert b - a + 1 <= 100
        assert {(r["org"], r["category"]) for r in rows[a:b + 1]} == {(org, cat)}


def test_truncation_detection():
    assert R.truncated({}, R.CC_CAP)
    assert R.truncated({"x-archive-orig-x-crawler-content-length": "18030582"}, 5_000_000)
    assert not R.truncated({"x-archive-orig-content-length": "662493"}, 662_493)
    assert not R.truncated({}, 36_130)


def test_capture_timestamp():
    assert R.capture_ts("https://web.archive.org/web/20240503035008id_/https://x.gov.in/a.pdf") == "20240503035008"


def test_archive_project_items():
    import family
    p = next(x for x in family.PROJECTS if x["name"].endswith("-archive"))
    assert p["target"] == "web.archive.org" and p["task"] == "recover" and p["max_workers"] <= 2
    keys = [i["key"] for i in p["items"]]
    assert len(keys) == len(set(keys)) and all(len(k) <= 200 for k in keys)
    assert any(pr["name"] == p["probe"] for pr in family.PROBES)
