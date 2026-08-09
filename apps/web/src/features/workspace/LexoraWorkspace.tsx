"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CirclePlus, MessageSquareText, Scale } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { ConversationPanel } from "@/features/conversation/ConversationPanel";
import type { CaseMaterial, ChatMessage } from "@/features/conversation/types";
import { MaterialPanel } from "@/features/materials/MaterialPanel";

import {
  addMaterial,
  type CaseProfile,
  createCase,
  deleteMaterial,
  cancelCaseRun,
  listCases,
  listMaterials,
  listMessages,
  normalizeCaseProfile,
  streamCaseMessage,
  updateCase,
  updateCaseProfile,
  uploadMaterial,
} from "./api";
import { CaseProfilePanel, emptyCaseProfile } from "./CaseProfilePanel";
import styles from "./LexoraWorkspace.module.css";

const welcomeMessage: ChatMessage = {
  id: "welcome",
  role: "assistant",
  text: "请描述案件经过。若有合同、聊天记录或其他证据，可以同时加入案件材料。",
};

export function LexoraWorkspace() {
  const queryClient = useQueryClient();
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [draftMode, setDraftMode] = useState(false);
  const [caseTitle, setCaseTitle] = useState("");
  const [pendingUserMessage, setPendingUserMessage] = useState<ChatMessage | null>(null);
  const [pendingAssistantMessage, setPendingAssistantMessage] = useState<ChatMessage | null>(null);
  const [materialPanelOpen, setMaterialPanelOpen] = useState(false);
  const [profilePanelOpen, setProfilePanelOpen] = useState(false);
  const conversationCaseIdRef = useRef<string | null>(null);
  const conversationAbortRef = useRef<AbortController | null>(null);

  const casesQuery = useQuery({ queryKey: ["cases"], queryFn: listCases });
  const activeCaseId = draftMode
    ? null
    : (selectedCaseId ?? casesQuery.data?.[0]?.id ?? null);
  const selectedCase = casesQuery.data?.find((item) => item.id === activeCaseId) ?? null;
  const displayedCaseTitle = caseTitle || selectedCase?.title || "";
  const materialsQuery = useQuery({
    queryKey: ["case-materials", activeCaseId],
    queryFn: () => listMaterials(activeCaseId as string),
    enabled: activeCaseId !== null,
  });
  const messagesQuery = useQuery({
    queryKey: ["case-messages", activeCaseId],
    queryFn: () => listMessages(activeCaseId as string),
    enabled: activeCaseId !== null,
  });

  async function ensureCase(): Promise<string> {
    if (activeCaseId) return activeCaseId;
    const created = await createCase(displayedCaseTitle.trim() || "未命名案件");
    queryClient.setQueryData(["cases"], (current: typeof casesQuery.data) => [
      created,
      ...(current ?? []),
    ]);
    setSelectedCaseId(created.id);
    setDraftMode(false);
    setCaseTitle(created.title);
    return created.id;
  }

  const conversation = useMutation({
    mutationFn: async ({ message }: { message: string }) => {
      const caseId = await ensureCase();
      conversationCaseIdRef.current = caseId;
      const controller = new AbortController();
      conversationAbortRef.current = controller;
      return streamCaseMessage(
        caseId,
        message,
        (delta) => {
          setPendingAssistantMessage((current) => ({
            id: current?.id ?? crypto.randomUUID(),
            role: "assistant",
            text: `${current?.text ?? ""}${delta}`,
          }));
        },
        controller.signal,
      );
    },
    onSuccess: (result) => {
      setPendingAssistantMessage((current) => ({
        id: current?.id ?? crypto.randomUUID(),
        role: "assistant",
        text: result.assistant_message,
        legalCitations: result.legal_citations,
        caseLawCitations: result.case_law_citations,
      }));
    },
    onSettled: async (result) => {
      const caseId = result?.case_id ?? conversationCaseIdRef.current;
      try {
        if (caseId) {
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ["case-messages", caseId] }),
            queryClient.invalidateQueries({ queryKey: ["cases"] }),
          ]);
        }
      } finally {
        conversationCaseIdRef.current = null;
        conversationAbortRef.current = null;
        setPendingUserMessage(null);
        setPendingAssistantMessage(null);
      }
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelCaseRun(activeCaseId as string),
  });

  const titleMutation = useMutation({
    mutationFn: async () => {
      if (!activeCaseId || !displayedCaseTitle.trim()) return null;
      return updateCase(activeCaseId, displayedCaseTitle.trim());
    },
    onSuccess: (updated) => {
      if (updated) void queryClient.invalidateQueries({ queryKey: ["cases"] });
    },
  });

  const profileMutation = useMutation({
    mutationFn: async (profile: CaseProfile) => {
      const caseId = await ensureCase();
      return updateCaseProfile(caseId, profile);
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData(["cases"], (current: typeof casesQuery.data) =>
        (current ?? []).map((item) => item.id === updated.id ? updated : item),
      );
      setProfilePanelOpen(false);
    },
  });

  const messages = useMemo<ChatMessage[]>(() => {
    const persistedMessages = messagesQuery.data ?? [];
    const mapped = persistedMessages.map((message) => ({
      id: message.id,
      role: message.role === "user" ? ("user" as const) : ("assistant" as const),
      text: message.content,
      legalCitations: message.legal_citations,
      caseLawCitations: message.case_law_citations,
    }));
    const pendingUserPersisted = pendingUserMessage
      && mapped.some((message) => message.role === "user" && message.text === pendingUserMessage.text);
    const withUser = pendingUserMessage && !pendingUserPersisted
      ? [...mapped, pendingUserMessage]
      : mapped;
    const withPending = pendingAssistantMessage
      ? [...withUser, pendingAssistantMessage]
      : withUser;
    return withPending.length ? withPending : [welcomeMessage];
  }, [messagesQuery.data, pendingAssistantMessage, pendingUserMessage]);

  async function persistMaterial(material: CaseMaterial) {
    const caseId = await ensureCase();
    await addMaterial(caseId, material);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["case-materials", caseId] }),
      queryClient.invalidateQueries({ queryKey: ["cases"] }),
    ]);
  }

  async function persistUpload(file: File) {
    const caseId = await ensureCase();
    await uploadMaterial(caseId, file);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["case-materials", caseId] }),
      queryClient.invalidateQueries({ queryKey: ["cases"] }),
    ]);
  }

  async function removeMaterial(materialId: string) {
    if (!activeCaseId) return;
    await deleteMaterial(activeCaseId, materialId);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["case-materials", activeCaseId] }),
      queryClient.invalidateQueries({ queryKey: ["cases"] }),
    ]);
  }

  function sendMessage(message: string) {
    if (conversation.isPending) return;
    setPendingUserMessage({ id: crypto.randomUUID(), role: "user", text: message });
    setPendingAssistantMessage(null);
    conversation.mutate({ message });
  }

  function exportCaseRecord() {
    const title = displayedCaseTitle.trim() || "未命名案件";
    const sections = messages.map((message) => {
      const heading = message.role === "assistant" ? "法析 Lexora" : "用户";
      const citations = message.legalCitations?.length
        ? `\n\n法规依据：\n${message.legalCitations.map((citation) =>
          `- [${citation.title} - ${citation.article_label ?? "相关条文"}](${citation.source_url}) ${citation.reference}`
        ).join("\n")}`
        : "";
      const caseLaw = message.caseLawCitations?.length
        ? `\n\n类案参考：\n${message.caseLawCitations.map((citation) =>
          `- [${citation.case_number} ${citation.title}](${citation.source_url}) ${citation.reference}`
        ).join("\n")}`
        : "";
      return `### ${heading}\n\n${message.text}${citations}${caseLaw}`;
    });
    const markdown = `# ${title}\n\n导出时间：${new Date().toLocaleString("zh-CN")}\n\n${sections.join("\n\n")}\n`;
    const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${title.replace(/[\\/:*?"<>|]/g, "-") || "lexora-case"}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function newAnalysis() {
    setSelectedCaseId(null);
    setDraftMode(true);
    setCaseTitle("");
    setPendingUserMessage(null);
    setPendingAssistantMessage(null);
    setMaterialPanelOpen(false);
    setProfilePanelOpen(false);
    conversation.reset();
  }

  const errorSource = conversation.error ?? casesQuery.error ?? messagesQuery.error;
  const error = errorSource instanceof Error ? errorSource.message : null;
  const materials = materialsQuery.data ?? [];
  const profile = selectedCase ? normalizeCaseProfile(selectedCase.profile) : emptyCaseProfile;
  const profileItemCount = (profile.case_type ? 1 : 0)
    + profile.parties.length
    + profile.claims.length
    + profile.key_facts.length
    + profile.disputed_issues.length
    + profile.evidence_notes.length
    + profile.missing_information.length;

  return (
    <main className={styles.workspace}>
      <aside className={styles.navigation} aria-label="案件导航">
        <div className={styles.brandBlock}>
          <div className={styles.brandMark}><Scale aria-hidden="true" size={22} /></div>
          <div>
            <h1>法析 Lexora</h1>
            <span>AI 法律案例分析助手</span>
          </div>
        </div>

        <button className={styles.newButton} onClick={newAnalysis} type="button">
          <CirclePlus aria-hidden="true" size={19} />
          新建分析
        </button>

        <nav className={styles.caseList} aria-label="案件列表">
          <span className={styles.sectionLabel}>案件</span>
          {casesQuery.data?.map((item) => (
            <button
              className={`${styles.caseButton} ${item.id === activeCaseId ? styles.activeCase : ""}`}
              key={item.id}
              onClick={() => {
                setSelectedCaseId(item.id);
                setCaseTitle(item.title);
                setDraftMode(false);
                setPendingUserMessage(null);
                conversation.reset();
                setProfilePanelOpen(false);
              }}
              type="button"
            >
              <MessageSquareText aria-hidden="true" size={17} />
              <span>{item.title}</span>
              <small>{item.material_count}</small>
            </button>
          ))}
          {draftMode || !casesQuery.data?.length ? (
            <button className={`${styles.caseButton} ${styles.activeCase}`} type="button">
              <MessageSquareText aria-hidden="true" size={17} />
              <span>{displayedCaseTitle.trim() || "未命名案件"}</span>
            </button>
          ) : null}
        </nav>

        <div className={styles.navigationFooter}>
          <span className={activeCaseId ? styles.connected : styles.ready} />
          {activeCaseId ? "案件已保存" : "等待描述案情"}
        </div>
      </aside>

      <ConversationPanel
        caseTitle={displayedCaseTitle}
        error={error}
        isCancelling={cancelMutation.isPending}
        isSubmitting={conversation.isPending}
        materialCount={materials.length}
        profileItemCount={profileItemCount}
        messages={messages}
        onCaseTitleChange={setCaseTitle}
        onCaseTitleCommit={() => void titleMutation.mutate()}
        onExport={exportCaseRecord}
        onCancel={() => {
          if (
            activeCaseId
            && conversation.isPending
          ) {
            void cancelMutation.mutateAsync().finally(() => {
              conversationAbortRef.current?.abort();
            });
          }
        }}
        onOpenMaterials={() => setMaterialPanelOpen(true)}
        onOpenProfile={() => setProfilePanelOpen(true)}
        onSend={sendMessage}
      />

      <MaterialPanel
        materials={materials}
        onAdd={persistMaterial}
        onClose={() => setMaterialPanelOpen(false)}
        onRemove={removeMaterial}
        onUpload={persistUpload}
        open={materialPanelOpen}
      />

      {profilePanelOpen ? (
        <CaseProfilePanel
          error={profileMutation.error instanceof Error ? profileMutation.error.message : null}
          onClose={() => setProfilePanelOpen(false)}
          onSave={async (value) => { await profileMutation.mutateAsync(value); }}
          profile={profile}
          saving={profileMutation.isPending}
        />
      ) : null}
    </main>
  );
}
