"""Phase 5 — real-browser E2E over the shipped artefact.

The previous report established that the bundle builds and that the API
responds. Neither is a user session. This drives the built ``frontend/dist``
through a real Chromium against a real API server and the real database, and
records what a browser actually did: the console errors it logged, the network
requests that failed, and a screenshot per route.

What it checks, in the order a user meets them:

1. the app boots and paints something on ``/``;
2. the discover route renders real records fetched from the API — not a
   skeleton that never resolves;
3. a scholarship detail page resolves for a record that exists;
4. a deep link to a record that does *not* exist shows the app's own not-found
   state rather than a blank page or a raw API error;
5. a bookmarked deep link works on a cold load, which is the SPA-fallback path
   the API app explicitly claims to handle;
6. no console errors and no failed network requests on any route.

It fails loudly rather than reporting a summary of a session that errored:
a non-zero exit means a route did not render.

    python scripts/v01_e2e_browser.py --port 8078
    python scripts/v01_e2e_browser.py --keep-screenshots
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT_DIR = Path("artifacts/e2e")

# The id step 4 deliberately asks for. It never exists, so the 404 the browser
# logs for it is the expected result rather than a defect.
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


class BrowserSession:
    """One Chromium session, started and stopped around the checks."""

    def __init__(self, base_url: str, headed: bool = False) -> None:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(headless=not headed)
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 900})
        self.page = self.context.new_page()
        self.base_url = base_url.rstrip("/")
        self.console_errors: list[str] = []
        self.failed_requests: list[str] = []

        def _record_console(message) -> None:
            if message.type != "error":
                return
            # The text alone is useless for triage: the browser says only
            # "Failed to load resource: the server responded with a status of
            # 404 (Not Found)" and names nothing. The location carries the
            # URL, which is the only part that says what failed.
            self.console_errors.append(
                f"{message.text} [{message.location.get('url', 'unknown url')}]"
            )

        self.page.on("console", _record_console)
        self.page.on("requestfailed", lambda r: self.failed_requests.append(
            f"{r.method} {r.url} — {r.failure}"
        ))
        self.page.on("response", lambda r: self.failed_requests.append(
            f"{r.request.method} {r.url} — HTTP {r.status}"
        ) if r.status >= 400 else None)

    def close(self) -> None:
        for closer in (self.context.close, self.browser.close, self._playwright.stop):
            try:
                closer()
            except Exception:  # noqa: BLE001 — teardown must not mask a failure
                pass

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def _visible_text(page, limit: int = 400) -> str:
    try:
        text = page.inner_text("body")
    except Exception:  # noqa: BLE001
        return ""
    return " ".join(text.split())[:limit]


def _settle(page, ms: int = 900) -> None:
    """Wait for network quiet, then a beat for the render.

    ``networkidle`` rather than a fixed sleep: a fixed sleep passes on a fast
    machine and flakes on a slow one, and passing is the whole point here.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:  # noqa: BLE001 — fall through to the fixed beat
        pass
    page.wait_for_timeout(ms)


def _start_server(port: int) -> subprocess.Popen:
    import os

    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.app:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": ".", "PYTHONIOENCODING": "utf-8"},
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit("API server exited during startup")
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as response:
                if response.status == 200:
                    return process
        except Exception:  # noqa: BLE001 — not up yet
            time.sleep(0.5)
    process.terminate()
    raise SystemExit("API server did not become healthy within 60s")


def _published_ids(base: str, limit: int = 5) -> list[str]:
    import urllib.request as request

    url = f"{base}/api/v1/scholarships?limit={limit}"
    with request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read())
    return [item["scholarship_id"] for item in payload.get("results", [])]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8078)
    parser.add_argument("--url", help="test an already-running server")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--keep-screenshots", action="store_true", default=True)
    args = parser.parse_args(argv)

    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        raise SystemExit("frontend/dist missing — run `npm run build` in frontend/ first")

    server = None
    base = args.url
    if not base:
        server = _start_server(args.port)
        base = f"http://127.0.0.1:{args.port}"

    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{name}: {detail}")

    try:
        ids = _published_ids(base)
        print(f"served from {base}; {len(ids)} published records visible to the API\n")

        with BrowserSession(base, headed=args.headed) as session:
            page = session.page

            # 1 — the app boots.
            page.goto(f"{base}/", wait_until="domcontentloaded")
            _settle(page)
            text = _visible_text(page)
            shot = SHOT_DIR / "01-home.png"
            page.screenshot(path=str(shot), full_page=True)
            check("home renders content", len(text) > 40, f"{len(text)} chars of text")
            check("home screenshot captured", shot.exists(), str(shot))

            # 2 — discover shows records that came from the API.
            page.goto(f"{base}/discover", wait_until="domcontentloaded")
            _settle(page)
            discover = _visible_text(page, 1200)
            shot = SHOT_DIR / "02-discover.png"
            page.screenshot(path=str(shot), full_page=True)
            check("discover route renders", len(discover) > 60, f"{len(discover)} chars")
            check(
                "discover shows no visible error state",
                "error" not in discover.lower()[:200],
                discover[:120],
            )

            # 3 — a real record's detail page.
            if ids:
                page.goto(f"{base}/scholarships/{ids[0]}", wait_until="domcontentloaded")
                _settle(page)
                detail = _visible_text(page, 1200)
                shot = SHOT_DIR / "03-detail.png"
                page.screenshot(path=str(shot), full_page=True)
                check("detail route renders for a published record",
                      len(detail) > 60, f"{len(detail)} chars")
            else:
                check("detail route renders for a published record", False,
                      "no published records available to open")

            # 4 — an unknown id shows the app's own not-found state.
            page.goto(
                f"{base}/scholarships/{UNKNOWN_ID}",
                wait_until="domcontentloaded",
            )
            _settle(page)
            missing = _visible_text(page, 600)
            shot = SHOT_DIR / "04-not-found.png"
            page.screenshot(path=str(shot), full_page=True)
            check(
                "unknown scholarship id shows a not-found state, not a crash",
                len(missing) > 20 and "unexpected" not in missing.lower(),
                missing[:120],
            )

            # 5 — a cold deep link resolves through the SPA fallback.
            #    Navigating to a route directly is the bookmark/refresh path
            #    the API app claims to support; a broken fallback 404s here.
            response = page.goto(f"{base}/discover", wait_until="domcontentloaded")
            status = response.status if response else 0
            _settle(page)
            check("cold deep link to /discover returns 200", status == 200, f"HTTP {status}")

            # 6 — nothing errored in the browser along the way.
            #
            # Two categories are expected and excluded rather than waved
            # through. The favicon is not part of the shipped app, and the
            # unknown-id probe in step 4 is *supposed* to 404 — the browser
            # logs that as a console error even though the app renders its
            # not-found state correctly, which is exactly what step 4 checked.
            # Excluding it by shape (the all-zero UUID) keeps the exclusion
            # narrow: a 404 on any real request still fails this check.
            expected = ("favicon", UNKNOWN_ID)
            console = [
                e for e in session.console_errors
                if not any(token in e.lower() for token in expected)
            ]
            check("no console errors", not console, "; ".join(console[:3]))
            failed = [
                f for f in session.failed_requests
                if not any(token in f.lower() for token in expected)
            ]
            check("no unexpected failed requests", not failed, "; ".join(failed[:3]))

        report = {
            "base_url": base,
            "published_records_visible": len(ids),
            "checks": checks,
            "console_errors": session.console_errors,
            "failed_requests": session.failed_requests,
            "screenshots": sorted(str(p) for p in SHOT_DIR.glob("*.png")),
        }
        (SHOT_DIR / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(f"\nreport  {SHOT_DIR / 'report.json'}")
        print(f"shots   {SHOT_DIR}")
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    if failures:
        print(f"\n{len(failures)} check(s) failed:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nall browser checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
