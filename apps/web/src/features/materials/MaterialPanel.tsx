"use client";

import { FilePlus2, FileText, Trash2, X } from "lucide-react";
import { useRef, useState } from "react";

import type {
  CaseMaterial,
  MaterialKind,
  StoredCaseMaterial,
} from "@/features/conversation/types";

import styles from "./MaterialPanel.module.css";

const materialKinds: Array<{ value: MaterialKind; label: string }> = [
  { value: "contract", label: "合同" },
  { value: "evidence", label: "证据" },
  { value: "complaint", label: "起诉材料" },
  { value: "defense", label: "答辩材料" },
  { value: "transcript", label: "笔录" },
  { value: "judgment", label: "裁判文书" },
  { value: "statute", label: "法规" },
  { value: "other", label: "其他" },
];

type MaterialPanelProps = {
  materials: StoredCaseMaterial[];
  onAdd: (material: CaseMaterial) => Promise<void>;
  onClose: () => void;
  onRemove: (materialId: string) => Promise<void>;
  onUpload: (file: File) => Promise<void>;
  open: boolean;
};

export function MaterialPanel({
  materials,
  onAdd,
  onClose,
  onRemove,
  onUpload,
  open,
}: MaterialPanelProps) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<MaterialKind>("evidence");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function resetForm() {
    setTitle("");
    setKind("evidence");
    setContent("");
    setAdding(false);
  }

  async function submitMaterial() {
    if (materials.length >= 20 || !title.trim() || !content.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd({ title: title.trim(), kind, content: content.trim(), source_note: null });
      resetForm();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "添加材料失败");
    } finally {
      setBusy(false);
    }
  }

  async function importFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      await onUpload(file);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "上传材料失败");
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <>
      {open ? <button aria-label="关闭材料区" className={styles.backdrop} onClick={onClose} /> : null}
      <aside className={`${styles.panel} ${open ? styles.open : ""}`} aria-label="案件材料">
        <header className={styles.header}>
          <div>
            <h2>案件材料</h2>
            <span>{materials.length} 份</span>
          </div>
          <button aria-label="关闭材料面板" className={styles.closeButton} onClick={onClose} type="button">
            <X aria-hidden="true" size={20} />
          </button>
        </header>

        <div className={styles.actions}>
          <button
            className={styles.primaryAction}
            disabled={materials.length >= 20}
            onClick={() => setAdding(true)}
            type="button"
          >
            <FilePlus2 aria-hidden="true" size={18} />
            新建材料
          </button>
          <button
            className={styles.secondaryAction}
            disabled={busy || materials.length >= 20}
            onClick={() => fileInputRef.current?.click()}
            type="button"
          >
            <FileText aria-hidden="true" size={18} />
            导入文本
          </button>
          <input
            accept=".pdf,.docx,.txt,.md,application/pdf,text/plain,text/markdown"
            className={styles.fileInput}
            onChange={(event) => void importFile(event.target.files?.[0])}
            ref={fileInputRef}
            type="file"
          />
        </div>

        {adding ? (
          <section className={styles.editor} aria-label="编辑材料">
            <input
              autoFocus
              maxLength={200}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="材料名称"
              value={title}
            />
            <select onChange={(event) => setKind(event.target.value as MaterialKind)} value={kind}>
              {materialKinds.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
            <textarea
              maxLength={40_000}
              onChange={(event) => setContent(event.target.value)}
              placeholder="粘贴材料正文"
              rows={9}
              value={content}
            />
            <div className={styles.editorActions}>
              <button className={styles.cancelButton} onClick={resetForm} type="button">取消</button>
              <button
                className={styles.saveButton}
                disabled={materials.length >= 20 || !title.trim() || !content.trim()}
                onClick={() => void submitMaterial()}
                type="button"
              >
                {busy ? "保存中" : "添加"}
              </button>
            </div>
          </section>
        ) : null}

        {error ? <div className={styles.error} role="alert">{error}</div> : null}

        <div className={styles.list}>
          {materials.length === 0 && !adding ? (
            <div className={styles.empty}>尚未添加材料</div>
          ) : null}
          {materials.map((material) => (
            <article className={styles.material} key={material.material_id}>
              <div className={styles.materialIcon}><FileText aria-hidden="true" size={17} /></div>
              <div className={styles.materialBody}>
                <strong>{material.title}</strong>
                <span>{materialKinds.find((item) => item.value === material.kind)?.label ?? "其他"}</span>
                <p>{material.content}</p>
              </div>
              <button
                aria-label={`删除材料 ${material.title}`}
                className={styles.deleteButton}
                disabled={busy}
                onClick={() => material.material_id && void onRemove(material.material_id)}
                title="删除材料"
                type="button"
              >
                <Trash2 aria-hidden="true" size={17} />
              </button>
            </article>
          ))}
        </div>
      </aside>
    </>
  );
}
