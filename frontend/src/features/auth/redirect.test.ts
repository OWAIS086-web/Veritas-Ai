// Req: enterprise-security 4.2 (documented react-router advisory, guarded here)
import { safeReturnPath } from "@/features/auth/redirect";

test("only paths inside the app are used after sign-in", () => {
  for (const ok of ["/", "/investigations/c-1", "/forensics?case=c-1&tab=compare", "/findings#x"]) {
    expect(safeReturnPath(ok)).toBe(ok);
  }
  for (const bad of [
    "//evil.example", "/\\evil.example", "\\\\evil.example", "/\\/evil.example", "https://evil.example",
    "javascript:alert(1)", "evil.example", "/\tevil", "/a\u0000b", "/login", "", null, undefined, 42,
    "/" + "a".repeat(600),
  ]) {
    expect(safeReturnPath(bad)).toBe("/");
  }
});
