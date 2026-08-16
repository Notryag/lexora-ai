import type { ConversationStreamActivity } from "./types";

export type ActivityDisplayState = "running" | "completed" | "failed" | "timed_out";

export type ActivityTimelineItem = {
  key: string;
  kind: "model" | "subagent" | "tool";
  title: string;
  technicalName?: string;
  state: ActivityDisplayState;
  level: 0 | 1;
  parentKey?: string;
  callCount: number;
  order: number;
};

type WorkingItem = Omit<ActivityTimelineItem, "state" | "callCount"> & {
  calls: Map<string, ActivityDisplayState>;
};

const SUBAGENT_NAMES: Record<string, string> = {
  case_analyst: "案件分析 Agent",
  legal_researcher: "法律研究 Agent",
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
  const callersWithToolWork = new Set<string>();
  let operationalWorkSeen = false;

  activities.forEach((activity, index) => {
    const eventType = activity.event_type ?? activity.type;
    if (eventType === "subagent.step" || activity.type === "task_running") return;

    const caller = activity.caller ?? "unknown";
    const presentation = activityPresentation(
      activity,
      operationalWorkSeen,
      callersWithToolWork,
    );
    if (!presentation) return;
    if (presentation.kind !== "model") operationalWorkSeen = true;
    if (
      isToolEvent(eventType, activity.type)
      && caller.startsWith("subagent:")
      && !activity.tool_name?.startsWith("delegate_")
    ) {
      callersWithToolWork.add(caller);
    }

    const existing = items.get(presentation.key);
    const item = existing ?? {
      ...presentation,
      order: index,
      calls: new Map<string, ActivityDisplayState>(),
    };
    item.calls.set(activityIdentity(activity, index), activityState(activity));
    items.set(presentation.key, item);
  });

  const timeline = [...items.values()]
    .sort((left, right) => left.order - right.order)
    .map(({ calls, ...item }) => ({
      ...item,
      state: finalState(calls, isRunning, hasError),
      callCount: calls.size,
    }));
  const parentKeys = new Set(timeline.filter((item) => !item.parentKey).map((item) => item.key));
  return [
    ...timeline.flatMap((item) => item.parentKey
      ? []
      : [item, ...timeline.filter((child) => child.parentKey === item.key)]),
    ...timeline.filter((item) => item.parentKey && !parentKeys.has(item.parentKey)),
  ];
}

function activityPresentation(
  activity: ConversationStreamActivity,
  operationalWorkSeen: boolean,
  callersWithToolWork: Set<string>,
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
      title: SUBAGENT_NAMES[subagentName] ?? "专业分析 Agent",
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
      ...(caller.startsWith("subagent:")
        ? { parentKey: `subagent:${caller.slice("subagent:".length)}` }
        : {}),
    };
  }

  if (isModelEvent(eventType, activity.type)) {
    const caller = activity.caller ?? "unknown";
    if (caller.startsWith("subagent:")) {
      const subagentName = caller.slice("subagent:".length);
      const phase = callersWithToolWork.has(caller) ? "synthesis" : "analysis";
      return {
        key: `model:${caller}:${phase}`,
        kind: "model",
        title: subagentModelPhaseTitle(subagentName, phase),
        technicalName: caller,
        level: 1,
        parentKey: `subagent:${subagentName}`,
      };
    }
    const phase = operationalWorkSeen ? "synthesis" : "analysis";
    return {
      key: `model:${phase}`,
      kind: "model",
      title: phase === "synthesis" ? "主 Agent 整理分析结论" : "主 Agent 理解问题",
      level: 0,
    };
  }

  return null;
}

function subagentModelPhaseTitle(
  subagentName: string,
  phase: "analysis" | "synthesis",
): string {
  if (subagentName === "case_analyst") return "提取并核对案件要素";
  if (subagentName === "legal_researcher") {
    return phase === "synthesis" ? "整理检索到的法律依据" : "规划法律检索范围";
  }
  return phase === "synthesis" ? "整理专业分析结果" : "执行专业分析";
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
