import createClient from "openapi-fetch";

import type { paths } from "./schema";

export const apiClient = createClient<paths>({ baseUrl: "" });

export function apiErrorMessage(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return "请求失败，请稍后重试。";
}
