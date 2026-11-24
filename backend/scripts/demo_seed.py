"""Reset the demo organization and seed it from sample-data/shipment-case through the public
API only (observability-testing 5.1). Run by scripts/demo-reset.ps1 and .sh.

    uv run python scripts/demo_seed.py [--base-url http://localhost:8080]

Credentials come from VERITAS_DEMO_EMAIL and VERITAS_DEMO_PASSWORD (environment or the
repository's .env). The demo user is registered on first use. Every existing case of the demo
organization is soft-deleted (hidden everywhere; the retention purge removes it later), then
one case is created, the 7 SYNTHETIC DEMONSTRATION DATA files are uploaded, processing is
awaited, and the result is checked: exactly one USD 20,000.00 discrepancy.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "sample-data" / "shipment-case"
ORG_NAME = "VERITAS Demo (SYNTHETIC DEMONSTRATION DATA)"
CASE_TITLE = "International Shipment SHIP-2049 (SYNTHETIC DEMONSTRATION DATA)"
EXPECTED_DIFFERENCE = Decimal("20000.00")


class DemoError(RuntimeError):
    pass


def _env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                value = line.split("=", 1)[1].strip()
    return value


def _ok(resp: httpx.Response, what: str) -> Any:
    if resp.status_code >= 400:
        detail = resp.json().get("detail") if "json" in resp.headers.get("content-type", "") else ""
        raise DemoError(f"{what} failed: HTTP {resp.status_code} {detail}")
    return resp.json() if resp.content else None


def _session(c: httpx.Client, email: str, password: str) -> dict[str, str]:
    resp = c.post("/auth/login", json={"email": email, "password": password})
    if resp.status_code == 401:
        print(f"registering the demo user {email}")
        body = {
            "email": email,
            "password": password,
            "full_name": "Demo Investigator",
            "organization_name": ORG_NAME,
        }
        tokens = _ok(c.post("/auth/register", json=body), "registration")
    else:
        tokens = _ok(resp, "login")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _existing_cases(c: httpx.Client, h: dict[str, str]) -> list[dict[str, Any]]:
    cases, cursor = [], None
    while True:
        params = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        page = _ok(c.get("/cases", headers=h, params=params), "listing cases")
        cases += page["items"]
        cursor = page.get("next_cursor")
        if not cursor:
            return cases


def _wait_for_job(c: httpx.Client, h: dict[str, str], job_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = _ok(c.get(f"/jobs/{job_id}", headers=h), "reading the processing job")
        if job["status"] in ("succeeded", "failed"):
            if job["status"] == "failed":
                raise DemoError(f"processing failed: {job.get('error')}")
            return
        print(f"  processing: {job['progress']}%", flush=True)
        time.sleep(5)
    raise DemoError(f"processing did not finish within {timeout:.0f} s")


def seed(base_url: str, timeout: float) -> dict[str, Any]:
    email, password = _env("VERITAS_DEMO_EMAIL"), _env("VERITAS_DEMO_PASSWORD")
    if not email or not password or password.startswith("CHANGE_ME"):
        raise DemoError("set VERITAS_DEMO_EMAIL and VERITAS_DEMO_PASSWORD (12+ characters) in .env")
    files = sorted(SAMPLES.glob("*.pdf"))
    if len(files) != 7:
        raise DemoError(f"expected 7 sample PDFs in {SAMPLES}, found {len(files)}")
    with httpx.Client(base_url=base_url.rstrip("/") + "/api/v1", timeout=120) as c:
        h = _session(c, email, password)
        removed = 0
        for case in _existing_cases(c, h):
            _ok(c.delete(f"/cases/{case['id']}", headers=h), f"deleting case {case['id']}")
            removed += 1
        print(f"soft-deleted {removed} existing case(s)")
        case = _ok(
            c.post(
                "/cases",
                headers=h,
                json={
                    "title": CASE_TITLE,
                    "objective": "Reconcile the declared values of shipment SHIP-2049.",
                    "investigation_type": "international_shipment",
                    "priority": "high",
                },
            ),
            "creating the case",
        )
        upload = _ok(
            c.post(
                f"/cases/{case['id']}/documents",
                headers=h,
                files=[("files", (p.name, p.read_bytes(), "application/pdf")) for p in files],
            ),
            "uploading the documents",
        )
        accepted = [r for r in upload["results"] if r["status"] == "accepted"]
        if len(accepted) != 7 or not upload.get("job_id"):
            raise DemoError(f"expected 7 accepted files, got {upload['results']}")
        _wait_for_job(c, h, upload["job_id"], timeout)
        findings = _ok(c.get(f"/cases/{case['id']}/findings", headers=h), "reading findings")
        money = [f for f in findings if f.get("type") == "financial_discrepancy"]
        if len(money) != 1 or Decimal(str(money[0].get("difference"))) != EXPECTED_DIFFERENCE:
            raise DemoError(f"expected one USD 20,000.00 discrepancy, found {findings}")
        return {"case_id": case["id"], "removed": removed, "findings": len(findings)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--base-url", default=os.environ.get("VERITAS_DEMO_BASE_URL", "http://localhost:8080")
    )
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    try:
        result = seed(args.base_url, args.timeout)
    except (DemoError, httpx.HTTPError) as exc:
        print(f"demo reset FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        f"demo ready: case {result['case_id']}, {result['findings']} finding(s) "
        f"(USD 20,000.00 discrepancy), {result['removed']} old case(s) removed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
