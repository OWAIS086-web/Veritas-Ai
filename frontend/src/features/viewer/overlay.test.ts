// Req: document-intelligence 3.1 (boxes drawn where the value is printed)
import { fitScale, toCssRect } from "@/features/viewer/overlay";

test("a PDF-point box scales onto the rendered page with padding", () => {
  // A value at x 200-260, y 400-412 points on a page rendered at 1.5x.
  expect(toCssRect([200, 400, 260, 412], 1.5)).toEqual({ left: 298, top: 598, width: 94, height: 22 });
});

test("invalid boxes are not drawn", () => {
  expect(toCssRect([10, 10, 5, 20], 1)).toBeNull();
  expect(toCssRect([1, 2, 3], 1)).toBeNull();
  expect(toCssRect([0, 0, Number.NaN, 4], 1)).toBeNull();
  expect(toCssRect([0, 0, 10, 10], 0)).toBeNull();
});

test("fit scale maps the page width onto the container, then applies zoom", () => {
  expect(fitScale(1190, 595, 1)).toBe(2);
  expect(fitScale(1190, 595, 0.5)).toBe(1);
  expect(fitScale(0, 595, 1.25)).toBe(1.25);
});
