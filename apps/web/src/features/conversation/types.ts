import type { components } from "@/lib/api/schema";

export type CaseMaterial = components["schemas"]["CaseMaterial"];
export type MaterialKind = components["schemas"]["MaterialKind"];
export type StoredCaseMaterial = components["schemas"]["StoredCaseMaterial"];
export type LegalCitation = components["schemas"]["LegalCitation"];
export type CaseLawCitation = components["schemas"]["CaseLawCitation"];

export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  text: string;
  legalCitations?: LegalCitation[];
  caseLawCitations?: CaseLawCitation[];
};

export type ConversationStreamActivity = {
  type: string;
  event_type?: string | null;
  content?: string | null;
  call_id?: string | null;
  caller?: string | null;
  kind?: string | null;
  parent_call_id?: string | null;
  status?: string | null;
  tool_name?: string | null;
  subagent_type?: string | null;
  task_id?: string | null;
  [key: string]: unknown;
};
