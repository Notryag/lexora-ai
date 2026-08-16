import assert from "node:assert/strict";
import test from "node:test";

import { readSseFrames } from "../src/features/workspace/sse.ts";

test("parses fragmented SSE frames with IDs and CRLF", async () => {
  const response = streamResponse([
    "id: 0-0\r\nevent: meta",
    "data\r\ndata: {\"run_id\":\"run-1\"}\r\n\r\n",
    ": keep-alive\r\n\r\nid: 0-1\r\nevent: messages\r\n",
    "data: {\"delta\":\"你好\"}\r\n\r\n",
  ]);
  const frames = [];

  await readSseFrames(response, (frame) => frames.push(frame));

  assert.deepEqual(frames, [
    { id: "0-0", event: "metadata", data: "{\"run_id\":\"run-1\"}" },
    { id: "0-1", event: "messages", data: "{\"delta\":\"你好\"}" },
  ]);
});

test("does not apply an unterminated frame after a severed write", async () => {
  const response = streamResponse([
    "id: 0-2\nevent: messages\ndata: {\"delta\":\"完整\"}\n\n",
    "id: 0-3\nevent: messages\ndata: {\"delta\":\"截断",
  ]);
  const frames = [];

  await readSseFrames(response, (frame) => frames.push(frame));

  assert.deepEqual(frames, [
    { id: "0-2", event: "messages", data: "{\"delta\":\"完整\"}" },
  ]);
});

function streamResponse(chunks) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}
