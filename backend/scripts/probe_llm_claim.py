"""Diagnostic: show the model's raw claims for one sample PDF next to the verified result.

Usage (inside the worker container): python scripts/probe_llm_claim.py <path-to-pdf> <doc_type>
Reads only the given file; nothing is written to the database.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.integrations.llm.openai_compat import configured_provider
from app.services.extraction import llm
from app.services.parsing.dispatch import parse_document


async def main(data: bytes, doc_type: str) -> None:
    provider = configured_provider()
    if provider is None:
        raise SystemExit("VERITAS_LLM_* is not configured")
    pages = parse_document(data, "application/pdf").pages
    completion = await provider.complete_json(llm.build_messages(doc_type, pages))
    print("raw claims:", completion.content)
    values, notes = await llm.extract(provider, doc_type, pages)
    for v in values:
        print(f"{v.name:20} {v.status:10} {v.rejection_reason or '':28} {v.value!r}")
    print("notes:", notes)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).read_bytes(), sys.argv[2]))
