"use client";

import {
  Activity,
  BookOpenCheck,
  BookOpenText,
  Check,
  ClipboardList,
  CircleCheck,
  CircleAlert,
  ChevronDown,
  Download,
  ExternalLink,
  LoaderCircle,
  Scale,
  SendHorizontal,
  Square,
  Users,
  Wrench,
} from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

import type { ChatMessage, ConversationStreamActivity } from "./types";
import {
  citationMarkers,
  citedSources,
  presentAssistantMarkdown,
} from "./citationPresentation";
import { buildActivityTimeline } from "./activityPresentation";
import styles from "./ConversationPanel.module.css";

type ConversationPanelProps = {
  caseTitle: string;
  error: string | null;
  isSubmitting: boolean;
  isCancelling: boolean;
  materialCount: number;
  profileItemCount: number;
  profileUpdated: boolean;
  messages: ChatMessage[];
  activities: ConversationStreamActivity[];
  onCaseTitleChange: (value: string) => void;
  onCaseTitleCommit: () => void;
  onOpenMaterials: () => void;
  onOpenProfile: () => void;
  onExport: () => void;
  onSend: (message: string) => void;
  onCancel: () => void;
};

export function ConversationPanel({
  caseTitle,
  error,
  isSubmitting,
  isCancelling,
  materialCount,
  profileItemCount,
  profileUpdated,
  messages,
  activities,
  onCaseTitleChange,
  onCaseTitleCommit,
  onOpenMaterials,
  onOpenProfile,
  onExport,
  onSend,
  onCancel,
}: ConversationPanelProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const activityTimeline = buildActivityTimeline(activities, isSubmitting, Boolean(error));

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (container) container.scrollTop = container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activities, isSubmitting, messages]);

  function submit() {
    const message = draft.trim();
    if (!message || isSubmitting) return;
    setDraft("");
    onSend(message);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <section className={styles.panel} aria-label="法律分析对话">
      <header className={styles.header}>
        <div className={styles.titleGroup}>
          <span className={styles.mobileBrand}>法析 Lexora</span>
          <input
            aria-label="案件标题"
            maxLength={240}
            onBlur={onCaseTitleCommit}
            onChange={(event) => onCaseTitleChange(event.target.value)}
            placeholder="未命名案件"
            value={caseTitle}
          />
        </div>
        <div className={styles.headerActions}>
          <button
            aria-label="导出案件记录"
            className={styles.exportButton}
            onClick={onExport}
            title="导出案件记录"
            type="button"
          >
            <Download aria-hidden="true" size={18} />
            <span>导出</span>
          </button>
          <button
            aria-label={profileUpdated ? `档案 ${profileItemCount}，已更新` : undefined}
            className={`${styles.profileButton} ${profileUpdated ? styles.profileButtonUpdated : ""}`}
            onClick={onOpenProfile}
            title={profileUpdated ? "案件档案已更新" : "案件档案"}
            type="button"
          >
            {profileUpdated
              ? <CircleCheck aria-hidden="true" size={18} />
              : <ClipboardList aria-hidden="true" size={18} />}
            <span>档案 {profileItemCount}{profileUpdated ? " · 已更新" : ""}</span>
          </button>
          <button className={styles.materialButton} onClick={onOpenMaterials} type="button">
            <BookOpenText aria-hidden="true" size={18} />
            <span>材料 {materialCount}</span>
          </button>
        </div>
      </header>

      <div className={styles.messages} ref={scrollRef}>
        <div className={styles.messageColumn}>
          {messages.map((message) => {
            const markers = citationMarkers(message.text);
            const legalCitations = citedSources(message.text, message.legalCitations);
            const caseLawCitations = citedSources(message.text, message.caseLawCitations);
            return (
              <article
              className={`${styles.message} ${message.role === "user" ? styles.user : styles.assistant}`}
              key={message.id}
            >
              {message.role === "assistant" ? (
                <div className={styles.assistantMark} aria-hidden="true">析</div>
              ) : null}
              <div className={styles.messageBody}>
                {message.role === "assistant" ? (
                  <Markdown>{presentAssistantMarkdown(message.text)}</Markdown>
                ) : (
                  <p>{message.text}</p>
                )}
                {message.role === "assistant" && legalCitations.length ? (
                  <section className={styles.legalSources} aria-label="法规依据">
                    <div className={styles.legalSourcesTitle}>
                      <BookOpenCheck aria-hidden="true" size={16} />
                      法规依据
                    </div>
                    {legalCitations.map((citation) => (
                      <details
                        className={styles.legalSource}
                        key={citation.reference}
                      >
                        <summary>
                          <span>
                            <strong>{citation.title}</strong>
                            <small>
                              {citation.article_label ?? "相关条文"} · {citation.issuing_authority}
                            </small>
                          </span>
                          <code>[{markers.get(citation.reference)}]</code>
                          <ChevronDown
                            aria-hidden="true"
                            className={styles.sourceChevron}
                            size={16}
                          />
                        </summary>
                        <div className={styles.sourceDetails}>
                          {citation.content ? (
                            <p className={styles.sourceContent}>{citation.content}</p>
                          ) : (
                            <p className={styles.sourceUnavailable}>该历史引用未保存正文。</p>
                          )}
                          <a href={citation.source_url} rel="noreferrer" target="_blank">
                            <ExternalLink aria-hidden="true" size={14} />
                            查看官方原文
                          </a>
                        </div>
                      </details>
                    ))}
                  </section>
                ) : null}
                {message.role === "assistant" && caseLawCitations.length ? (
                  <section className={styles.legalSources} aria-label="类案参考">
                    <div className={styles.legalSourcesTitle}>
                      <Scale aria-hidden="true" size={16} />
                      类案参考
                    </div>
                    {caseLawCitations.map((citation) => (
                      <details
                        className={styles.legalSource}
                        key={citation.reference}
                      >
                        <summary>
                          <span>
                            <strong>{citation.case_number} · {citation.title}</strong>
                            <small>
                              {citation.section_label} · {citation.issuing_authority}
                            </small>
                          </span>
                          <code>[{markers.get(citation.reference)}]</code>
                          <ChevronDown
                            aria-hidden="true"
                            className={styles.sourceChevron}
                            size={16}
                          />
                        </summary>
                        <div className={styles.sourceDetails}>
                          {citation.content ? (
                            <p className={styles.sourceContent}>{citation.content}</p>
                          ) : (
                            <p className={styles.sourceUnavailable}>该历史引用未保存正文。</p>
                          )}
                          <a href={citation.source_url} rel="noreferrer" target="_blank">
                            <ExternalLink aria-hidden="true" size={14} />
                            查看最高法原文
                          </a>
                        </div>
                      </details>
                    ))}
                  </section>
                ) : null}
              </div>
              </article>
            );
          })}

          {activityTimeline.length ? (
            <section className={styles.activityTimeline} aria-label="分析过程" aria-live="polite">
              <div className={styles.activityHeader}>
                <Activity aria-hidden="true" size={15} />
                <span>分析过程</span>
                <small>{isSubmitting ? "进行中" : error ? "未完成" : "已完成"}</small>
              </div>
              <ol className={styles.activityList}>
                {activityTimeline.map((activity) => {
                  const terminal = activity.state !== "running";
                  const failed = activity.state === "failed" || activity.state === "timed_out";
                  const DetailIcon = activity.kind === "subagent" ? Users
                    : activity.kind === "tool" ? Wrench
                      : Activity;
                  return (
                    <li
                      className={`${styles.activityItem} ${terminal ? styles.activityItemTerminal : ""} ${activity.level ? styles.activityItemNested : ""}`}
                      key={activity.key}
                      title={activity.technicalName ? `技术标识：${activity.technicalName}` : undefined}
                    >
                      <span className={`${styles.activityIcon} ${failed ? styles.activityIconFailed : ""}`}>
                        {failed ? <CircleAlert aria-hidden="true" size={14} />
                          : terminal ? <Check aria-hidden="true" size={14} />
                            : <LoaderCircle aria-hidden="true" className={styles.activitySpinner} size={14} />}
                      </span>
                      <span className={styles.activityDetail}>
                        <DetailIcon aria-hidden="true" size={12} />
                        <span className={styles.activityText}>{activity.title}</span>
                        {activity.kind === "tool" && activity.callCount > 1
                          ? <small>{activity.callCount} 次</small>
                          : null}
                      </span>
                      <span className={styles.activityStatus}>{activityStateLabel(activity.state)}</span>
                    </li>
                  );
                })}
              </ol>
            </section>
          ) : null}

          {isSubmitting && messages.at(-1)?.role !== "assistant" ? (
            <article className={`${styles.message} ${styles.assistant}`} aria-label="正在分析">
              <div className={styles.assistantMark} aria-hidden="true">析</div>
              <div className={styles.thinking}>
                <span />
                <span />
                <span />
              </div>
            </article>
          ) : null}
        </div>
      </div>

      <div className={styles.composerDock}>
        {error ? <div className={styles.error} role="alert">{error}</div> : null}
        <div className={styles.composer}>
          <textarea
            aria-label="描述案件情况"
            disabled={isSubmitting}
            maxLength={4_000}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="描述案件情况或继续补充事实"
            rows={2}
            value={draft}
          />
          {isSubmitting ? (
            <button
              aria-label="取消分析"
              className={styles.cancelButton}
              disabled={isCancelling}
              onClick={onCancel}
              title="取消分析"
              type="button"
            >
              <Square aria-hidden="true" fill="currentColor" size={17} />
            </button>
          ) : (
            <button
              aria-label="发送"
              className={styles.sendButton}
              disabled={!draft.trim()}
              onClick={submit}
              title="发送"
              type="button"
            >
              <SendHorizontal aria-hidden="true" size={20} />
            </button>
          )}
        </div>
        <p className={styles.disclaimer}>AI 分析仅用于案件研究和材料整理，不构成法律意见。</p>
      </div>
    </section>
  );
}

function activityStateLabel(state: "running" | "completed" | "failed" | "timed_out"): string {
  return {
    running: "处理中",
    completed: "已完成",
    failed: "失败",
    timed_out: "已超时",
  }[state];
}
