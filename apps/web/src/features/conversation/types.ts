import type { components } from "@/lib/api/schema";

export type CaseMaterial = components["schemas"]["CaseMaterial"];
export type MaterialKind = components["schemas"]["MaterialKind"];
export type StoredCaseMaterial = components["schemas"]["StoredCaseMaterial"];
export type LegalCitation = components["schemas"]["LegalCitation"];
export type CaseLawCitation = components["schemas"]["CaseLawCitation"];

export type ChatMessage = {
  id: string;
  runId?: string;
  role: "assistant" | "user";
  text: string;
  legalCitations?: LegalCitation[];
  caseLawCitations?: CaseLawCitation[];
};

export type ConversationActivityState = "running" | "completed" | "failed";

export type ConversationStreamActivity = {
  type: string;
  event_type?: string | null;
  call_index?: number | null;
  content?: string | null;
  call_id?: string | null;
  caller?: string | null;
  description?: string | null;
  display_name?: string | null;
  kind?: string | null;
  latency_ms?: number | null;
  parent_call_id?: string | null;
  status?: string | null;
  tool_name?: string | null;
  subagent_type?: string | null;
  task_id?: string | null;
  [key: string]: unknown;
};
