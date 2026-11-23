"""Document comparison lab: registration, text and pixel comparison, the engine on the
synthetic comparison fixtures, the vision-model validation, annotation and report output."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf
import pytest

from app.integrations.llm.replay import ReplayProvider
from app.services.doccompare import report
from app.services.doccompare.annotate import Mark, annotated_images, annotated_pdf
from app.services.doccompare.engine import DocInput, EngineSettings, run
from app.services.doccompare.fusion import Candidate, score
from app.services.doccompare.geometry import overlaps
from app.services.doccompare.pages import UnsupportedDocumentError, pair_pages, rasters
from app.services.doccompare.registration import register, warp_to_test
from app.services.doccompare.text import differs, digits
from app.services.doccompare.vision import Vision, VisionStats, fit, in_image
from app.services.doccompare.visual import detect
from app.services.parsing.pdf import parse_text_page

ROOT = Path(__file__).resolve().parents[3] / "sample-data" / "comparison"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
RECORDED = (
    Path(__file__).resolve().parents[1] / "fixtures" / "llm" / "doccompare_vision_altered.json"
)
CFG = EngineSettings(
    dpi=144, max_pages=20, work_width=1000, ssim_threshold=0.6, vlm_max_regions=8, vlm_max_pages=1
)
PDF = "application/pdf"


def _doc(name: str, fields: list[dict[str, Any]] | None = None) -> DocInput:
    """A comparison input with the text layer the pipeline would store (PDF fixtures only)."""
    data = (ROOT / name).read_bytes()
    with pymupdf.open(stream=data, filetype="pdf") as d:
        pages = [
            {
                "page_number": i + 1,
                "method": "text_layer",
                "lines": [ln.to_json() for ln in parse_text_page(d[i], i + 1).lines],
            }
            for i in range(len(d))
        ]
    return DocInput(name, name, data, PDF, hashlib.sha256(data).hexdigest(), pages, fields or [])


async def _noop(stage: str, pct: int) -> None:
    return None


def _change(key: str) -> dict[str, Any]:
    return dict(MANIFEST["changes"][key])


# --- registration and pixels ------------------------------------------------------------


def _work(name: str, page: int = 0) -> np.ndarray:
    r = rasters((ROOT / name).read_bytes(), PDF, 144, 5)[page]
    h, w = r.gray.shape
    return np.asarray(cv2.resize(r.gray, (1000, round(h * 1000 / w))), dtype=np.uint8)


def test_registration_recovers_a_rotation_and_shift() -> None:
    original = _work("original_invoice.pdf")
    h, w = original.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 1.5, 1.0)
    m[:, 2] += (12, -7)
    moved = np.asarray(cv2.warpAffine(original, m, (w, h), borderValue=255), dtype=np.uint8)
    reg = register(moved, original)
    assert reg.method != "identity"
    assert reg.ssim > 0.9
    # A point of the moved page maps back onto where it came from in the original.
    src = np.array([400.0, 300.0, 1.0])
    moved_pt = np.append(m @ src, 1.0)
    back = reg.matrix @ moved_pt
    assert np.allclose(back[:2] / back[2], src[:2], atol=3.0)
    assert warp_to_test(original, reg.matrix, (w, h)).shape == moved.shape


def test_identical_pages_keep_the_identity_alignment_and_no_pixel_regions() -> None:
    data = (ROOT / "original_invoice.pdf").read_bytes()
    rs = rasters(data, PDF, 144, 5)
    sizes = [(595.0, 842.0)] * len(rs)
    for pair in pair_pages(rs, sizes, rs, sizes, 1000):
        assert pair.registration.method == "identity"
        regions, changed = detect(pair, 0.6)
        assert regions == [] and int(changed.sum()) == 0


def test_pixel_regions_cover_the_changed_total_inside_page_bounds() -> None:
    o, t = (ROOT / "original_invoice.pdf").read_bytes(), (ROOT / "test_altered.pdf").read_bytes()
    sizes = [(595.0, 842.0)] * 2
    pairs = pair_pages(rasters(o, PDF, 144, 5), sizes, rasters(t, PDF, 144, 5), sizes, 1000)
    regions, _ = detect(pairs[0], 0.6)
    total = _change("total")["box"]
    assert any(overlaps(r.region, total) for r in regions)
    for r in regions:
        assert 0 <= r.region[0] < r.region[2] <= 595 and 0 <= r.region[1] < r.region[3] <= 842


def test_unsupported_types_are_refused() -> None:
    with pytest.raises(UnsupportedDocumentError):
        rasters(b"a,b\n1,2\n", "text/csv", 144, 5)


# --- text rules -------------------------------------------------------------------------


def test_text_rules() -> None:
    assert differs("USD 48,000.00", "USD 68,000.00", "ocr")
    assert not differs("Invoice  Total", "invoice total", "text_layer")
    assert differs("Northwind", "Northwlnd", "text_layer")  # a text layer must match exactly
    assert not differs("Northwind Imports", "Northwlnd Imports", "ocr")  # OCR noise tolerated
    assert digits("USD 48,000.00") == ["48000", "00"]


# --- the engine on the fixtures ---------------------------------------------------------


async def test_engine_finds_exactly_the_planted_changes() -> None:
    result = await run(_doc("original_invoice.pdf"), _doc("test_altered.pdf"), CFG, None, _noop)
    assert len(result.findings) == len(MANIFEST["expected"]["test_altered.pdf"])
    for key in MANIFEST["expected"]["test_altered.pdf"]:
        change = _change(key)
        hits = [
            f
            for f in result.findings
            if f.test_page == change["page"] and f.region and overlaps(f.region, change["box"])
        ]
        assert len(hits) == 1, key
        f = hits[0]
        assert f.type == "text_changed" and f.severity == "medium" and f.digits_changed
        assert f.test_text and f.test_text in change["test"]
        assert f.original_text and f.original_text in change["original"]
        assert f.original_region and overlaps(f.original_region, change["box"])
        assert 0.05 <= f.confidence <= 0.95
    assert [f.test_page for f in result.findings] == sorted(
        f.test_page or 0 for f in result.findings
    )
    assert result.summary["test"]["sha256"] == MANIFEST["files"]["test_altered.pdf"]["sha256"]
    assert {p["alignment"] for p in result.summary["pages"]} == {"identity"}


async def test_engine_reports_nothing_for_a_resaved_copy() -> None:
    result = await run(_doc("original_invoice.pdf"), _doc("test_resaved.pdf"), CFG, None, _noop)
    assert result.findings == []
    assert result.summary["findings"] == 0


async def test_engine_attaches_overlapping_extracted_fields() -> None:
    total = _change("total")
    field = {
        "id": "00000000-0000-0000-0000-00000000f001",
        "name": "total_amount",
        "value": total["test"],
        "value_type": "amount",
        "page_number": 1,
        "bbox": total["box"],
    }
    result = await run(
        _doc("original_invoice.pdf"), _doc("test_altered.pdf", [field]), CFG, None, _noop
    )
    hit = next(f for f in result.findings if f.region and overlaps(f.region, total["box"]))
    assert [x["id"] for x in hit.fields] == [field["id"]]
    assert "overlaps the extracted total amount" in hit.explanation


async def test_page_count_differences_are_reported() -> None:
    o = _doc("original_invoice.pdf")
    one_page = pymupdf.open(stream=o.data, filetype="pdf")
    one_page.select([0])
    data = one_page.tobytes()
    t = DocInput("t", "t.pdf", data, PDF, hashlib.sha256(data).hexdigest(), o.pages[:1], [])
    result = await run(o, t, CFG, None, _noop)
    removed = [f for f in result.findings if f.type == "page_removed"]
    assert len(removed) == 1 and removed[0].original_page == 2 and removed[0].test_page is None
    added = await run(t, o, CFG, None, _noop)
    assert [f.test_page for f in added.findings if f.type == "page_added"] == [2]


# --- the vision model is checked, never trusted ----------------------------------------


async def test_recorded_vision_answers_raise_confidence_but_their_boxes_are_validated() -> None:
    provider = ReplayProvider.from_file(RECORDED)
    vision = Vision(provider, "qwen2.5vl:7b", VisionStats(model="qwen2.5vl:7b"))
    plain = await run(_doc("original_invoice.pdf"), _doc("test_altered.pdf"), CFG, None, _noop)
    seen = await run(_doc("original_invoice.pdf"), _doc("test_altered.pdf"), CFG, vision, _noop)
    assert len(seen.findings) == len(plain.findings)  # the model adds no finding here
    for before, after in zip(plain.findings, seen.findings, strict=True):
        assert after.region == before.region  # regions come from text boxes and pixels
        assert after.vlm and after.vlm["status"] == "assessed"
        assert after.vlm["visible_difference"] is True
        assert after.vlm["text_check"]["test"] == "consistent"
        assert after.confidence == pytest.approx(min(0.95, before.confidence + 0.10))
        assert "vlm" in after.sources
    stats = seen.vlm or {}
    assert stats["status"] == "used" and stats["calls"] == 4
    # The recorded page-scan boxes sit 30-40 px off the changed text: no changed pixels.
    assert {r["reason"] for r in stats["proposals_rejected"]} == {"no_pixel_difference"}
    assert stats["tokens"] == sum(
        r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"]
        for r in json.loads(RECORDED.read_text(encoding="utf-8"))["responses"]
    )


async def test_a_proposal_is_kept_only_where_pixels_changed_and_uses_the_pixel_box() -> None:
    o, t = _doc("original_invoice.pdf"), _doc("test_altered.pdf")
    plain = await run(o, t, CFG, None, _noop)
    total = next(
        f for f in plain.findings if f.region and overlaps(f.region, _change("total")["box"])
    )
    # A page-scan answer: one box on the changed total (sent-image px), one on blank paper,
    # one outside the image. The region checks fail, so only the page scan counts.
    _, fx, _ = fit(np.zeros((1684, 1190, 3), np.uint8), 1008)
    s = 144 / 72 * fx
    box = [v * s for v in total.region or []]
    answers: list[dict[str, Any]] = [{"error": "unavailable"}] * 3 + [
        {
            "content": {
                "regions": [
                    {"box": [box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4], "description": "x"},
                    {"box": [600, 900, 680, 960], "description": "blank paper"},
                    {"box": [5000, 10, 5100, 40], "description": "outside"},
                ]
            }
        }
    ]

    vision = Vision(ReplayProvider(answers), "m", VisionStats(model="m"))
    vision.stats.calls = 1  # behaves as a reachable model whose region checks failed
    seen = await run(o, t, CFG, vision, _noop)
    rejected = {r["reason"] for r in (seen.vlm or {})["proposals_rejected"]}
    assert rejected == {"no_pixel_difference", "outside_image"}
    hit = next(f for f in seen.findings if f.region == total.region)
    assert hit.metrics.get("vlm_page_scan") and "vlm" in hit.sources
    assert len(seen.findings) == len(plain.findings)


async def test_an_unreachable_model_is_not_retried_for_every_region() -> None:
    vision = Vision(ReplayProvider([{"error": "connection refused"}]), "m", VisionStats())
    result = await run(_doc("original_invoice.pdf"), _doc("test_altered.pdf"), CFG, vision, _noop)
    assert (result.vlm or {})["status"] == "failed"
    assert len((result.vlm or {})["errors"]) == 1
    assert all((f.vlm or {}).get("status") in (None, "error") for f in result.findings)


def test_boxes_outside_the_image_are_invalid() -> None:
    assert in_image([1, 1, 50, 50], 100, 100)
    assert not in_image([405, 215, 979, 280], 500, 100)  # observed from qwen2.5vl:7b
    assert not in_image([50, 50, 10, 60], 100, 100)
    img, fx, fy = fit(np.zeros((1684, 1190, 3), np.uint8), 1008)
    assert img.shape[0] % 28 == 0 and img.shape[1] % 28 == 0 and max(img.shape[:2]) <= 1008
    assert fx == pytest.approx(img.shape[1] / 1190) and fy == pytest.approx(img.shape[0] / 1684)


def test_vision_disagreement_lowers_confidence() -> None:
    c = Candidate(
        "text_changed",
        1,
        1,
        [1, 1, 5, 5],
        [1, 1, 5, 5],
        ["ocr", "cv"],
        method="text_layer",
        digits_changed=True,
    )
    score(c, 0.99)
    base = c.confidence
    c.vlm = {"status": "assessed", "visible_difference": False}
    score(c, 0.99)
    assert c.confidence == pytest.approx(base - 0.10)
    score(c, 0.3)
    assert c.confidence == pytest.approx(base - 0.25)


# --- annotated files and reports --------------------------------------------------------


def _marks() -> list[Mark]:
    return [
        Mark(1, 1, _change("total")["box"], "medium", "total changed"),
        Mark(2, 2, _change("account")["box"], "low", "account changed"),
        Mark(3, 1, [900, 900, 950, 950], "low", "outside the page"),
        Mark(4, 7, [10, 10, 20, 20], "info", "no such page"),
    ]


def test_annotated_pdf_marks_valid_regions_and_leaves_the_input_unchanged() -> None:
    data = (ROOT / "test_altered.pdf").read_bytes()
    before = hashlib.sha256(data).hexdigest()
    out, stats = annotated_pdf(data, PDF, _marks(), None, 144, 20)
    assert hashlib.sha256(data).hexdigest() == before
    assert (stats.drawn, stats.skipped) == (2, 2)
    with pymupdf.open(stream=out, filetype="pdf") as d:
        assert len(d) == 2
        rects = [a.rect for p in d for a in p.annots() if a.type[1] == "Square"]
        assert len(rects) == 2
        assert all(d[0].rect.contains(r) for r in rects)
        tags = [a.info["content"] for p in d for a in p.annots() if a.type[1] == "FreeText"]
        assert tags == ["#1", "#2"]


def test_annotated_pdf_from_an_image_and_the_png_zip() -> None:
    data = (ROOT / "test_scanned_altered.png").read_bytes()
    h, w = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape[:2]
    marks = [
        Mark(1, 1, [420, 490, 566, 523], "medium", "total"),
        Mark(2, 1, [w, h, w + 9, h + 9], "low", "x"),
    ]
    out, stats = annotated_pdf(data, "image/png", marks, None, 144, 20)
    with pymupdf.open(stream=out, filetype="pdf") as d:
        assert len(d) == 1 and (d[0].rect.width, d[0].rect.height) == (w, h)
    assert (stats.drawn, stats.skipped) == (1, 1)
    zipped, zstats = annotated_images(data, "image/png", marks, "notes", 144, 20)
    names = zipfile.ZipFile(io.BytesIO(zipped)).namelist()
    assert names == ["test-page-001-annotated.png", "README.txt"]
    assert (zstats.drawn, zstats.skipped) == (1, 1)


def test_report_escapes_document_text_and_json_carries_the_schema() -> None:
    payload = {
        "comparison": {"id": "c1", "vlm_status": "disabled"},
        "generated_at": "2026-11-23T00:00:00Z",
        "original": {"filename": "<b>orig</b>.pdf", "sha256": "a" * 64},
        "test": {"filename": "test.pdf", "sha256": "b" * 64},
        "summary": {"pages": [{"test_page": 1, "original_page": 1, "alignment": "identity"}]},
        "findings": [
            {
                "number": 1,
                "type": "text_changed",
                "severity": "medium",
                "evidence_confidence": 0.8,
                "sources": ["ocr", "cv"],
                "test_page": 1,
                "region": _change("total")["box"],
                "original_page": 1,
                "original_region": _change("total")["box"],
                "explanation": "reads <script>alert(1)</script>",
                "review_status": "unreviewed",
            }
        ],
        "limitations": ["A difference is not proof."],
    }
    pdf = report.report_pdf(
        payload,
        ((ROOT / "original_invoice.pdf").read_bytes(), PDF),
        ((ROOT / "test_altered.pdf").read_bytes(), PDF),
        144,
        20,
    )
    with pymupdf.open(stream=pdf, filetype="pdf") as d:
        text = "".join(p.get_text() for p in d)
        assert "<script>alert(1)</script>" in text and "<b>orig</b>.pdf" in text
        assert sum(len(p.get_images()) for p in d) == 2  # original and test crop
    data = json.loads(report.findings_json(payload))
    assert data["schema"] == report.SCHEMA and data["findings"][0]["number"] == 1
