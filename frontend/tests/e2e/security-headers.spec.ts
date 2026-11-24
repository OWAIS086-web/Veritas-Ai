// Req: enterprise-security 3.1, 3.2 (Nginx on the real stack)
import { expect, type APIResponse, test } from "@playwright/test";

const COMMON = {
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
  "referrer-policy": "strict-origin-when-cross-origin",
};

function expectCommon(resp: APIResponse, where: string) {
  const h = resp.headers();
  for (const [name, value] of Object.entries(COMMON)) {
    expect(h[name], `${where}: ${name}`).toBe(value);
  }
  expect(h["permissions-policy"], `${where}: permissions-policy`).toContain("camera=()");
  expect(h["server"] ?? "", `${where}: server version hidden`).not.toMatch(/\d/);
}

test("every kind of response carries the security headers", async ({ request, page }) => {
  await page.goto("/login");
  const html = await (await request.get("/login")).text();
  const asset = html.match(/src="(\/assets\/[^"]+\.js)"/)?.[1];
  expect(asset, "an /assets/ script on the login page").toBeTruthy();

  const spa = await request.get("/investigations");
  expect(spa.status()).toBe(200);
  expectCommon(spa, "SPA");
  const csp = spa.headers()["content-security-policy"];
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).not.toContain("unsafe-eval");
  expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);

  expectCommon(await request.get(asset as string), "asset");
  const api = await request.get("/api/v1/system/health");
  expectCommon(api, "API");
  expect(api.headers()["content-security-policy"]).toContain("default-src 'none'");
  const problem = await request.get("/api/v1/cases");
  expect(problem.status()).toBe(401);
  expectCommon(problem, "API error");
  expectCommon(await request.get("/healthz"), "healthz");
});

test("HSTS is sent only when the request arrived over HTTPS at the edge", async ({ request }) => {
  const plain = await request.get("/login");
  expect(plain.headers()["strict-transport-security"]).toBeUndefined();
  const tls = await request.get("/login", { headers: { "X-Forwarded-Proto": "https" } });
  expect(tls.headers()["strict-transport-security"]).toBe("max-age=31536000; includeSubDomains");
});

test("CORS through Nginx answers only the configured origins", async ({ request }) => {
  const preflight = (origin: string) =>
    request.fetch("/api/v1/cases", {
      method: "OPTIONS",
      headers: { Origin: origin, "Access-Control-Request-Method": "GET" },
    });
  const good = await preflight("http://localhost:8080");
  expect(good.headers()["access-control-allow-origin"]).toBe("http://localhost:8080");
  for (const origin of ["https://evil.example", "http://localhost:8080.evil.example"]) {
    expect((await preflight(origin)).headers()["access-control-allow-origin"]).toBeUndefined();
  }
});
