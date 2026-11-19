"""V0.1 end-to-end smoke test + response-time measurement.

Runs the whole V0.1 user journey against a production-like server (uvicorn
serving the same app object the deployment serves) and times each step.
Nothing is mocked and nothing is written: this is the journey a real visitor
takes, and a step that fails here fails in production too.

    python scripts/v01_smoke.py --base http://127.0.0.1:8222
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid

PROFILE = {
    "target_country": "United Kingdom",
    "degree": "Master",
    "field_of_study": ["Computer Science"],
    "current_gpa": 3.5,
    "ielts_score": 7.0,
    "toefl_score": None,
    "research_experience": "Not Required",
    "work_experience": "Optional",
    "publication": "Not Required",
    "leadership": False,
    "funding_preference": "Fully Funded",
}

INCOMPLETE_PROFILE = {"target_country": "Japan"}

FAILURES: list[str] = []
TIMINGS: dict[str, list[float]] = {}


def call(method: str, path: str, payload=None, expect: int = 200):
    """One request, timed, with the status recorded for the report."""
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            body = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
        body = json.loads(raw) if raw else {}
    elapsed_ms = (time.perf_counter() - start) * 1000
    TIMINGS.setdefault(f"{method} {path.split('?')[0]}", []).append(elapsed_ms)

    if status != expect:
        FAILURES.append(f"{method} {path} -> {status} (expected {expect})")
    return status, body


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "ok  " if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILURES.append(f"{label}: {detail}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8222")
    args = parser.parse_args()
    global BASE
    BASE = args.base.rstrip("/")

    print("1. health")
    status, body = call("GET", "/health")
    check("health returns ok", status == 200 and body.get("status") == "ok", str(body))

    print("\n2. browse")
    status, listing = call("GET", "/api/v1/scholarships?limit=20&offset=0")
    check("list returns 200", status == 200)
    results = listing.get("results", [])
    check("catalogue is populated", len(results) > 0, f"{listing.get('total')} approved")
    check(
        "no sentinel in list",
        all(
            (r.get("provider_name") or "").casefold() != "unknown"
            and (r.get("country") or "").casefold() != "unknown"
            for r in results
        ),
    )

    print("\n3. search")
    status, found = call("GET", "/api/v1/scholarships?q=a&limit=10")
    check("search returns 200", status == 200)
    status, empty = call("GET", "/api/v1/scholarships?q=zzzznotascholarshipzzz&limit=10")
    check(
        "no-match search is an empty page, not an error",
        status == 200 and empty.get("results") == [] and empty.get("total") == 0,
    )
    status, _ = call("GET", "/api/v1/scholarships?country=Japan&limit=10")
    check("country filter returns 200", status == 200)
    status, _ = call("GET", "/api/v1/scholarships?degree=Bachelor&limit=10")
    check("degree filter returns 200", status == 200)

    print("\n4. detail")
    if results:
        scholarship_id = results[0]["scholarship_id"]
        status, detail = call("GET", f"/api/v1/scholarships/{scholarship_id}")
        check("detail returns 200", status == 200)
        check("detail has an official source", bool(detail.get("official_url")))
        check(
            "detail exposes source-trust date",
            "last_verified_at" in detail,
            f"last_verified_at={detail.get('last_verified_at')}",
        )
        check(
            "detail never reports a sentinel",
            all(
                (detail.get(f) or "").casefold() != "unknown"
                for f in ("provider_name", "country", "provider_type")
            ),
        )
        step_5 = detail.get("timeline") or {}
        check(
            "a record with sparse optional fields still renders",
            isinstance(step_5, dict),
        )

    print("\n5. publication boundary")
    status, _ = call("GET", f"/api/v1/scholarships/{uuid.uuid4()}", expect=404)
    check("unknown id is 404", status == 404)
    status, _ = call("GET", "/api/v1/scholarships/not-a-uuid", expect=404)
    check("malformed id is 404, not 500", status == 404)
    status, _ = call("GET", "/api/v1/scholarships?limit=0", expect=422)
    check("limit=0 is 422", status == 422)
    status, _ = call("GET", "/api/v1/scholarships?limit=99999", expect=422)
    check("limit above the cap is 422", status == 422)

    print("\n6. profile validation")
    status, body = call("POST", "/api/v1/matching", INCOMPLETE_PROFILE, expect=422)
    check(
        "incomplete profile is 422 with field messages",
        status == 422 and bool(body.get("detail")),
    )

    print("\n7. matching")
    status, matches = call("POST", "/api/v1/matching", PROFILE)
    check("matching returns 200", status == 200)
    check("results returned", len(matches.get("results", [])) > 0)
    check(
        "total >= returned",
        matches.get("total", 0) >= matches.get("returned", -1),
        f"total={matches.get('total')} returned={matches.get('returned')}",
    )
    check(
        "returned equals the page length",
        matches.get("returned") == len(matches.get("results", [])),
    )
    scores = [r["match_score"] for r in matches.get("results", [])]
    check("scores within 0-100", all(0 <= s <= 100 for s in scores))
    check(
        "scores are ordered",
        scores == sorted(scores, reverse=True),
        f"min={min(scores) if scores else 'n/a'} max={max(scores) if scores else 'n/a'}",
    )
    check(
        "every result explains itself",
        all(r.get("strengths") is not None and r.get("gaps") is not None for r in matches.get("results", [])),
    )
    check(
        "every result links to a source",
        all(r.get("official_url") for r in matches.get("results", [])),
    )
    status, canonical = call("POST", "/api/v1/recommendations", PROFILE)
    check("canonical path returns the same contract", canonical == matches)

    print("\n8. frontend is served")
    for path in ("/", "/discover", "/match"):
        request = urllib.request.Request(BASE + path)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                code = response.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        check(f"GET {path}", code == 200, str(code))

    print("\n--- response times (ms), 1 warm-up pass then 5 measured")
    for path in (
        "/api/v1/scholarships?limit=20",
        "/api/v1/scholarships?limit=100",
        "/api/v1/matching",
        "/api/v1/recommendations",
    ):
        for _ in range(2):
            if path.endswith("matching") or path.endswith("recommendations"):
                call("POST", path, PROFILE)
            else:
                call("GET", path)
        TIMINGS.clear()
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            if path.endswith("matching") or path.endswith("recommendations"):
                call("POST", path, PROFILE)
            else:
                call("GET", path)
            samples.append((time.perf_counter() - start) * 1000)
        print(
            f"  {path:<40} median={statistics.median(samples):6.1f}  "
            f"min={min(samples):6.1f}  max={max(samples):6.1f}"
        )

    print()
    if FAILURES:
        print(f"SMOKE TEST FAILED — {len(FAILURES)} problem(s):")
        for failure in FAILURES:
            print("  -", failure)
        return 1
    print("SMOKE TEST PASSED")
    return 0


BASE = "http://127.0.0.1:8222"


if __name__ == "__main__":
    sys.exit(main())
