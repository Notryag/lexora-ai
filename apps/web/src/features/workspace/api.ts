import { apiClient, apiErrorMessage } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { ConversationStreamActivity } from "@/features/conversation/types";

import { readSseFrames, waitForRetry } from "./sse";

export type { ConversationStreamActivity } from "@/features/conversation/types";

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
export type CaseRunActivityHistory = components["schemas"]["CaseRunActivityHistory"];
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

export async function getLatestRunActivities(
  caseId: string,
): Promise<CaseRunActivityHistory | null> {
  const { data, error } = await apiClient.GET(
    "/api/v1/cases/{case_id}/run/activities",
    { params: { path: { case_id: caseId } } },
  );
  return requireData(data, error);
}

export async function streamCaseMessage(
  caseId: string,
  message: string,
  onDelta: (delta: string) => void,
  onActivity?: (activity: ConversationStreamActivity) => void,
  signal?: AbortSignal,
): Promise<CaseConversationTurnResult> {
  const response = await fetch(`/api/v1/cases/${caseId}/messages/stream`, {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!response.ok) {
    const payload: unknown = await response.json();
    throw new Error(apiErrorMessage(payload));
  }

  const retryDelays = [300, 600, 1_200];
  let currentResponse: Response | null = response;
  let runId: string | null = null;
  let lastEventId: string | null = null;
  let result: CaseConversationTurnResult | null = null;
  let ended = false;
  let resumeAttempt = 0;

  function consumeFrame(eventName: string, eventId: string | null, payload: string) {
    let data: Record<string, unknown>;
    try {
      data = JSON.parse(payload) as Record<string, unknown>;
    } catch {
      throw new TerminalStreamError("分析服务返回了无法识别的流事件，请刷新后查看结果。");
    }

    if (eventName === "metadata") {
      if (typeof data.run_id !== "string" || !data.run_id) {
        throw new TerminalStreamError("分析服务未返回有效的运行标识，请刷新后重试。");
      }
      if (runId && runId !== data.run_id) {
        throw new TerminalStreamError("分析流的运行标识发生变化，请刷新后查看结果。");
      }
      runId = data.run_id;
    } else if (eventName === "messages" && typeof data.delta === "string") {
      onDelta(data.delta);
    } else if (eventName === "custom" && onActivity) {
      onActivity(data as ConversationStreamActivity);
    } else if (eventName === "complete") {
      result = data.result as CaseConversationTurnResult;
    } else if (eventName === "error") {
      throw new TerminalStreamError(
        typeof data.message === "string" ? data.message : "分析失败，请稍后重试。",
      );
    } else if (eventName === "gap") {
      throw new TerminalStreamError(
        "实时事件已过期，案件记录仍已保存。请刷新页面查看最新结果。",
      );
    } else if (eventName === "end") {
      ended = true;
    }
    if (eventId) lastEventId = eventId;
  }

  while (true) {
    try {
      if (currentResponse === null) {
        const headers = new Headers({ Accept: "text/event-stream" });
        if (lastEventId) headers.set("Last-Event-ID", lastEventId);
        currentResponse = await fetch(
          `/api/v1/cases/${caseId}/runs/${runId}/events/stream`,
          {
            method: "GET",
            headers,
            signal,
          },
        );
        if (!currentResponse.ok) {
          if (currentResponse.status >= 500) throw new Error("resume unavailable");
          throw new TerminalStreamError(
            "无法恢复本次实时连接，案件记录仍已保存。请刷新页面查看最新结果。",
          );
        }
      }
      await readSseFrames(currentResponse, ({ event, id, data }) => {
        consumeFrame(event, id, data);
      });
    } catch (error) {
      if (result) return result;
      if (error instanceof TerminalStreamError || signal?.aborted) throw error;
    }

    if (result) return result;
    if (ended) {
      throw new TerminalStreamError(
        "分析已经结束，但实时结果不完整。案件记录仍已保存，请刷新页面查看。",
      );
    }
    if (!runId) {
      throw new TerminalStreamError(
        "连接在分析启动前中断。为避免重复提交，请刷新页面确认后再试。",
      );
    }
    if (resumeAttempt >= retryDelays.length) {
      throw new TerminalStreamError(
        "实时连接暂时无法恢复，案件记录仍已保存。请刷新页面查看最新结果。",
      );
    }
    await waitForRetry(retryDelays[resumeAttempt], signal);
    resumeAttempt += 1;
    currentResponse = null;
  }
}

class TerminalStreamError extends Error {}

export async function cancelCaseRun(caseId: string): Promise<CaseRun> {
  const { data, error } = await apiClient.POST("/api/v1/cases/{case_id}/run/cancel", {
    params: { path: { case_id: caseId } },
  });
  return requireData(data, error);
}
