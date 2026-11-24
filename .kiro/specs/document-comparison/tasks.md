# Tasks: Document Comparison Lab

Delivered as one implementation. A box is ticked only after its tests pass in the quality gate.

- [x] 1. Migration 0008, models, settings, permissions
  - Done when: the migration cycle has no drift and RLS isolation holds for the four tables.
  - _Requirements: 6.1, 7.2, 9.1_
- [x] 2. Geometry, rasters, page pairing and registration
  - Done when: a rotated and shifted page is recovered (unit) and the clip/round-trip properties hold.
  - _Requirements: 2.1–2.3_
- [x] 3. Text and pixel comparison, fusion
  - Done when: the altered fixture yields exactly its three changes, the re-saved copy none, and the scan its two changes plus the missing page.
  - _Requirements: 3.1–3.3, 4.1–4.2, 6.1–6.3_
- [x] 4. Vision model with validation
  - Done when: recorded qwen2.5vl:7b answers raise confidence without moving regions, boxes outside the image and proposals without pixels are rejected, and an unreachable model is called once.
  - _Requirements: 5.1–5.6_
- [x] 5. Worker, API, review and audit
  - Done when: the integration suite (upload → processing → comparison, review, failures, cross-org 404) passes.
  - _Requirements: 1.1–1.4, 7.1–7.2, 9.1–9.2_
- [x] 6. Annotated PDF and images, report PDF, findings JSON, signed downloads
  - Done when: downloads match their SHA-256, the annotated PDF has one rectangle per drawn finding inside the page, and the original is unchanged.
  - _Requirements: 8.1–8.4_
- [x] 7. Comparison Lab UI
  - Done when: the Vitest UI states and the Playwright run on the stack pass.
  - _Requirements: 9.2–9.3_
- [x] 8. Live run with qwen2.5vl:7b and documentation
  - Done when: the live test passes against a local Ollama and the docs record the measured numbers.
