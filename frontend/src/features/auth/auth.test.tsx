// Req: authentication-rbac 1.1, 1.2, 2.1, 2.2
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { useAuth } from "@/stores/auth";
import { me, overview } from "@/test/fixtures";
import { renderAt } from "@/test/render";
import { server } from "@/test/server";

const tokens = { access_token: "a", refresh_token: "r", token_type: "bearer", expires_in: 900 };

test("successful sign-in stores the session and opens the overview", async () => {
  useAuth.setState({ status: "anonymous" });
  server.use(
    http.post("/api/v1/auth/login", () => HttpResponse.json(tokens)),
    http.get("/api/v1/auth/me", () => HttpResponse.json(me)),
    http.get("/api/v1/stats/overview", () => HttpResponse.json(overview())),
  );
  renderAt("/login");
  await userEvent.type(screen.getByLabelText("Work email"), "ana@example.com");
  await userEvent.type(screen.getByLabelText("Password"), "a-long-password");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
  expect(useAuth.getState().me?.user.email).toBe("ana@example.com");
  expect(window.localStorage.getItem("veritas.refresh")).toBe("r");
});

test("failed sign-in shows the server's generic message", async () => {
  useAuth.setState({ status: "anonymous" });
  server.use(
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json({ title: "Authentication required", status: 401, detail: "Invalid email or password." },
                        { status: 401 })),
  );
  renderAt("/login");
  await userEvent.type(screen.getByLabelText("Work email"), "ana@example.com");
  await userEvent.type(screen.getByLabelText("Password"), "wrong");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
  expect(useAuth.getState().status).toBe("anonymous");
});

test("registration blocks short passwords before calling the API", async () => {
  useAuth.setState({ status: "anonymous" });
  renderAt("/register");
  await userEvent.type(screen.getByLabelText("Password"), "short");
  expect(screen.getByText("Use at least 12 characters.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Create organization" })).toBeDisabled();
});

test("server field errors are shown next to the field", async () => {
  useAuth.setState({ status: "anonymous" });
  server.use(
    http.post("/api/v1/auth/register", () =>
      HttpResponse.json({ title: "Validation failed", status: 422, detail: "Request validation failed",
                          errors: [{ loc: ["body", "email"], msg: "value is not a valid email address" }] },
                        { status: 422 })),
  );
  renderAt("/register");
  await userEvent.type(screen.getByLabelText("Full name"), "Ana");
  await userEvent.type(screen.getByLabelText("Organization name"), "Harbor");
  await userEvent.type(screen.getByLabelText("Work email"), "ana@bad");
  await userEvent.type(screen.getByLabelText("Password"), "a-long-password-1");
  await userEvent.click(screen.getByRole("button", { name: "Create organization" }));
  expect(await screen.findByText("value is not a valid email address")).toBeInTheDocument();
});
