import type { ConversationStreamActivity } from "./types";

export type ActivityDisplayState = "running" | "completed" | "failed" | "timed_out";

export type ActivityTimelineItem = {
  key: string;
  kind: "model" | "subagent" | "tool";
  title: string;
  technicalName?: string;
  state: ActivityDisplayState;
  level: 0 | 1;
  callCount: number;
  order: number;
};

type WorkingItem = Omit<ActivityTimelineItem, "state" | "callCount"> & {
  calls: Map<string, ActivityDisplayState>;
};

const SUBAGENT_NAMES: Record<string, string> = {
  case_analyst: "案件要素分析",
  legal_researcher: "法律资料研究",
};

const TOOL_NAMES: Record<string, string> = {
  calculate_employment_termination_compensation: "计算劳动补偿金额",
  search_case_materials: "检索案件材料",
  search_guiding_cases: "检索指导性案例",
  search_legal_authorities: "检索法规依据",
};

export function buildActivityTimeline(
  activities: ConversationStreamActivity[],
  isRunning: boolean,
  hasError: boolean,
): ActivityTimelineItem[] {
  const items = new Map<string, WorkingItem>();
  let operationalWorkSeen = false;

  activities.forEach((activity, index) => {
    const eventType = activity.event_type ?? activity.type;
    if (eventType === "subagent.step" || activity.type === "task_running") return;

    const caller = activity.caller ?? "unknown";
    if (isModelEvent(eventType, activity.type) && caller.startsWith("subagent:")) return;

    const presentation = activityPresentation(activity, operationalWorkSeen);
    if (!presentation) return;
    if (presentation.kind !== "model") operationalWorkSeen = true;

    const existing = items.get(presentation.key);
    const item = existing ?? {
      ...presentation,
      order: index,
      calls: new Map<string, ActivityDisplayState>(),
    };
    item.calls.set(activityIdentity(activity, index), activityState(activity));
    items.set(presentation.key, item);
  });

  return [...items.values()]
    .sort((left, right) => left.order - right.order)
    .map(({ calls, ...item }) => ({
      ...item,
      state: finalState(calls, isRunning, hasError),
      callCount: calls.size,
    }));
}

function activityPresentation(
  activity: ConversationStreamActivity,
  operationalWorkSeen: boolean,
): Omit<WorkingItem, "calls" | "order"> | null {
  const eventType = activity.event_type ?? activity.type;
  const delegatedSubagent = activity.tool_name?.startsWith("delegate_")
    ? activity.tool_name.slice("delegate_".length)
    : null;
  const subagentName = activity.subagent_type ?? delegatedSubagent;

  if (subagentName) {
    return {
      key: `subagent:${subagentName}`,
      kind: "subagent",
      title: SUBAGENT_NAMES[subagentName] ?? "专业法律分析",
      technicalName: subagentName,
      level: 0,
    };
  }

  if (isToolEvent(eventType, activity.type) && activity.tool_name) {
    const caller = activity.caller ?? "unknown";
    return {
      key: `tool:${caller}:${activity.tool_name}`,
      kind: "tool",
      title: TOOL_NAMES[activity.tool_name] ?? "执行辅助工具",
      technicalName: activity.tool_name,
      level: caller.startsWith("subagent:") ? 1 : 0,
    };
  }

  if (isModelEvent(eventType, activity.type)) {
    const phase = operationalWorkSeen ? "synthesis" : "analysis";
    return {
      key: `model:${phase}`,
      kind: "model",
      title: phase === "synthesis" ? "整理分析结论" : "分析问题",
      level: 0,
    };
  }

  return null;
}

function activityIdentity(activity: ConversationStreamActivity, index: number): string {
  return activity.call_id ?? activity.task_id ?? `${activity.event_type ?? activity.type}:${index}`;
}

function activityState(activity: ConversationStreamActivity): ActivityDisplayState {
  if (activity.type.endsWith("failed") || activity.event_type?.endsWith(".error")) {
    return "failed";
  }
  if (activity.type === "task_timed_out" || activity.status === "timed_out") {
    return "timed_out";
  }
  if (
    activity.type.endsWith("completed")
    || activity.event_type?.endsWith(".completed")
    || activity.event_type === "subagent.end"
  ) {
    return "completed";
  }
  return "running";
}

function finalState(
  calls: Map<string, ActivityDisplayState>,
  isRunning: boolean,
  hasError: boolean,
): ActivityDisplayState {
  const states = [...calls.values()];
  if (states.includes("running")) {
    if (isRunning) return "running";
    return hasError ? "failed" : "completed";
  }
  if (states.includes("failed")) return "failed";
  if (states.includes("timed_out")) return "timed_out";
  return "completed";
}

function isModelEvent(eventType: string, liveType: string): boolean {
  return eventType.startsWith("model.") || liveType.startsWith("model_");
}

function isToolEvent(eventType: string, liveType: string): boolean {
  return eventType.startsWith("tool.") || liveType.startsWith("tool_");
}
