"""Phase 6 — performance baseline for the public API.

The V0.1 report measured the frontend bundle but not the API's response time,
which is the number a user actually feels on a cold load. This measures it.

Runs against a *live* server over real HTTP rather than the in-process test
client: the in-process client shares the event loop and connection pool, so it
reports a number no user will ever see.

Every sample is reported, not just an average, because a p95 that is one query
away from a timeout is the number that matters. The run prints median, p95 and
max per endpoint so a regression shows up as a shape change rather than as a
number that moved slightly.

    python scripts/v01_perf_baseline.py                 # starts its own server
    python scripts/v01_perf_baseline.py --url http://127.0.0.1:8000
    python scripts/v01_perf_baseline.py --samples 40
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_SAMPLES = 25


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile over a sorted copy.

    Nearest-rank rather than interpolated: with 25 samples an interpolated p95
    invents a value no request produced.
    """
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered)) - 1))
    return ordered[index]


def _time_get(url: str, timeout: float = 30.0) -> tuple[float, int, int]:
    """One timed GET. Returns (milliseconds, status, bytes)."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, response.status, len(body)


def _detail_id(base: str, timeout: float = 30.0) -> str | None:
    """A real published record to point the detail endpoint at."""
    url = f"{base}/api/v1/scholarships?limit=1"
    try:
        import json

        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read())
        results = payload.get("results") or []
        return results[0]["scholarship_id"] if results else None
    except Exception:  # noqa: BLE001 — the probe failing just skips that route
        return None


def _measure(base: str, routes: list[tuple[str, str]], samples: int) -> dict:
    results: dict[str, dict] = {}
    for label, path in routes:
        url = f"{base}{path}"
        timings: list[float] = []
        statuses: set[int] = set()
        sizes: list[int] = []
        try:
            for _ in range(samples):
                elapsed, status, size = _time_get(url)
                timings.append(elapsed)
                statuses.add(status)
                sizes.append(size)
        except (urllib.error.URLError, OSError) as exc:
            results[label] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        results[label] = {
            "samples": len(timings),
            "median_ms": round(statistics.median(timings), 1),
            "p95_ms": round(_percentile(timings, 0.95), 1),
            "max_ms": round(max(timings), 1),
            "min_ms": round(min(timings), 1),
            "statuses": sorted(statuses),
            "bytes": sizes[-1] if sizes else 0,
        }
    return results


def _report(results: dict) -> None:
    print(f"{'route':<34}{'n':>4}{'median':>9}{'p95':>9}{'max':>9}  status")
    print("-" * 84)
    for label, stats in results.items():
        if "error" in stats:
            print(f"{label:<34}{'—':>4}{'—':>9}{'—':>9}{'—':>9}  {stats['error'][:40]}")
            continue
        print(
            f"{label:<34}{stats['samples']:>4}{stats['median_ms']:>9}"
            f"{stats['p95_ms']:>9}{stats['max_ms']:>9}  {stats['statuses']}"
        )


def _start_server(port: int) -> subprocess.Popen:
    env = {"PYTHONPATH": ".", "PYTHONIOENCODING": "utf-8"}
    process = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "api.app:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**dict(__import__("os").environ), **env},
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        if process.poll() is not None:
            raise SystemExit("server exited during startup")
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2) as response:
                if response.status == 200:
                    return process
        except Exception:  # noqa: BLE001 — not up yet
            time.sleep(0.5)
    process.terminate()
    raise SystemExit("server did not become healthy within 60s")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="measure an already-running server")
    parser.add_argument("--port", type=int, default=8077)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--json", action="store_true", help="emit raw numbers")
    args = parser.parse_args(argv)

    process = None
    base = args.url
    if not base:
        process = _start_server(args.port)
        base = f"http://127.0.0.1:{args.port}"

    try:
        routes: list[tuple[str, str]] = [
            ("GET /health", "/health"),
            ("GET /api/v1/scholarships", "/api/v1/scholarships"),
            ("GET /api/v1/scholarships?limit=100", "/api/v1/scholarships?limit=100"),
            ("GET /api/v1/scholarships?q=scholarship",
             "/api/v1/scholarships?q=scholarship"),
            ("GET /api/v1/scholarships?country=Japan",
             "/api/v1/scholarships?country=Japan"),
        ]
        detail = _detail_id(base)
        if detail:
            routes.append((f"GET /api/v1/scholarships/{detail[:8]}…",
                           f"/api/v1/scholarships/{detail}"))
        else:
            print("note: no published record available, skipping the detail route\n")

        # Warm-up is excluded from the samples: the first request after boot
        # pays for connection setup and cold plan caches, and reporting it as
        # the baseline would flatter a later regression or blame a cold start.
        for _, path in routes:
            try:
                _time_get(f"{base}{path}")
            except Exception:  # noqa: BLE001
                pass

        print(f"baseline against {base}, {args.samples} samples per route\n")
        results = _measure(base, routes, args.samples)
        _report(results)

        if args.json:
            import json

            print()
            print(json.dumps(results, indent=2))
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
