import type { ConversationStreamActivity } from "./types";

export type ActivityDisplayState = "running" | "completed" | "failed" | "timed_out";

export type ActivityTimelineItem = {
  key: string;
  kind: "model" | "subagent" | "tool";
  title: string;
  description?: string;
  technicalName?: string;
  state: ActivityDisplayState;
  level: 0 | 1;
  parentKey?: string;
  durationMs?: number;
  order: number;
};

type WorkingItem = Omit<ActivityTimelineItem, "state" | "durationMs"> & {
  runningTitle?: string;
  calls: Map<string, { state: ActivityDisplayState; durationMs?: number }>;
};

const SUBAGENT_NAMES: Record<string, string> = {
  case_analyst: "案件分析 Agent",
  legal_researcher: "法律研究 Agent",
};

const SUBAGENT_DESCRIPTIONS: Record<string, string> = {
  case_analyst: "梳理用户陈述，形成可复用的案件画像",
  legal_researcher: "检索并核验与当前问题直接相关的法规和案例",
};

const TOOL_NAMES: Record<string, string> = {
  calculate_employment_termination_compensation: "计算劳动补偿金额",
  search_case_materials: "检索案件材料",
  search_guiding_cases: "检索相关案例",
  search_legal_authorities: "检索法规依据",
};

const TOOL_DESCRIPTIONS: Record<string, string> = {
  calculate_employment_termination_compensation: "根据已确认的工资和工作年限执行确定性计算",
  search_case_materials: "从当前案件材料中定位与问题相关的内容",
  search_guiding_cases: "查找事实结构相近的已审核官方案例",
  search_legal_authorities: "查找直接支持当前问题的有效法规条文",
};

export function buildActivityTimeline(
  activities: ConversationStreamActivity[],
  isRunning: boolean,
  hasError: boolean,
): ActivityTimelineItem[] {
  const items = new Map<string, WorkingItem>();
  const taskKeysBySubagent = new Map<string, string>();
  let operationalWorkSeen = false;

  activities.forEach((activity, index) => {
    const eventType = activity.event_type ?? activity.type;
    if (eventType === "subagent.step" || activity.type === "task_running") return;

    rememberSubagentTask(activity, taskKeysBySubagent);
    const presentation = activityPresentation(
      activity,
      index,
      operationalWorkSeen,
      taskKeysBySubagent,
    );
    if (!presentation) return;
    if (presentation.kind !== "model") operationalWorkSeen = true;

    const existing = items.get(presentation.key);
    const item = existing ?? { ...presentation, order: index, calls: new Map() };
    if (existing) {
      item.description = activity.description ?? existing.description;
      item.runningTitle = presentation.runningTitle ?? existing.runningTitle;
    }
    item.calls.set(activityIdentity(activity, index), {
      state: activityState(activity),
      ...(typeof activity.latency_ms === "number"
        ? { durationMs: activity.latency_ms }
        : {}),
    });
    items.set(presentation.key, item);
  });

  const timeline = [...items.values()]
    .sort((left, right) => left.order - right.order)
    .map(({ calls, runningTitle, ...item }) => {
      const state = finalState(calls, isRunning, hasError);
      const durations = [...calls.values()]
        .map((call) => call.durationMs)
        .filter((duration): duration is number => typeof duration === "number");
      return {
        ...item,
        title: state === "running" && runningTitle ? runningTitle : item.title,
        state,
        ...(durations.length ? { durationMs: Math.max(...durations) } : {}),
      };
    });
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
  index: number,
  operationalWorkSeen: boolean,
  taskKeysBySubagent: Map<string, string>,
): Omit<WorkingItem, "calls" | "order"> | null {
  const eventType = activity.event_type ?? activity.type;
  const delegatedSubagent = activity.tool_name?.startsWith("delegate_")
    ? activity.tool_name.slice("delegate_".length)
    : null;
  const subagentName = activity.subagent_type ?? delegatedSubagent;

  if (subagentName) {
    const taskKey = subagentTaskKey(activity, subagentName);
    const displayName = activity.display_name ?? SUBAGENT_NAMES[subagentName] ?? "专业分析 Agent";
    return {
      key: taskKey,
      kind: "subagent",
      title: displayName,
      runningTitle: `正在调用${displayName}`,
      description: activity.description
        ?? SUBAGENT_DESCRIPTIONS[subagentName]
        ?? "执行主 Agent 委派的专业分析任务",
      technicalName: subagentName,
      level: 0,
    };
  }

  if (isToolEvent(eventType, activity.type) && activity.tool_name) {
    const caller = activity.caller ?? "unknown";
    const callerSubagent = subagentNameFromCaller(caller);
    const parentKey = callerSubagent
      ? activity.task_id
        ? `subagent:${activity.task_id}`
        : taskKeysBySubagent.get(callerSubagent)
      : undefined;
    return {
      key: `tool:${activity.call_id ?? `${caller}:${activity.tool_name}:${index}`}`,
      kind: "tool",
      title: TOOL_NAMES[activity.tool_name] ?? "执行辅助工具",
      runningTitle: `正在${TOOL_NAMES[activity.tool_name] ?? "执行辅助工具"}`,
      description: activity.description ?? TOOL_DESCRIPTIONS[activity.tool_name],
      technicalName: activity.tool_name,
      level: callerSubagent ? 1 : 0,
      ...(parentKey ? { parentKey } : {}),
    };
  }

  if (isModelEvent(eventType, activity.type)) {
    const caller = activity.caller ?? "unknown";
    if (caller.startsWith("subagent:") || caller.startsWith("middleware:")) return null;
    const phase = activity.call_index === 1 || (!activity.call_index && !operationalWorkSeen)
      ? "analysis"
      : "synthesis";
    return {
      key: `model:${phase}`,
      kind: "model",
      title: phase === "synthesis" ? "主 Agent 核对结果并组织答复" : "主 Agent 判断处理路径",
      runningTitle: phase === "synthesis"
        ? "主 Agent 正在核对结果并组织答复"
        : "主 Agent 正在判断处理路径",
      description: phase === "synthesis"
        ? "检查案件画像和研究依据，决定继续处理或形成最终回答"
        : "识别问题类型，并判断需要调用哪些专业 Agent 或工具",
      level: 0,
    };
  }

  return null;
}

function rememberSubagentTask(
  activity: ConversationStreamActivity,
  taskKeysBySubagent: Map<string, string>,
): void {
  const delegatedSubagent = activity.tool_name?.startsWith("delegate_")
    ? activity.tool_name.slice("delegate_".length)
    : null;
  const subagentName = activity.subagent_type ?? delegatedSubagent;
  if (subagentName) taskKeysBySubagent.set(subagentName, subagentTaskKey(activity, subagentName));
}

function subagentTaskKey(
  activity: ConversationStreamActivity,
  subagentName: string,
): string {
  return `subagent:${activity.task_id ?? activity.call_id ?? `legacy:${subagentName}`}`;
}

function subagentNameFromCaller(caller: string): string | null {
  return caller.startsWith("subagent:") ? caller.slice("subagent:".length) : null;
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
  calls: Map<string, { state: ActivityDisplayState }>,
  isRunning: boolean,
  hasError: boolean,
): ActivityDisplayState {
  const states = [...calls.values()].map((call) => call.state);
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
