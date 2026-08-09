type Citation = { reference: string };

const authorityReferencePattern =
  /\[((?:L[a-zA-Z0-9-]+:C\d+|C[a-zA-Z0-9-]+:S\d+))\]/g;

export function citationMarkers(text: string): Map<string, number> {
  const markers = new Map<string, number>();
  for (const match of text.matchAll(authorityReferencePattern)) {
    const reference = match[1];
    if (!markers.has(reference)) markers.set(reference, markers.size + 1);
  }
  return markers;
}

export function presentAssistantText(text: string): string {
  const markers = citationMarkers(text);
  return text.replace(
    authorityReferencePattern,
    (_match, reference: string) => `[${markers.get(reference)}]`,
  );
}

export function presentAssistantMarkdown(text: string): string {
  return presentAssistantText(text)
    .replace(/\[(\d+)\]/g, "`[$1]`")
    .replace(/\[(M\d+:C\d+)\]/g, "`[$1]`");
}

export function citedSources<T extends Citation>(text: string, citations: T[] = []): T[] {
  const markers = citationMarkers(text);
  return citations.filter((citation) => markers.has(citation.reference));
}
