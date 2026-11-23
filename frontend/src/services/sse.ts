/**
 * Server-sent events over fetch, so the bearer token travels in the Authorization header
 * (never in the URL) and reconnects resume with Last-Event-ID.
 */
import { API_BASE, authHeaders, refreshSession } from "@/services/api";

export interface SseMessage {
  id: number | null;
  event: string;
  data: unknown;
}

export function parseSseChunk(buffer: string): { messages: SseMessage[]; rest: string } {
  const messages: SseMessage[] = [];
  const blocks = buffer.split(/\r?\n\r?\n/);
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let id: number | null = null;
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith(":")) continue;
      const [field, ...valueParts] = line.split(":");
      const value = valueParts.join(":").replace(/^ /, "");
      if (field === "id") id = Number(value);
      else if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length === 0 && event === "message") continue;
    let parsed: unknown = data.join("\n");
    try {
      parsed = JSON.parse(data.join("\n"));
    } catch {
      /* keep raw text */
    }
    messages.push({ id, event, data: parsed });
  }
  return { messages, rest };
}

interface StreamOptions {
  onMessage: (msg: SseMessage) => void;
  signal: AbortSignal;
  maxReconnects?: number;
}

export async function streamEvents(path: string, opts: StreamOptions): Promise<void> {
  let lastId = 0;
  let reconnects = 0;
  const max = opts.maxReconnects ?? 5;
  while (!opts.signal.aborted) {
    try {
      let resp = await fetch(`${API_BASE}${path}`, {
        headers: { Accept: "text/event-stream", "Last-Event-ID": String(lastId), ...authHeaders() },
        signal: opts.signal,
      });
      if (resp.status === 401 && (await refreshSession())) {
        resp = await fetch(`${API_BASE}${path}`, {
          headers: { Accept: "text/event-stream", "Last-Event-ID": String(lastId),
                     ...authHeaders() },
          signal: opts.signal,
        });
      }
      if (!resp.ok || !resp.body) throw new Error(`stream failed: ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseChunk(buffer);
        buffer = parsed.rest;
        for (const msg of parsed.messages) {
          if (msg.id !== null) lastId = msg.id;
          opts.onMessage(msg);
          if (msg.event === "end") return;
        }
      }
      return;
    } catch (err) {
      if (opts.signal.aborted) return;
      reconnects += 1;
      if (reconnects > max) throw err;
      await new Promise((r) => setTimeout(r, Math.min(4000, 500 * 2 ** reconnects)));
    }
  }
}
