// Req: authentication-rbac 6.1, 6.2; ui-design (confirmation dialogs, toasts)
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { me } from "@/test/fixtures";
import { renderAt, signIn } from "@/test/render";
import { server } from "@/test/server";

const members = [
  { user_id: "u-1", email: "ana@example.com", full_name: "Ana Investigator", role: "org_admin", created_at: "2026-11-20T10:00:00Z" },
  { user_id: "u-2", email: "ben@example.com", full_name: "Ben Reviewer", role: "reviewer", created_at: "2026-11-21T10:00:00Z" },
];

function baseHandlers() {
  server.use(
    http.get("/api/v1/organizations/o-1", () => HttpResponse.json(me.organization)),
    http.get("/api/v1/organizations/o-1/members", () => HttpResponse.json(members)),
  );
}

test("removing a member asks for confirmation, then calls the API", async () => {
  baseHandlers();
  let deleted: string | null = null;
  server.use(
    http.delete("/api/v1/organizations/o-1/members/:userId", ({ params }) => {
      deleted = String(params.userId);
      return new HttpResponse(null, { status: 204 });
    }),
  );
  signIn(me);
  renderAt("/settings");
  await userEvent.click(await screen.findByRole("button", { name: "Remove ben@example.com" }));
  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText(/will lose access/)).toBeInTheDocument();
  expect(deleted).toBeNull();
  await userEvent.click(within(dialog).getByRole("button", { name: "Remove member" }));
  expect(await screen.findByText("Member removed")).toBeInTheDocument();
  expect(deleted).toBe("u-2");
});

test("the last-admin conflict from the API is shown as an error toast", async () => {
  baseHandlers();
  server.use(
    http.patch("/api/v1/organizations/o-1/members/u-1", () =>
      HttpResponse.json({ title: "Conflict", status: 409,
                          detail: "The organization must keep at least one Organization Admin." },
                        { status: 409 })),
  );
  signIn(me);
  renderAt("/settings");
  const select = await screen.findByLabelText("Role for ana@example.com");
  await userEvent.selectOptions(select, "investigator");
  expect(await screen.findByText("The organization must keep at least one Organization Admin.")).toBeInTheDocument();
});

test("roles without members:manage see the list but no controls", async () => {
  baseHandlers();
  signIn({ ...me, role: "reviewer", permissions: ["members:read", "org:read"] });
  renderAt("/settings");
  expect(await screen.findByText("ben@example.com")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Organization name")).toBeDisabled();
});
