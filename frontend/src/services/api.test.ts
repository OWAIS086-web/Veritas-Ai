// Req: platform-foundation 7.3, 7.4
import { http, HttpResponse } from "msw";

import { api, ApiError, request } from "@/services/api";
import { parseSseChunk } from "@/services/sse";
import { useAuth } from "@/stores/auth";
import { server } from "@/test/server";

test("problem+json errors become ApiError with title, detail and field errors", async () => {
  server.use(
    http.post("/api/v1/auth/register", () =>
      HttpResponse.json(
        { type: "about:blank", title: "Validation failed", status: 422, detail: "Request validation failed",
          errors: [{ loc: ["body", "password"], msg: "too short" }], request_id: "abc" },
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      ),
    ),
  );
  const err = await api
    .register({ email: "a@example.com", password: "x", full_name: "A", organization_name: "Org" })
    .catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  const apiErr = err as ApiError;
  expect(apiErr.status).toBe(422);
  expect(apiErr.errors[0]?.loc).toEqual(["body", "password"]);
  expect(apiErr.requestId).toBe("abc");
});

test("a 401 triggers one shared refresh and the requests are retried with the new token", async () => {
  window.localStorage.setItem("veritas.refresh", "refresh-1");
  useAuth.setState({ accessToken: "expired" });
  let refreshCalls = 0;
  const seen: string[] = [];
  server.use(
    http.post("/api/v1/auth/refresh", async ({ request: req }) => {
      refreshCalls += 1;
      expect(await req.json()).toEqual({ refresh_token: "refresh-1" });
      return HttpResponse.json({ access_token: "fresh", refresh_token: "refresh-2", token_type: "bearer", expires_in: 900 });
    }),
    http.get("/api/v1/jobs/:id", ({ request: req }) => {
      const auth = req.headers.get("Authorization") ?? "";
      seen.push(auth);
      return auth === "Bearer fresh"
        ? HttpResponse.json({ id: "j" })
        : HttpResponse.json({ title: "Authentication required", status: 401, detail: "expired" }, { status: 401 });
    }),
  );
  await Promise.all([request("/jobs/1"), request("/jobs/2")]);
  expect(refreshCalls).toBe(1);
  expect(window.localStorage.getItem("veritas.refresh")).toBe("refresh-2");
  expect(seen.filter((h) => h === "Bearer fresh")).toHaveLength(2);
});

test("a failed refresh signs the user out", async () => {
  window.localStorage.setItem("veritas.refresh", "revoked");
  useAuth.setState({ accessToken: "expired", status: "authenticated" });
  server.use(
    http.post("/api/v1/auth/refresh", () => HttpResponse.json({ title: "x", status: 401, detail: "" }, { status: 401 })),
    http.get("/api/v1/auth/me", () => HttpResponse.json({ title: "x", status: 401, detail: "nope" }, { status: 401 })),
  );
  await expect(api.me()).rejects.toMatchObject({ status: 401 });
  expect(useAuth.getState().status).toBe("anonymous");
  expect(window.localStorage.getItem("veritas.refresh")).toBeNull();
});

test("SSE parser handles ids, events, comments and partial chunks", () => {
  const first = parseSseChunk('id: 1\nevent: queued\ndata: {"seq":1}\n\n: keep-alive\n\nid: 2\nevent: sta');
  expect(first.messages).toEqual([{ id: 1, event: "queued", data: { seq: 1 } }]);
  const second = parseSseChunk(`${first.rest}rted\ndata: {"seq":2}\n\nevent: end\ndata: {}\n\n`);
  expect(second.messages.map((m) => [m.id, m.event])).toEqual([[2, "started"], [null, "end"]]);
  expect(second.rest).toBe("");
});
