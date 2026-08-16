import assert from "node:assert/strict";
import test from "node:test";

import { buildActivityTimeline } from "../src/features/conversation/activityPresentation.ts";

test("merges delegation transport and subagent lifecycle into one Chinese row", () => {
  const timeline = buildActivityTimeline([
    activity("tool_started", "tool.started", {
      tool_name: "delegate_legal_researcher",
      call_id: "research-task",
    }),
    activity("task_started", "subagent.start", {
      subagent_type: "legal_researcher",
      task_id: "research-task",
      description: "核验劳动关系的法律依据",
    }),
    activity("task_running", "subagent.step", {
      task_id: "research-task",
      kind: "ai",
    }),
    activity("tool_completed", "tool.completed", {
      tool_name: "delegate_legal_researcher",
      call_id: "research-task",
    }),
    activity("task_completed", "subagent.end", {
      subagent_type: "legal_researcher",
      task_id: "research-task",
      status: "completed",
      latency_ms: 1_234,
    }),
  ], false, false);

  assert.deepEqual(timeline, [{
    key: "subagent:research-task",
    kind: "subagent",
    title: "法律研究 Agent",
    description: "核验劳动关系的法律依据",
    technicalName: "legal_researcher",
    state: "completed",
    level: 0,
    durationMs: 1_234,
    order: 0,
  }]);
});

test("keeps repeated tool calls separate and merges each call with its terminal event", () => {
  const inProgress = [
    activity("tool_started", "tool.started", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
      description: "检索“劳动合同解除条件”相关的法规依据",
    }),
    activity("tool_started", "tool.started", {
      tool_name: "search_legal_authorities",
      call_id: "search-2",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
      description: "检索“违法解除赔偿金”相关的法规依据",
    }),
    activity("tool_completed", "tool.completed", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
    }),
  ];

  const timeline = buildActivityTimeline(inProgress, true, false);
  assert.deepEqual(timeline.map(({ key, state, description }) => ({
    key,
    state,
    description,
  })), [
    {
      key: "tool:search-1",
      state: "completed",
      description: "检索“劳动合同解除条件”相关的法规依据",
    },
    {
      key: "tool:search-2",
      state: "running",
      description: "检索“违法解除赔偿金”相关的法规依据",
    },
  ]);
  assert.equal(timeline[0].parentKey, "subagent:research-task");

  const completed = [
    ...inProgress,
    activity("tool_completed", "tool.completed", {
      tool_name: "search_legal_authorities",
      call_id: "search-2",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
    }),
  ];
  assert.deepEqual(
    buildActivityTimeline(completed, true, false).map((item) => item.state),
    ["completed", "completed"],
  );
});

test("closes an orphan running state when the product run has completed", () => {
  const timeline = buildActivityTimeline([
    activity("tool_started", "tool.started", {
      tool_name: "search_case_materials",
      call_id: "materials-1",
      caller: "subagent:legal_researcher",
    }),
  ], false, false);

  assert.equal(timeline[0].state, "completed");
  assert.equal(timeline[0].title, "检索案件材料");
});

test("does not expose subagent model turns as invented user-facing phases", () => {
  const timeline = buildActivityTimeline([
    activity("model_started", "model.started", {
      call_id: "supervisor-1",
      caller: "unknown",
    }),
    activity("model_completed", "model.completed", {
      call_id: "supervisor-1",
      caller: "unknown",
    }),
    activity("model_started", "model.started", {
      call_id: "case-analysis-model",
      caller: "subagent:case_analyst",
    }),
    activity("model_completed", "model.completed", {
      call_id: "case-analysis-model",
      caller: "subagent:case_analyst",
    }),
  ], false, false);

  assert.deepEqual(timeline.map(({ title, level }) => ({ title, level })), [
    { title: "主 Agent 判断处理路径", level: 0 },
  ]);
});

test("shows real subagent and tool activity without inferred model phases", () => {
  const timeline = buildActivityTimeline([
    activity("task_started", "subagent.start", {
      subagent_type: "legal_researcher",
      task_id: "research-task",
    }),
    activity("model_started", "model.started", {
      call_id: "research-plan",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
    }),
    activity("model_completed", "model.completed", {
      call_id: "research-plan",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
    }),
    activity("tool_started", "tool.started", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
    }),
    activity("tool_completed", "tool.completed", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
    }),
    activity("model_started", "model.started", {
      call_id: "research-synthesis",
      caller: "subagent:legal_researcher",
      task_id: "research-task",
    }),
  ], true, false);

  assert.deepEqual(timeline.map(({ title, state, level }) => ({ title, state, level })), [
    { title: "正在调用法律研究 Agent", state: "running", level: 0 },
    { title: "检索法规依据", state: "completed", level: 1 },
  ]);
});

function activity(type, eventType, fields) {
  return { type, event_type: eventType, ...fields };
}
