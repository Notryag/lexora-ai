import { apiClient, apiErrorMessage } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type ConversationTurnRequest = components["schemas"]["ConversationTurnRequest"];
type ConversationTurnResult = components["schemas"]["ConversationTurnResult"];

export async function sendConversationTurn(
  body: ConversationTurnRequest,
): Promise<ConversationTurnResult> {
  const { data, error } = await apiClient.POST("/api/v1/conversations/messages", { body });
  if (!data) throw new Error(apiErrorMessage(error));
  return data;
}
