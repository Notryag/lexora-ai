"use client";

import { Save, X } from "lucide-react";
import { useState } from "react";

import type { CaseProfile } from "./api";
import styles from "./CaseProfilePanel.module.css";

export const emptyCaseProfile: CaseProfile = {
  case_type: null,
  parties: [],
  claims: [],
  key_facts: [],
  disputed_issues: [],
  evidence_notes: [],
  missing_information: [],
};

type ListField =
  | "parties"
  | "claims"
  | "key_facts"
  | "disputed_issues"
  | "evidence_notes"
  | "missing_information";

type CaseProfilePanelProps = {
  error: string | null;
  onClose: () => void;
  onSave: (profile: CaseProfile) => Promise<void>;
  profile: CaseProfile;
  saving: boolean;
};

const listFields: Array<{ field: ListField; label: string; placeholder: string }> = [
  { field: "parties", label: "当事人", placeholder: "每行一项，如：张某（劳动者）" },
  { field: "claims", label: "诉求", placeholder: "每行一项" },
  { field: "key_facts", label: "当事人陈述", placeholder: "每行一项，仅记录已确认要纳入分析的描述" },
  { field: "disputed_issues", label: "争议焦点", placeholder: "每行一项" },
  { field: "evidence_notes", label: "证据线索", placeholder: "每行一项" },
  { field: "missing_information", label: "待补信息", placeholder: "每行一项" },
];

function splitLines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

export function CaseProfilePanel({
  error,
  onClose,
  onSave,
  profile,
  saving,
}: CaseProfilePanelProps) {
  const [draft, setDraft] = useState<CaseProfile>(profile);

  function updateList(field: ListField, value: string) {
    setDraft((current) => ({ ...current, [field]: splitLines(value) }));
  }

  return (
    <>
      <button aria-label="关闭案件档案" className={styles.backdrop} onClick={onClose} />
      <aside className={styles.panel} aria-label="案件档案">
        <header className={styles.header}>
          <div>
            <h2>案件档案</h2>
            <span>用户确认的信息</span>
          </div>
          <button aria-label="关闭案件档案" className={styles.iconButton} onClick={onClose} type="button">
            <X aria-hidden="true" size={20} />
          </button>
        </header>

        <div className={styles.fields}>
          <label>
            <span>案件类型</span>
            <input
              maxLength={120}
              onChange={(event) => setDraft((current) => ({
                ...current,
                case_type: event.target.value || null,
              }))}
              placeholder="如：劳动合同争议"
              value={draft.case_type ?? ""}
            />
          </label>

          {listFields.map(({ field, label, placeholder }) => (
            <label key={field}>
              <span>{label}</span>
              <textarea
                onChange={(event) => updateList(field, event.target.value)}
                placeholder={placeholder}
                rows={field === "key_facts" ? 5 : 3}
                value={draft[field].join("\n")}
              />
            </label>
          ))}
        </div>

        <footer className={styles.footer}>
          {error ? <div className={styles.error} role="alert">{error}</div> : null}
          <button disabled={saving} onClick={() => void onSave(draft)} type="button">
            <Save aria-hidden="true" size={18} />
            {saving ? "保存中" : "保存档案"}
          </button>
        </footer>
      </aside>
    </>
  );
}
