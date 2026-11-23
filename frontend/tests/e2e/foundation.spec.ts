// Req: platform-foundation 5, 6, 7; authentication-rbac 1, 2, 5, 7 (end to end, real stack)
import { expect, test } from "@playwright/test";

const suffix = Date.now().toString(36);
const user = {
  name: "E2E Investigator",
  org: `E2E Customs ${suffix}`,
  email: `e2e-${suffix}@example.com`,
  password: `e2e-password-${suffix}`,
};

test("register, see live overview, run a real worker job, audit, settings, sign out and in", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Full name").fill(user.name);
  await page.getByLabel("Organization name").fill(user.org);
  await page.getByLabel("Work email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Create organization" }).click();

  // Overview: values come from the stats API for this brand-new organization.
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText(user.org)).toBeVisible();
  await expect(page.getByLabel("Members: 1")).toBeVisible();
  await expect(page.getByLabel("Jobs processed: 0")).toBeVisible();
  await expect(page.getByLabel("Documents processed: 0")).toBeVisible();
  await expect(page.getByLabel("Findings requiring review: 0")).toBeVisible();

  // A real Celery job, followed over server-sent events.
  await page.getByRole("button", { name: "Run worker check" }).click();
  await expect(page.getByRole("status", { name: "Worker check succeeded" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("list", { name: "Job events" }).getByRole("listitem")).toHaveCount(3);
  await expect(page.getByLabel("Jobs processed: 1")).toBeVisible();

  // Built sections show real empty states with a real next action.
  await page.getByRole("link", { name: "Findings" }).click();
  await expect(page.getByText("No findings yet")).toBeVisible();
  await page.getByRole("link", { name: "Reports" }).click();
  await expect(page.getByText("No investigations yet")).toBeVisible();
  await expect(page.getByRole("link", { name: "Create an investigation" })).toBeVisible();

  // Settings: rename the organization; the change is audited.
  await page.getByRole("link", { name: "Settings" }).click();
  const nameField = page.getByLabel("Organization name");
  await expect(nameField).toHaveValue(user.org);
  await nameField.fill(`${user.org} Renamed`);
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Organization updated")).toBeVisible();

  await page.getByRole("link", { name: "Audit Logs" }).click();
  await expect(page.getByText("organization.update")).toBeVisible();
  await expect(page.getByText("auth.register")).toBeVisible();

  // Session survives a reload (refresh-token restore), then sign out and back in.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Audit Logs" })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Work email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(`${user.org} Renamed`)).toBeVisible();
});

test("wrong password shows the generic error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Work email").fill(`nobody-${suffix}@example.com`);
  await page.getByLabel("Password").fill("definitely-wrong-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Invalid email or password.");
});
