/**
 * msw request interception for UI-state unit tests only. Real backend behavior is covered by
 * the backend integration suite and the Playwright end-to-end test against the running stack.
 */
import { setupServer } from "msw/node";

export const server = setupServer();
