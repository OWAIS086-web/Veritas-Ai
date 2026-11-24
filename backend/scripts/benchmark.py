"""Benchmark the document pipeline on the synthetic dataset (observability-testing 3.1, 3.2).

    uv run python scripts/benchmark.py --runs 3 --write-docs
        [--llm-base-url http://127.0.0.1:11434/v1 --llm-model qwen2.5:7b-instruct]
        [--vlm-model qwen2.5vl:7b]
        [--api-url http://localhost:8080]

What is measured, and how:
- In this process, per document and run (the code the worker runs): parse (text layer, or
  OpenCV + PaddleOCR for scans and images), classification and rules extraction, timed with
  time.perf_counter. OCR time is the parse time of documents that needed OCR. Time per page is
  parse + classify + extract divided by the page count. A warm-up pass loads the OCR models
  first and is reported apart, not mixed into the runs.
- Peak RSS of this process (psutil, sampled every 0.1 s).
- With --llm-base-url: model inference time of provider extraction for each text document.
- With --vlm-model: vision-model time of one original-versus-test comparison.
- With --api-url: one investigation on the running stack through the public API (time from
  start to the human-review pause), and the worker container's peak memory (docker stats).
Failures are recorded as data points, never as a crash. Results go to docs/benchmarks.md with
the machine and date; no other performance claim is made anywhere.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import secrets
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a file from backend/

from app.services.classification.rules import classify
from app.services.extraction import rules
from app.services.ingestion.detect import detect
from app.services.parsing.dispatch import parse_document

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "sample-data"
DOCS = ROOT / "docs" / "benchmarks.md"
DATASET = sorted((SAMPLES / "shipment-case").glob("*.pdf")) + sorted(
    p for p in (SAMPLES / "format-variants").iterdir() if p.is_file()
)


@dataclass
class Series:
    unit: str
    values: list[float] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        if not self.values:
            return {"n": 0, "mean": None, "p95": None, "unit": self.unit}
        ordered = sorted(self.values)
        p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]  # nearest rank
        return {
            "n": len(ordered),
            "mean": round(statistics.fmean(ordered), 3),
            "p95": round(p95, 3),
            "unit": self.unit,
        }


@dataclass
class Results:
    series: dict[str, Series] = field(default_factory=dict)
    outcomes: dict[str, list[bool]] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, value: float, unit: str) -> None:
        self.series.setdefault(name, Series(unit)).values.append(value)

    def outcome(self, name: str, ok: bool, detail: str = "") -> None:
        self.outcomes.setdefault(name, []).append(ok)
        if not ok:
            self.failures.append(f"{name}: {detail}"[:300])


class PeakRss:
    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._proc = psutil.Process()

    def __enter__(self) -> PeakRss:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self._proc.memory_info().rss)
            time.sleep(0.1)

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()


def _process(data: bytes, mime: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    parsed = parse_document(data, mime)
    t1 = time.perf_counter()
    pages = parsed.pages
    kind = classify(
        [ln.text for ln in pages[0].lines] if pages else [], "\n".join(p.text for p in pages)
    )
    t2 = time.perf_counter()
    values = rules.extract(kind.doc_type, pages, parsed.ocr_version)
    t3 = time.perf_counter()
    return {
        "parse": t1 - t0,
        "classify": t2 - t1,
        "extract": t3 - t2,
        "pages": max(1, len(pages)),
        "ocr": parsed.ocr_version is not None,
        "doc_type": kind.doc_type,
        "fields": sum(1 for v in values if v.status == "extracted"),
        "pages_list": pages,
    }


def run_pipeline(res: Results, runs: int) -> None:
    files = [(p, p.read_bytes()) for p in DATASET]
    scans = [(p, d) for p, d in files if (detect(d).mime or "").startswith("image/")]
    if scans:
        started = time.perf_counter()
        try:
            _process(scans[0][1], detect(scans[0][1]).mime or "")
        except Exception as exc:  # recorded, the runs continue
            res.notes.append(f"warm-up failed: {type(exc).__name__}")
        res.extra["warmup_seconds"] = round(time.perf_counter() - started, 2)
    for run in range(runs):
        for path, data in files:
            mime = detect(data).mime
            name = f"{path.parent.name}/{path.name}"
            if mime is None:
                res.outcome("document", False, f"{name}: undetected type")
                continue
            try:
                r = _process(data, mime)
            except Exception as exc:
                res.outcome("document", False, f"{name}: {type(exc).__name__}: {exc}")
                continue
            res.outcome("document", r["doc_type"] != "unknown", f"{name}: classified unknown")
            if r["ocr"]:
                res.add("OCR time per document", r["parse"], "s")
            else:
                res.add("Parse time per document (no OCR)", r["parse"], "s")
            res.add("Extraction time per document (rules)", r["extract"], "s")
            res.add("Classification time per document", r["classify"], "s")
            res.add(
                "Pipeline time per page",
                (r["parse"] + r["classify"] + r["extract"]) / r["pages"],
                "s",
            )
        print(f"run {run + 1}/{runs} done", flush=True)


async def run_llm(res: Results, base: str, model: str, runs: int) -> None:
    from app.integrations.llm.openai_compat import OpenAICompatProvider
    from app.services.extraction import llm

    provider = OpenAICompatProvider(base, os.environ.get("VERITAS_LLM_API_KEY", ""), [model], 240)
    texts = [p for p in DATASET if p.suffix == ".pdf" and p.parent.name == "shipment-case"]
    for _ in range(runs):
        for path in texts:
            data = path.read_bytes()
            parsed = parse_document(data, "application/pdf")
            kind = classify(
                [ln.text for ln in parsed.pages[0].lines], "\n".join(p.text for p in parsed.pages)
            )
            started = time.perf_counter()
            try:
                values, _ = await llm.extract(provider, kind.doc_type, parsed.pages)
            except Exception as exc:
                res.outcome("model extraction", False, f"{path.name}: {type(exc).__name__}")
                continue
            res.add(f"Model inference per document ({model})", time.perf_counter() - started, "s")
            res.outcome(
                "model extraction",
                any(v.status == "extracted" for v in values),
                f"{path.name}: no verified value",
            )


async def run_vlm(res: Results, base: str, model: str) -> None:
    from app.integrations.llm.openai_compat import OpenAICompatProvider
    from app.services.doccompare.engine import DocInput, EngineSettings, run
    from app.services.doccompare.vision import Vision, VisionStats

    def doc(name: str) -> DocInput:
        data = (SAMPLES / "comparison" / name).read_bytes()
        parsed = parse_document(data, "application/pdf")
        pages = [
            {
                "page_number": p.page_number,
                "method": p.method,
                "lines": [ln.to_json() for ln in p.lines],
            }
            for p in parsed.pages
        ]
        return DocInput(
            name, name, data, "application/pdf", hashlib.sha256(data).hexdigest(), pages, []
        )

    async def progress(stage: str, pct: int) -> None:
        return None

    provider = OpenAICompatProvider(base, os.environ.get("VERITAS_LLM_API_KEY", ""), [model], 240)
    vision = Vision(provider, model, VisionStats(model=model))
    started = time.perf_counter()
    try:
        result = await run(
            doc("original_invoice.pdf"),
            doc("test_altered.pdf"),
            EngineSettings(144, 20, 1000, 0.6, 8, 1),
            vision,
            progress,
        )
    except Exception as exc:
        res.outcome("vision comparison", False, f"{type(exc).__name__}: {exc}")
        return
    stats = result.vlm or {}
    res.add("Comparison lab, whole comparison (2 pages)", time.perf_counter() - started, "s")
    res.add(f"Vision-model time per comparison ({model})", float(stats.get("seconds") or 0), "s")
    res.outcome("vision comparison", stats.get("status") == "used", str(stats.get("errors")))
    res.extra["vision_calls"] = stats.get("calls")


def _docker_worker_mem() -> float | None:
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if "celery-worker" in line:
            used = line.split()[1]
            units = {"KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0}
            for unit, factor in units.items():
                if used.endswith(unit):
                    return float(used[: -len(unit)]) * factor
    return None


def run_investigation(res: Results, api: str) -> None:
    tag = secrets.token_hex(4)
    peak = [0.0]
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            mem = _docker_worker_mem()
            if mem:
                peak[0] = max(peak[0], mem)
            time.sleep(2)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        with httpx.Client(base_url=api.rstrip("/") + "/api/v1", timeout=120) as c:
            reg = c.post(
                "/auth/register",
                json={
                    "email": f"bench-{tag}@example.com",
                    "password": f"bench-password-{tag}",
                    "full_name": "Benchmark",
                    "organization_name": f"Benchmark {tag} (SYNTHETIC DEMONSTRATION DATA)",
                },
            )
            reg.raise_for_status()
            h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
            case = c.post(
                "/cases", headers=h, json={"title": "Benchmark pair", "objective": "Benchmark"}
            ).json()
            files = [
                ("files", (n, (SAMPLES / "shipment-case" / n).read_bytes(), "application/pdf"))
                for n in ("02_commercial_invoice.pdf", "03_customs_declaration.pdf")
            ]
            up = c.post(f"/cases/{case['id']}/documents", headers=h, files=files).json()
            while c.get(f"/jobs/{up['job_id']}", headers=h).json()["status"] not in (
                "succeeded",
                "failed",
            ):
                time.sleep(3)
            time.sleep(5)  # the comparison runs at the end of processing
            started = time.perf_counter()
            inv = c.post(
                f"/cases/{case['id']}/investigate",
                headers=h,
                json={"objective": "Explain the totals"},
            ).json()
            while True:
                d = c.get(f"/investigations/{inv['id']}", headers=h).json()
                if d["status"] not in ("queued", "running"):
                    break
                if time.perf_counter() - started > 1200:
                    d = {"status": "timeout"}
                    break
                time.sleep(3)
            elapsed = time.perf_counter() - started
            ok = d["status"] == "awaiting_review"
            res.outcome("investigation", ok, f"status {d['status']}: {d.get('error')}")
            if ok:
                res.add("Investigation time to review (stack, live model)", elapsed, "s")
                res.extra["investigation_usage"] = d.get("usage")
    except httpx.HTTPError as exc:
        res.outcome("investigation", False, f"{type(exc).__name__}: {exc}")
    finally:
        stop.set()
        sampler.join(timeout=30)
    if peak[0]:
        res.add("Peak worker container memory (docker stats)", peak[0], "MiB")


def machine() -> str:
    mem = psutil.virtual_memory().total / 1024**3
    return (
        f"{platform.system()} {platform.release()}, {platform.processor() or platform.machine()}, "
        f"{psutil.cpu_count(logical=False)} cores / {psutil.cpu_count()} threads, "
        f"{mem:.1f} GB RAM, "
        f"Python {platform.python_version()}, CPU only"
    )


def markdown(res: Results, args: argparse.Namespace) -> str:
    lines = [
        "# Benchmarks",
        "",
        "Generated by `backend/scripts/benchmark.py`. These are the only performance numbers the",
        "project states. SYNTHETIC DEMONSTRATION DATA only.",
        "",
        f"- **Date:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- **Machine:** {machine()}",
        f"- **Command:** `uv run python scripts/benchmark.py {' '.join(sys.argv[1:])}`",
        f"- **Dataset:** {len(DATASET)} files "
        f"({', '.join(sorted({p.parent.name for p in DATASET}))}), "
        f"{args.runs} runs",
        f"- **OCR warm-up (model load, not in the runs):** {res.extra.get('warmup_seconds')} s",
        "",
        "| Metric | n | Mean | p95 | Unit |",
        "|---|---|---|---|---|",
    ]
    for name, s in res.series.items():
        x = s.summary()
        lines.append(f"| {name} | {x['n']} | {x['mean']} | {x['p95']} | {x['unit']} |")
    lines += ["", "| Outcome | Succeeded | Failed | Success rate |", "|---|---|---|---|"]
    for name, oks in res.outcomes.items():
        good = sum(oks)
        lines.append(f"| {name} | {good} | {len(oks) - good} | {good / len(oks):.0%} |")
    if res.failures:
        lines += ["", "Failures:", *(f"- {f}" for f in res.failures[:30])]
    lines += ["", "Not measured in this run:"]
    missing = []
    if not args.llm_base_url:
        missing.append("model inference (no `--llm-base-url`)")
    if not args.vlm_model:
        missing.append("vision model (no `--vlm-model`)")
    if not args.api_url:
        missing.append("investigation time and worker memory (no `--api-url`)")
    lines += [f"- {m}" for m in missing] or ["- nothing: every optional measurement ran"]
    if res.extra.get("investigation_usage"):
        lines += [
            "",
            "Investigation usage (provider-reported): "
            f"`{json.dumps(res.extra['investigation_usage'])}`",
        ]
    lines += [
        "",
        "Notes:",
        "- Pipeline times are measured in-process with the worker's code, not through the queue.",
        "- Model times depend on the model server's hardware and load; the first call after a",
        "  model loads is slower and is included as measured.",
        *(f"- {n}" for n in res.notes),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--llm-base-url", default="")
    ap.add_argument("--llm-model", default="qwen2.5:7b-instruct")
    ap.add_argument("--vlm-model", default="")
    ap.add_argument("--api-url", default="")
    ap.add_argument("--write-docs", action="store_true")
    args = ap.parse_args()
    res = Results()
    with PeakRss() as rss:
        run_pipeline(res, args.runs)
        if args.llm_base_url:
            asyncio.run(run_llm(res, args.llm_base_url, args.llm_model, 1))
        if args.vlm_model and args.llm_base_url:
            asyncio.run(run_vlm(res, args.llm_base_url, args.vlm_model))
    res.add("Peak RSS of the pipeline process", rss.peak / 1024**2, "MiB")
    if args.api_url:
        run_investigation(res, args.api_url)
    report = markdown(res, args)
    print(report)
    if args.write_docs:
        DOCS.write_text(report, encoding="utf-8")
        print(f"wrote {DOCS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
