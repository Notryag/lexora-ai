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
  event_type?: string;
  content?: string | null;
  tool_name?: string;
  subagent_type?: string;
  task_id?: string;
  [key: string]: unknown;
};
