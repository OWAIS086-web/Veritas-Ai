import type { FieldOut } from "@/types/api";

export const DOC_TYPE_LABELS: Record<string, string> = {
  purchase_order: "Purchase order",
  commercial_invoice: "Commercial invoice",
  packing_list: "Packing list",
  bill_of_lading: "Bill of lading",
  customs_declaration: "Customs declaration",
  certificate_of_origin: "Certificate of origin",
  insurance_certificate: "Insurance certificate",
  payment_receipt: "Payment receipt",
  supplier_agreement: "Supplier agreement",
  inspection_certificate: "Inspection certificate",
  unknown: "Unclassified",
};

export const FIELD_LABELS: Record<string, string> = {
  document_number: "Document number",
  document_date: "Document date",
  supplier: "Supplier / seller",
  buyer: "Buyer / importer",
  shipment_reference: "Shipment reference",
  invoice_reference: "Invoice reference",
  po_reference: "PO reference",
  bill_of_lading_reference: "Bill of lading",
  bank_reference: "Bank reference",
  currency: "Currency",
  total_amount: "Total amount",
  total_quantity: "Total quantity",
  total_cartons: "Total cartons",
  gross_weight: "Gross weight",
  incoterms: "Incoterms",
  valuation_basis: "Valuation basis",
  vessel: "Vessel",
  insurer: "Insurer",
  port_of_loading: "Port of loading",
  port_of_discharge: "Port of discharge",
};

export const STAGE_LABELS: Record<string, string> = {
  parse: "Parse / OCR",
  classify: "Classify",
  extract: "Extract",
  validate: "Validate",
};

export const METHOD_LABELS: Record<string, string> = {
  text_layer: "PDF text layer",
  ocr: "OCR (PaddleOCR)",
  parser: "Direct parser",
  llm: "Model",
  rules: "Rules",
};

/** How a field was read. A model value is only kept after it is found in the page's own text,
 * so the label also names that text source (text layer, OCR or parser). */
export function methodLabel(
  f: Pick<FieldOut, "method" | "status" | "page_number">,
  pageMethods: Record<number, string>,
): string {
  const base = METHOD_LABELS[f.method] ?? f.method;
  if (f.method !== "llm" || f.status !== "extracted") return base;
  const source = f.page_number != null ? pageMethods[f.page_number] : undefined;
  return source ? `${base}, verified on ${METHOD_LABELS[source] ?? source}` : base;
}

export const INVESTIGATION_TYPES: Record<string, string> = {
  international_shipment: "International shipment",
  trade_finance: "Trade finance",
  insurance_claim: "Insurance claim",
  procurement: "Procurement",
  other: "Other",
};

export const docTypeLabel = (t: string | null | undefined) =>
  t ? (DOC_TYPE_LABELS[t] ?? t.replaceAll("_", " ")) : "Not classified yet";

export const fieldLabel = (name: string) => FIELD_LABELS[name] ?? name.replaceAll("_", " ");

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** Human form of a normalized value; the raw document text stays the source of truth. */
export function formatNormalized(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  if (typeof v.amount === "string") {
    const n = Number(v.amount);
    const amount = n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return `${v.currency ?? "currency unknown"} ${amount}`;
  }
  if (typeof v.date === "string") return v.role ? `${v.date} (${String(v.role).replaceAll("_", " ")})` : v.date;
  if (typeof v.quantity === "string") return `${Number(v.quantity).toLocaleString()}${v.unit ? ` ${v.unit}` : ""}`;
  if (typeof v.currency === "string") return v.currency;
  return null;
}
