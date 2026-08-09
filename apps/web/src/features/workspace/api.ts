import { apiClient, apiErrorMessage } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type LegalCase = components["schemas"]["LegalCase"];
type ApiCaseProfile = components["schemas"]["CaseProfile"];
export type CaseProfile = {
  case_type: string | null;
  parties: string[];
  claims: string[];
  key_facts: string[];
  disputed_issues: string[];
  evidence_notes: string[];
  missing_information: string[];
};
export type CaseMaterial = components["schemas"]["CaseMaterial"];
export type StoredCaseMaterial = components["schemas"]["StoredCaseMaterial"];
export type PersistedMessage = components["schemas"]["CaseConversationMessage"];
export type CaseRun = components["schemas"]["CaseRun"];
type CaseConversationTurnResult = components["schemas"]["CaseConversationTurnResult"];

function requireData<T>(data: T | undefined, error: unknown): T {
  if (data === undefined) throw new Error(apiErrorMessage(error));
  return data;
}

export function normalizeCaseProfile(profile: ApiCaseProfile | undefined): CaseProfile {
  return {
    case_type: profile?.case_type ?? null,
    parties: profile?.parties ?? [],
    claims: profile?.claims ?? [],
    key_facts: profile?.key_facts ?? [],
    disputed_issues: profile?.disputed_issues ?? [],
    evidence_notes: profile?.evidence_notes ?? [],
    missing_information: profile?.missing_information ?? [],
  };
}

export async function listCases(): Promise<LegalCase[]> {
  const { data, error } = await apiClient.GET("/api/v1/cases");
  return requireData(data, error);
}

export async function createCase(title: string): Promise<LegalCase> {
  const { data, error } = await apiClient.POST("/api/v1/cases", {
    body: { title, background: null },
  });
  return requireData(data, error);
}

export async function updateCase(caseId: string, title: string): Promise<LegalCase> {
  const response = await fetch(`/api/v1/cases/${caseId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  const payload: unknown = await response.json();
  if (!response.ok) throw new Error(apiErrorMessage(payload));
  return payload as LegalCase;
}

export async function updateCaseProfile(
  caseId: string,
  profile: CaseProfile,
): Promise<LegalCase> {
  const { data, error } = await apiClient.PUT("/api/v1/cases/{case_id}/profile", {
    params: { path: { case_id: caseId } },
    body: profile,
  });
  return requireData(data, error);
}

export async function listMaterials(caseId: string): Promise<StoredCaseMaterial[]> {
  const { data, error } = await apiClient.GET("/api/v1/cases/{case_id}/materials", {
    params: { path: { case_id: caseId } },
  });
  return requireData(data, error);
}

export async function addMaterial(
  caseId: string,
  material: CaseMaterial,
): Promise<StoredCaseMaterial> {
  const { data, error } = await apiClient.POST("/api/v1/cases/{case_id}/materials", {
    params: { path: { case_id: caseId } },
    body: material,
  });
  return requireData(data, error);
}

export async function uploadMaterial(
  caseId: string,
  file: File,
): Promise<StoredCaseMaterial> {
  const form = new FormData();
  form.set("kind", "other");
  form.set("file", file);
  const response = await fetch(`/api/v1/cases/${caseId}/materials/upload`, {
    method: "POST",
    body: form,
  });
  const payload: unknown = await response.json();
  if (!response.ok) throw new Error(apiErrorMessage(payload));
  return payload as StoredCaseMaterial;
}

export async function deleteMaterial(caseId: string, materialId: string): Promise<void> {
  const { error, response } = await apiClient.DELETE(
    "/api/v1/cases/{case_id}/materials/{material_id}",
    { params: { path: { case_id: caseId, material_id: materialId } } },
  );
  if (!response.ok) throw new Error(apiErrorMessage(error));
}

export async function listMessages(caseId: string): Promise<PersistedMessage[]> {
  const { data, error } = await apiClient.GET("/api/v1/cases/{case_id}/messages", {
    params: { path: { case_id: caseId } },
  });
  return requireData(data, error);
}

type ConversationStreamEvent =
  | { type: "delta"; delta: string }
  | { type: "complete"; result: CaseConversationTurnResult }
  | { type: "error"; message: string };

export async function streamCaseMessage(
  caseId: string,
  message: string,
  onDelta: (delta: string) => void,
  signal?: AbortSignal,
): Promise<CaseConversationTurnResult> {
  const response = await fetch(`/api/v1/cases/${caseId}/messages/stream`, {
    method: "POST",
    headers: {
      Accept: "application/x-ndjson",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    throw new Error(apiErrorMessage(payload));
  }
  if (!response.body) throw new Error("浏览器未能建立流式响应。请稍后重试。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: CaseConversationTurnResult | null = null;

  function consumeLine(line: string) {
    if (!line.trim()) return;
    const event = JSON.parse(line) as ConversationStreamEvent;
    if (event.type === "delta") onDelta(event.delta);
    if (event.type === "complete") result = event.result;
    if (event.type === "error") throw new Error(event.message);
  }

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(consumeLine);
    if (done) break;
  }
  consumeLine(buffer);
  if (!result) throw new Error("分析响应提前结束，请重试。");
  return result;
}

export async function cancelCaseRun(caseId: string): Promise<CaseRun> {
  const { data, error } = await apiClient.POST("/api/v1/cases/{case_id}/run/cancel", {
    params: { path: { case_id: caseId } },
  });
  return requireData(data, error);
}
