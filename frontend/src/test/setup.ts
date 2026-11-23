import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "@/test/server";
import { useAuth } from "@/stores/auth";

// Recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

// React Flow reads the viewport transform through DOMMatrixReadOnly, which jsdom lacks.
class DOMMatrixStub {
  m22: number;
  constructor(transform?: string) {
    const scale = /scale\(([\d.]+)\)/.exec(transform ?? "")?.[1];
    this.m22 = scale ? Number(scale) : 1;
  }
}
(globalThis as { DOMMatrixReadOnly?: unknown }).DOMMatrixReadOnly ??= DOMMatrixStub;

// React Router builds a Node (undici) Request with jsdom's AbortSignal, which undici rejects.
// Tests don't cancel navigations, so the signal is dropped in the test environment only.
const NodeRequest = globalThis.Request;
globalThis.Request = class extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (init?.signal) {
      const rest = { ...init };
      delete rest.signal;
      super(input, rest);
    } else {
      super(input, init);
    }
  }
} as typeof Request;

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
  useAuth.setState({ status: "unknown", accessToken: null, me: null });
});
afterAll(() => server.close());
