// Req: document-intelligence (provenance shown per field)
import { methodLabel } from "@/features/documents/labels";

test("a verified model value names the page text it was checked against", () => {
  const pages = { 1: "text_layer", 2: "ocr" };
  expect(methodLabel({ method: "llm", status: "extracted", page_number: 1 }, pages))
    .toBe("Model, verified on PDF text layer");
  expect(methodLabel({ method: "llm", status: "extracted", page_number: 2 }, pages))
    .toBe("Model, verified on OCR (PaddleOCR)");
  // A rejected model claim was not verified against anything.
  expect(methodLabel({ method: "llm", status: "uncertain", page_number: 1 }, pages)).toBe("Model");
  expect(methodLabel({ method: "text_layer", status: "extracted", page_number: 1 }, pages))
    .toBe("PDF text layer");
});
