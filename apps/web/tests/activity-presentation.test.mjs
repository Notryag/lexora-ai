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
    }),
  ], false, false);

  assert.deepEqual(timeline, [{
    key: "subagent:legal_researcher",
    kind: "subagent",
    title: "法律研究 Agent",
    technicalName: "legal_researcher",
    state: "completed",
    level: 0,
    callCount: 1,
    order: 0,
  }]);
});

test("groups concurrent calls to the same subagent tool until every call completes", () => {
  const inProgress = [
    activity("tool_started", "tool.started", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
    }),
    activity("tool_started", "tool.started", {
      tool_name: "search_legal_authorities",
      call_id: "search-2",
      caller: "subagent:legal_researcher",
    }),
    activity("tool_completed", "tool.completed", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
    }),
  ];

  assert.deepEqual(buildActivityTimeline(inProgress, true, false)[0], {
    key: "tool:subagent:legal_researcher:search_legal_authorities",
    kind: "tool",
    title: "检索法规依据",
    technicalName: "search_legal_authorities",
    state: "running",
    level: 1,
    parentKey: "subagent:legal_researcher",
    callCount: 2,
    order: 0,
  });

  const completed = [
    ...inProgress,
    activity("tool_completed", "tool.completed", {
      tool_name: "search_legal_authorities",
      call_id: "search-2",
      caller: "subagent:legal_researcher",
    }),
  ];
  assert.equal(buildActivityTimeline(completed, true, false)[0].state, "completed");
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

test("shows subagent model work as a controlled nested stage", () => {
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
    { title: "主 Agent 理解问题", level: 0 },
    { title: "提取并核对案件要素", level: 1 },
  ]);
});

test("separates legal research planning, tool use, and synthesis", () => {
  const timeline = buildActivityTimeline([
    activity("task_started", "subagent.start", {
      subagent_type: "legal_researcher",
      task_id: "research-task",
    }),
    activity("model_started", "model.started", {
      call_id: "research-plan",
      caller: "subagent:legal_researcher",
    }),
    activity("model_completed", "model.completed", {
      call_id: "research-plan",
      caller: "subagent:legal_researcher",
    }),
    activity("tool_started", "tool.started", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
    }),
    activity("tool_completed", "tool.completed", {
      tool_name: "search_legal_authorities",
      call_id: "search-1",
      caller: "subagent:legal_researcher",
    }),
    activity("model_started", "model.started", {
      call_id: "research-synthesis",
      caller: "subagent:legal_researcher",
    }),
  ], true, false);

  assert.deepEqual(timeline.map(({ title, state, level }) => ({ title, state, level })), [
    { title: "法律研究 Agent", state: "running", level: 0 },
    { title: "规划法律检索范围", state: "completed", level: 1 },
    { title: "检索法规依据", state: "completed", level: 1 },
    { title: "整理检索到的法律依据", state: "running", level: 1 },
  ]);
});

function activity(type, eventType, fields) {
  return { type, event_type: eventType, ...fields };
}
