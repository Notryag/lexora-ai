"use client";

import {
  BookOpenCheck,
  BookOpenText,
  ClipboardList,
  ExternalLink,
  Scale,
  SendHorizontal,
  Square,
} from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

import type { ChatMessage } from "./types";
import styles from "./ConversationPanel.module.css";

type ConversationPanelProps = {
  caseTitle: string;
  error: string | null;
  isSubmitting: boolean;
  isCancelling: boolean;
  materialCount: number;
  profileItemCount: number;
  messages: ChatMessage[];
  onCaseTitleChange: (value: string) => void;
  onCaseTitleCommit: () => void;
  onOpenMaterials: () => void;
  onOpenProfile: () => void;
  onSend: (message: string) => void;
  onCancel: () => void;
};

function assistantMarkdown(text: string) {
  return text.replace(/\[((?:M\d+:C\d+|L[a-f0-9]+:C\d+|C[a-f0-9]+:S\d+))\]/g, "`[$1]`");
}

export function ConversationPanel({
  caseTitle,
  error,
  isSubmitting,
  isCancelling,
  materialCount,
  profileItemCount,
  messages,
  onCaseTitleChange,
  onCaseTitleCommit,
  onOpenMaterials,
  onOpenProfile,
  onSend,
  onCancel,
}: ConversationPanelProps) {
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const container = scrollRef.current;
      if (container) container.scrollTop = container.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isSubmitting, messages]);

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
          <button className={styles.profileButton} onClick={onOpenProfile} type="button">
            <ClipboardList aria-hidden="true" size={18} />
            <span>档案 {profileItemCount}</span>
          </button>
          <button className={styles.materialButton} onClick={onOpenMaterials} type="button">
            <BookOpenText aria-hidden="true" size={18} />
            <span>材料 {materialCount}</span>
          </button>
        </div>
      </header>

      <div className={styles.messages} ref={scrollRef}>
        <div className={styles.messageColumn}>
          {messages.map((message) => (
            <article
              className={`${styles.message} ${message.role === "user" ? styles.user : styles.assistant}`}
              key={message.id}
            >
              {message.role === "assistant" ? (
                <div className={styles.assistantMark} aria-hidden="true">析</div>
              ) : null}
              <div className={styles.messageBody}>
                {message.role === "assistant" ? (
                  <Markdown>{assistantMarkdown(message.text)}</Markdown>
                ) : (
                  <p>{message.text}</p>
                )}
                {message.role === "assistant" && message.legalCitations?.length ? (
                  <section className={styles.legalSources} aria-label="法规依据">
                    <div className={styles.legalSourcesTitle}>
                      <BookOpenCheck aria-hidden="true" size={16} />
                      法规依据
                    </div>
                    {message.legalCitations.map((citation) => (
                      <a
                        className={styles.legalSource}
                        href={citation.source_url}
                        key={citation.reference}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <span>
                          <strong>{citation.title}</strong>
                          <small>
                            {citation.article_label ?? "相关条文"} · {citation.issuing_authority}
                          </small>
                        </span>
                        <code>{citation.reference}</code>
                        <ExternalLink aria-hidden="true" size={14} />
                      </a>
                    ))}
                  </section>
                ) : null}
                {message.role === "assistant" && message.caseLawCitations?.length ? (
                  <section className={styles.legalSources} aria-label="类案参考">
                    <div className={styles.legalSourcesTitle}>
                      <Scale aria-hidden="true" size={16} />
                      类案参考
                    </div>
                    {message.caseLawCitations.map((citation) => (
                      <a
                        className={styles.legalSource}
                        href={citation.source_url}
                        key={citation.reference}
                        rel="noreferrer"
                        target="_blank"
                      >
                        <span>
                          <strong>{citation.case_number} · {citation.title}</strong>
                          <small>
                            {citation.section_label} · {citation.issuing_authority}
                          </small>
                        </span>
                        <code>{citation.reference}</code>
                        <ExternalLink aria-hidden="true" size={14} />
                      </a>
                    ))}
                  </section>
                ) : null}
              </div>
            </article>
          ))}

          {isSubmitting ? (
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
