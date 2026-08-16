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
    title: "法律资料研究",
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

test("does not duplicate subagent model calls as top-level analysis steps", () => {
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
      call_id: "research-model",
      caller: "subagent:legal_researcher",
    }),
    activity("model_completed", "model.completed", {
      call_id: "research-model",
      caller: "subagent:legal_researcher",
    }),
  ], false, false);

  assert.equal(timeline.length, 1);
  assert.equal(timeline[0].title, "分析问题");
});

function activity(type, eventType, fields) {
  return { type, event_type: eventType, ...fields };
}
