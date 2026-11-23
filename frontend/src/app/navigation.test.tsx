// Req: platform-foundation 7.1, 7.2
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { NAV_ITEMS } from "@/app/navigation";
import { useAuth } from "@/stores/auth";
import { me, overview } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";

const EXPECTED = [
  "Overview", "Investigations", "Documents", "Evidence Explorer", "Intelligence Graph",
  "Forensics Lab", "Findings", "Reports", "AI Agents", "Audit Logs", "Settings",
];

test("navigation has the 11 sections in the required order", async () => {
  server.use(http.get("/api/v1/stats/overview", () => HttpResponse.json(overview())));
  signIn(me);
  renderAt("/");
  const nav = await screen.findByRole("navigation", { name: "Main" });
  const labels = within(nav).getAllByRole("link").map((a) => a.getAttribute("title"));
  expect(labels).toEqual(EXPECTED);
  expect(NAV_ITEMS.map((n) => n.label)).toEqual(EXPECTED);
});

test.each(NAV_ITEMS.filter((n) => n.pending).map((n) => [n.label, n.path, n.pending?.phase] as const))(
  "%s shows the explicit pending state, not sample data",
  async (label, path, phase) => {
    signIn(me);
    renderAt(path);
    expect(await screen.findByRole("heading", { level: 1, name: label })).toBeInTheDocument();
    expect(screen.getByText("Available in a later phase")).toBeInTheDocument();
    expect(screen.getByText(`Planned for phase ${phase}`)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  },
);

test("unauthenticated users are redirected to sign in", async () => {
  useAuth.setState({ status: "anonymous" });
  renderAt("/settings");
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
});
