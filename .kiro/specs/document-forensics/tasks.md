# Tasks: Document Forensics

- [x] 1. Migration 0005 and models
  - Done when: the migration cycle passes and RLS isolation holds.
- [x] 2. PDF structure analysis
  - Done when: the incremental-update fixture is detected and metadata inconsistency is flagged.
  - _Requirements: 1.1–1.3_
- [x] 3. Visual noise and compression analysis
  - Done when: the recompressed-region fixture is flagged and the clean fixture is not.
  - _Requirements: 2.1_
- [x] 4. Version comparison (alignment and SSIM)
  - Done when: the edited region is detected in the version pair.
  - _Requirements: 2.2_
- [x] 5. Signature and stamp regions
  - Done when: stamps on the samples are located and the variation fixture is flagged.
  - _Requirements: 2.3_
- [x] 6. Pipeline stage, API and limitations property
  - _Requirements: 3.1–3.4, 4.1_
- [x] 7. Forensics Lab UI
  - _Requirements: 4.2_
