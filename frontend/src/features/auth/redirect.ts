/**
 * Where to go after sign-in. The path comes from the URL the visitor first opened, so it is
 * untrusted: only a path inside this app is accepted. "//host", "/\host", backslashes and
 * control characters (all ways browsers or the router can read as another origin) fall back
 * to the overview. Guards GHSA-wrjc-x8rr-h8h6 until react-router is upgraded.
 */
export function safeReturnPath(from: unknown): string {
  if (typeof from !== "string" || from === "/login") return "/";
  if (!from.startsWith("/") || from.startsWith("//")) return "/";
  if (from.includes("\\") || [...from].some((ch) => ch.charCodeAt(0) < 0x20 || ch.charCodeAt(0) === 0x7f)) {
    return "/";
  }
  if (from.length > 512) return "/";
  return from;
}
