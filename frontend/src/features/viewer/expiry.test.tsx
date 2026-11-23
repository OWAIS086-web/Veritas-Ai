// Regression: an expired signed link (60 s) left the viewer stuck on "HTTP 403". The canvas now
// asks its parent for a fresh link once, and shows the error only if that fails too.
// Req: evidence-explorer design, failure handling ("an expired signed URL ... retries once").
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

import { ImageCanvas } from "@/features/viewer/ImageCanvas";
import PdfCanvas from "@/features/viewer/PdfCanvas";

afterEach(() => vi.unstubAllGlobals());

test("a refused PDF link asks for a fresh one instead of showing an error", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 403 }));
  vi.stubGlobal("fetch", fetchMock);
  const onExpired = vi.fn();
  const { rerender } = render(
    <PdfCanvas url="/api/v1/files/old" page={1} zoom={1} boxes={[]} width={600} onPageCount={() => undefined} onExpired={onExpired} />,
  );
  await waitFor(() => expect(onExpired).toHaveBeenCalledTimes(1));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  // The fresh link is refused as well: now the error is shown, and no endless retries.
  rerender(
    <PdfCanvas url="/api/v1/files/new" page={1} zoom={1} boxes={[]} width={600} onPageCount={() => undefined} onExpired={onExpired} />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 403");
  expect(onExpired).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("a failed image asks for a fresh link once, then reports the failure", () => {
  const onExpired = vi.fn();
  const { rerender } = render(<ImageCanvas url="/blob/old.png" alt="page" zoom={1} width={600} boxes={[]} onExpired={onExpired} />);
  fireEvent.error(screen.getByAltText("page"));
  expect(onExpired).toHaveBeenCalledTimes(1);
  rerender(<ImageCanvas url="/blob/new.png" alt="page" zoom={1} width={600} boxes={[]} onExpired={onExpired} />);
  fireEvent.error(screen.getByAltText("page"));
  expect(screen.getByRole("alert")).toHaveTextContent("Could not display the image");
  expect(onExpired).toHaveBeenCalledTimes(1);
});
