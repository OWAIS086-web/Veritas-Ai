# SYNTHETIC DEMONSTRATION DATA

Fictional documents for the VERITAS AI demo case "International Shipment Financial Discrepancy Investigation". All companies, people, references and amounts are invented. Regenerate with `uv run python backend/scripts/generate_samples.py`.

- `shipment-case/`: the 7 demo PDFs (PO, invoice and receipt declare USD 48,000; customs declaration and insurance certificate declare USD 68,000; packing list and bill of lading both list 1,000 units).
- `format-variants/`: the same content as scanned PDF, PNG, JPG, TIFF, DOCX, XLSX, CSV and EML, used to test each ingestion path.
- `manifest.json`: hashes and ground truth used **only by tests**.
