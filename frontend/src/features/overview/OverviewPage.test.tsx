// Req: platform-foundation 6.1–6.3, 7.4
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { me, overview } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";

test("renders the values returned by the stats API", async () => {
  server.use(http.get("/api/v1/stats/overview", () => HttpResponse.json(overview())));
  signIn(me);
  renderAt("/");
  expect(await screen.findByLabelText("Members: 3")).toBeInTheDocument();
  expect(screen.getByLabelText("Audited events (7 days): 42")).toBeInTheDocument();
  expect(screen.getByText("83.3%")).toBeInTheDocument();
});

test("finding metrics show the counts computed by the API", async () => {
  server.use(http.get("/api/v1/stats/overview", () => HttpResponse.json(overview({
    findings_requiring_review: { value: 3, available: true, note: null },
    high_priority_findings: { value: 1, available: true, note: null },
  }))));
  signIn(me);
  renderAt("/");
  expect(await screen.findByLabelText("Documents processed: 7")).toBeInTheDocument();
  expect(screen.getByLabelText("Findings requiring review: 3")).toBeInTheDocument();
  expect(screen.getByLabelText("High-priority findings: 1")).toBeInTheDocument();
});

test("a metric the API marks unavailable says so instead of showing a number", async () => {
  server.use(http.get("/api/v1/stats/overview", () => HttpResponse.json(overview({
    high_priority_findings: { value: null, available: false, note: "Available in a later phase" },
  }))));
  signIn(me);
  renderAt("/");
  expect(await screen.findByLabelText("High-priority findings: available in a later phase")).toBeInTheDocument();
});

test("an API error shows the problem detail and Retry refetches", async () => {
  let calls = 0;
  server.use(
    http.get("/api/v1/stats/overview", () => {
      calls += 1;
      return calls === 1
        ? HttpResponse.json({ title: "Service unavailable", status: 503, detail: "Database unreachable" }, { status: 503 })
        : HttpResponse.json(overview({ members: { value: 9, available: true, note: null } }));
    }),
  );
  signIn(me);
  renderAt("/");
  expect(await screen.findByText("Database unreachable")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByLabelText("Members: 9")).toBeInTheDocument();
});

test("roles without system:ping don't get the worker-check button", async () => {
  server.use(http.get("/api/v1/stats/overview", () => HttpResponse.json(overview())));
  signIn({ ...me, role: "read_only_analyst", permissions: ["stats:read", "org:read"] });
  renderAt("/");
  await screen.findByLabelText("Members: 3");
  expect(screen.queryByRole("button", { name: "Run worker check" })).not.toBeInTheDocument();
});
