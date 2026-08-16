"use client";

import {
  Activity,
  Bot,
  Check,
  ChevronDown,
  CircleAlert,
  LoaderCircle,
  Wrench,
} from "lucide-react";
import { useState } from "react";

import {
  type ActivityDisplayState,
  buildActivityTimeline,
} from "./activityPresentation";
import styles from "./ActivityTimeline.module.css";
import type {
  ConversationActivityState,
  ConversationStreamActivity,
} from "./types";

type ActivityTimelineProps = {
  activities: ConversationStreamActivity[];
  state: ConversationActivityState;
};

type DisclosureOverride = {
  runKey: string;
  state: ConversationActivityState;
  expanded: boolean;
};

export function ActivityTimeline({ activities, state }: ActivityTimelineProps) {
  const [disclosure, setDisclosure] = useState<DisclosureOverride | null>(null);
  const timeline = buildActivityTimeline(
    activities,
    state === "running",
    state === "failed",
  );

  if (!timeline.length) return null;

  const runKey = activityRunKey(activities);
  const expanded = disclosure?.runKey === runKey && disclosure.state === state
    ? disclosure.expanded
    : state !== "completed";

  return (
    <section className={styles.timeline} aria-label="分析过程" aria-live="polite">
      <button
        aria-expanded={expanded}
        className={styles.header}
        onClick={() => setDisclosure({ runKey, state, expanded: !expanded })}
        type="button"
      >
        <Activity aria-hidden="true" size={15} />
        <span>分析过程</span>
        <small>{summaryLabel(state)}</small>
        <ChevronDown
          aria-hidden="true"
          className={`${styles.toggle} ${expanded ? styles.toggleExpanded : ""}`}
          size={15}
        />
      </button>
      {expanded ? (
        <ol className={styles.list}>
          {timeline.map((item) => {
            const terminal = item.state !== "running";
            const failed = item.state === "failed" || item.state === "timed_out";
            const DetailIcon = item.kind === "subagent" ? Bot
              : item.kind === "tool" ? Wrench
                : Activity;

            return (
              <li
                className={`${styles.item} ${terminal ? styles.itemTerminal : ""} ${item.level ? styles.itemNested : ""}`}
                key={item.key}
                title={item.technicalName ? `技术标识：${item.technicalName}` : undefined}
              >
                <span className={`${styles.icon} ${failed ? styles.iconFailed : ""}`}>
                  {failed ? <CircleAlert aria-hidden="true" size={14} />
                    : terminal ? <Check aria-hidden="true" size={14} />
                      : <LoaderCircle aria-hidden="true" className={styles.spinner} size={14} />}
                </span>
                <span className={styles.detail}>
                  <DetailIcon aria-hidden="true" size={12} />
                  <span className={styles.copy}>
                    <span className={styles.text}>
                      {item.title}
                    </span>
                    {item.description
                      ? <small className={styles.description}>{item.description}</small>
                      : null}
                  </span>
                </span>
                <span className={styles.status}>
                  {item.durationMs !== undefined
                    ? <small>{formatDuration(item.durationMs)}</small>
                    : null}
                  {activityStateLabel(item.state)}
                </span>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}

function activityRunKey(activities: ConversationStreamActivity[]): string {
  return activities.find((activity) => activity.call_id)?.call_id
    ?? activities.find((activity) => activity.task_id)?.task_id
    ?? activities[0]?.event_type
    ?? "empty";
}

function summaryLabel(state: ConversationActivityState): string {
  return {
    running: "进行中",
    completed: "已完成",
    failed: "未完成",
  }[state];
}

function activityStateLabel(state: ActivityDisplayState): string {
  return {
    running: "处理中",
    completed: "已完成",
    failed: "失败",
    timed_out: "已超时",
  }[state];
}

function formatDuration(durationMs: number): string {
  if (durationMs < 1_000) return `${durationMs} 毫秒`;
  return `${(durationMs / 1_000).toFixed(durationMs < 10_000 ? 1 : 0)} 秒`;
}
