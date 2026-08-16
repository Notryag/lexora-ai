export type SseFrame = {
  id: string | null;
  event: string;
  data: string;
};

export async function readSseFrames(
  response: Response,
  onFrame: (frame: SseFrame) => void,
): Promise<void> {
  if (!response.body) throw new Error("浏览器未能建立流式响应。请稍后重试。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let id: string | null = null;
  let data: string[] = [];

  function resetFrame() {
    event = "message";
    id = null;
    data = [];
  }

  function dispatchFrame() {
    if (data.length) onFrame({ id, event, data: data.join("\n") });
    resetFrame();
  }

  function consumeLine(rawLine: string) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!line) {
      dispatchFrame();
      return;
    }
    if (line.startsWith(":")) return;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value || "message";
    else if (field === "id" && !value.includes("\0")) id = value;
    else if (field === "data") data.push(value);
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(consumeLine);
  }
  buffer += decoder.decode();
  const lines = buffer.split("\n");
  // An unterminated final frame may be a severed network write. It is replayed
  // from the last committed event ID instead of being applied partially.
  if (lines.at(-1) === "") lines.slice(0, -1).forEach(consumeLine);
}

export function waitForRetry(delayMs: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = globalThis.setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, delayMs);
    function abort() {
      globalThis.clearTimeout(timer);
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
    }
    signal?.addEventListener("abort", abort, { once: true });
  });
}
