"use client";

/**
 * 드라이브 — 워크스페이스의 문서(작성한 리포트)와 데이터(올린 파일)를 폴더로 정리한다(구글 드라이브처럼).
 * 왼쪽 = 폴더 트리(펼치기·접기, 누르면 그 폴더), 오른쪽 = 고른 폴더의 하위 폴더·파일 목록.
 * 폴더: 만들기·이름 바꾸기·공유(멤버 전체 / 나만 / 고른 멤버)·옮기기·지우기(안의 것은 한 칸 위로). 폴더·파일은 목록이나 트리의 폴더로 끌어 옮기고, 화면에 끌어다 놓아 올린다.
 * 데이터 행의 'AI 참고' = 이 워크스페이스에서 에이전트가 쓰는지. 데이터를 누르면 오른쪽 미리보기, 문서를 누르면 작성 화면.
 * 숨긴 기능(FEATURES): 데이터 연결·공용 자료실·판 비교.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronRight, FilePlus2, FileText, Folder, FolderInput, FolderOpen, FolderPlus, HardDrive, History, Library, Loader2, Lock, MoreHorizontal, Pencil, PlugZap, Plus, Share2, Table2, Trash2, Upload, Users, X } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { ApiError, removeDocument, uploadDocuments } from "../../../report/api";
import { ACCEPT } from "../../../report/components/library/DocumentsFolder";
import { FileTypeIcon, formatSize } from "../../../report/components/library/rows";
import { DocViewerBody } from "../../../report/components/viewer/DocViewerBody";
import type { DocumentCard } from "../../../report/types";
import { AssetDrawer } from "./AssetsView";
import { createFolder, deleteFolder, getDrive, moveDriveItems, setDocumentEvidence, updateFolder } from "../../api";
import { useWorkspace } from "../../context";
import { FEATURES } from "../../features";
import type { DriveListing, FolderAccess } from "../../types";
import { DocTablesDialog } from "../DocTablesDialog";
import { NewDocumentDialog } from "../NewDocumentDialog";
import { ConnectorsPanel } from "./ConnectorPanels";
import { LibraryPanel } from "./LibraryPanel";
import { VersionCompare } from "./VersionCompare";

/** 끄는 항목 — 폴더는 id 가 'folder:<폴더 id>' */
type Drag = { id: string; kind: "doc" | "data" | "table" };
type DropProps = { onDragOver: (e: React.DragEvent) => void; onDragLeave: () => void; onDrop: (e: React.DragEvent) => void };
const DRAG = "application/x-dcf-drive";

function shortDate(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.getFullYear() === now.getFullYear() ? `${d.getMonth() + 1}월 ${d.getDate()}일` : `${d.getFullYear()}. ${d.getMonth() + 1}. ${d.getDate()}.`;
}

function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4" onMouseDown={onClose}>
      <div onMouseDown={(e) => e.stopPropagation()} className="w-full max-w-[440px] rounded-[24px] bg-white p-6 shadow-xl">
        <h2 className="text-[20px] font-bold tracking-tight text-text-primary">{title}</h2>
        <div className="mt-4">{children}</div>
        <div className="mt-6 flex justify-end gap-2">{footer}</div>
      </div>
    </div>
  );
}

const btnGray = "h-10 cursor-pointer rounded-xl bg-neutral-100 px-4 text-[14px] font-semibold text-neutral-700 hover:bg-neutral-200";
const btnBlue = "h-10 cursor-pointer rounded-xl bg-primary px-4 text-[14px] font-semibold text-white hover:bg-primary-hover disabled:opacity-40";

export function DriveView({ initialFolder = null }: { initialFolder?: string | null }) {
  const ws = useWorkspace();
  const canEdit = ws.can("editor");
  const canUpload = ws.can("reviewer");
  const [folder, setFolder] = useState<string | null>(initialFolder);
  const [d, setD] = useState<DriveListing | null>(null);
  const [preview, setPreview] = useState<DocumentCard | null>(null);
  const [comparing, setComparing] = useState<DocumentCard | null>(null);
  const [naming, setNaming] = useState<{ id?: string; name: string } | null>(null);
  const [sharing, setSharing] = useState<string | null>(null);
  const [moving, setMoving] = useState<Drag[] | null>(null);
  const [newDoc, setNewDoc] = useState(false);
  const [menu, setMenu] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [dropOver, setDropOver] = useState<string | null>(null);
  const [fileOver, setFileOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [panel, setPanel] = useState<"connect" | "library" | null>(null);
  const [tablesOf, setTablesOf] = useState<DocumentCard | null>(null);
  const [tableOpen, setTableOpen] = useState<string | null>(null);
  const dragRef = useRef<Drag | null>(null);

  const load = useCallback(
    async (target: string | null = folder) => {
      try {
        setD(await getDrive(ws.workspaceId, target));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404 && target) setFolder(null);
        else toast.error("불러오지 못했습니다.", { position: "top-center" });
      }
    },
    [folder, ws.workspaceId],
  );

  useEffect(() => {
    void load(folder);
  }, [folder, load]);

  // 처리 중인 업로드가 있으면 3초마다 다시
  const pending = (d?.jobs ?? []).filter((j) => j.status === "queued" || j.status === "processing").length;
  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => void load(folder), 3000);
    return () => clearTimeout(timer);
  }, [pending, d, folder, load]);

  useEffect(() => {
    if (!menu && !createOpen) return;
    const close = () => {
      setMenu(null);
      setCreateOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("click", close);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("keydown", esc);
    };
  }, [menu, createOpen]);
  /** 메뉴는 한 번에 하나만 */
  const toggleMenu = (key: string) => {
    setCreateOpen(false);
    setMenu((m) => (m === key ? null : key));
  };

  const run = async (fn: () => Promise<unknown>, fail: string) => {
    try {
      const r = await fn();
      if (r && typeof r === "object" && "folders" in r) setD(r as DriveListing);
      else await load(folder);
      return true;
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
      return false;
    }
  };

  const upload = async (files: File[]) => {
    if (!files.length || !canUpload) return;
    setUploading(true);
    await run(async () => {
      const r = await uploadDocuments(ws.workspaceId, files, undefined, folder);
      if (r.errors?.length) toast.error(r.errors.join("\n"), { position: "top-center" });
    }, "올리지 못했습니다.");
    setUploading(false);
  };

  const pick = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ACCEPT;
    input.onchange = () => void upload(input.files ? Array.from(input.files) : []);
    input.click();
  };

  const dropOn = (target: string | null) => (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDropOver(null);
    const item = dragRef.current;
    dragRef.current = null;
    if (!item || !canEdit || target === folder) return;
    if (item.id.startsWith("folder:")) {
      const id = item.id.slice(7);
      if (id !== target)
        void run(async () => {
          await updateFolder(ws.workspaceId, id, { parentId: target });
        }, "옮기지 못했습니다.");
    } else void run(() => moveDriveItems(ws.workspaceId, [item], target, folder), "옮기지 못했습니다.");
  };
  const dropTarget = (key: string, target: string | null): DropProps => ({
    onDragOver: (e: React.DragEvent) => {
      if (!dragRef.current) return;
      e.preventDefault();
      e.stopPropagation();
      setDropOver(key);
    },
    onDragLeave: () => setDropOver((k) => (k === key ? null : k)),
    onDrop: dropOn(target),
  });

  const empty = d && !d.folders.length && !d.docs.length && !d.data.length && !d.tables.length && !d.jobs.length;

  return (
    <div className="flex min-h-0 flex-1">
      <FolderTree tree={d?.tree ?? []} current={folder} path={(d?.path ?? []).map((p) => p.id)} onOpen={setFolder} dropTarget={dropTarget} dropOver={dropOver} />
      <section
        onDragOver={(e) => {
          if (dragRef.current || !canUpload || !e.dataTransfer.types.includes("Files")) return;
          e.preventDefault();
          setFileOver(true);
        }}
        onDragLeave={(e) => e.currentTarget === e.target && setFileOver(false)}
        onDrop={(e) => {
          if (dragRef.current || !e.dataTransfer.files.length) return;
          e.preventDefault();
          setFileOver(false);
          void upload(Array.from(e.dataTransfer.files));
        }}
        className={cn("thin-scrollbar min-w-0 flex-1 overflow-y-auto bg-white px-8 pt-7 pb-12 transition-colors", fileOver && "bg-primary-soft/40")}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <nav aria-label="폴더 경로" className="flex min-w-0 flex-wrap items-center gap-1 text-[22px] font-bold tracking-tight">
            <button type="button" onClick={() => setFolder(null)} {...dropTarget("root", null)} className={cn("cursor-pointer rounded-lg px-1.5 py-0.5 hover:bg-neutral-100", d?.path.length ? "text-neutral-500" : "text-text-primary", dropOver === "root" && "bg-primary-soft")}>
              드라이브
            </button>
            {d?.path.map((p, i) => (
              <span key={p.id} className="flex min-w-0 items-center gap-1">
                <ChevronRight className="size-5 shrink-0 text-neutral-400" aria-hidden />
                <button type="button" onClick={() => setFolder(p.id)} {...dropTarget(`p-${p.id}`, p.id)} className={cn("max-w-[260px] cursor-pointer truncate rounded-lg px-1.5 py-0.5 hover:bg-neutral-100", i === d.path.length - 1 ? "text-text-primary" : "text-neutral-500", dropOver === `p-${p.id}` && "bg-primary-soft")}>
                  {p.name}
                </button>
              </span>
            ))}
            {d?.folder && d.folder.access !== "all" && (d.folder.access === "private" ? <Lock className="ml-1 size-4 text-neutral-500" aria-label="나만 보기" /> : <Users className="ml-1 size-4 text-neutral-500" aria-label="고른 멤버만" />)}
          </nav>
          <div className="flex items-center gap-2">
            {FEATURES.connectors && canUpload && (
              <button type="button" onClick={() => setPanel((p) => (p === "connect" ? null : "connect"))} className={cn(btnGray, "flex items-center gap-1.5")}>
                <PlugZap className="size-4" aria-hidden />
                데이터 연결
              </button>
            )}
            {FEATURES.library && canUpload && (
              <button type="button" onClick={() => setPanel((p) => (p === "library" ? null : "library"))} className={cn(btnGray, "flex items-center gap-1.5")}>
                <Library className="size-4" aria-hidden />
                공용 자료실
              </button>
            )}
            {d?.folder?.canShare && (
              <button type="button" onClick={() => setSharing(d.folder!.id)} className={cn(btnGray, "flex items-center gap-1.5")}>
                <Share2 className="size-4" aria-hidden />
                공유
              </button>
            )}
            {(canEdit || canUpload) && (
              <div className="relative">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setMenu(null);
                    setCreateOpen((v) => !v);
                  }}
                  className={cn(btnBlue, "flex items-center gap-1.5")}
                >
                  {uploading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Plus className="size-4" aria-hidden />}
                  새로 만들기
                </button>
                {createOpen && (
                  <div className="absolute top-full right-0 z-30 mt-1.5 w-48 rounded-2xl bg-white p-1.5 shadow-[0_8px_24px_rgba(0,27,55,0.14)]">
                    {canEdit && <MenuItem icon={FolderPlus} label="새 폴더" onClick={() => (setCreateOpen(false), setNaming({ name: "" }))} />}
                    {canUpload && <MenuItem icon={Upload} label="파일 올리기" onClick={() => (setCreateOpen(false), pick())} />}
                    {canEdit && <MenuItem icon={FilePlus2} label="새 문서" onClick={() => (setCreateOpen(false), setNewDoc(true))} />}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {panel === "connect" && (
          <div className="mt-4">
            <ConnectorsPanel onClose={() => setPanel(null)} onFetched={() => void load(folder)} />
          </div>
        )}
        {panel === "library" && (
          <div className="mt-4">
            <LibraryPanel onClose={() => setPanel(null)} onAttached={() => void load(folder)} />
          </div>
        )}

        {!d && <p className="mt-6 text-[14px] text-neutral-500">불러오는 중…</p>}

        {d && (d.folders.length > 0 || d.docs.length > 0 || d.data.length > 0 || d.tables.length > 0 || d.jobs.length > 0) && (
          <section className="mt-6">
            <div className="grid grid-cols-[minmax(0,1fr)_120px_96px_72px_76px_36px] items-center gap-x-3 border-b border-neutral-100 px-3 pb-2 text-[12px] font-semibold text-neutral-500">
              <span>이름</span>
              <span>소유자</span>
              <span>수정</span>
              <span>크기</span>
              <span>AI 참고</span>
              <span />
            </div>
            {d.folders.map((f) => (
              <div
                key={f.id}
                {...dropTarget(f.id, f.id)}
                draggable={canEdit}
                onDragStart={() => (dragRef.current = { id: `folder:${f.id}`, kind: "doc" })}
                onDragEnd={() => (dragRef.current = null, setDropOver(null))}
                onClick={() => setFolder(f.id)}
                className={cn("group grid cursor-pointer grid-cols-[minmax(0,1fr)_120px_96px_72px_76px_36px] items-center gap-x-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-neutral-50", dropOver === f.id && "bg-primary-soft ring-2 ring-primary/40 hover:bg-primary-soft")}
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="flex h-8 w-7 shrink-0 items-center justify-center">
                    <Folder className="size-6 fill-amber-300 text-amber-400" aria-hidden />
                  </span>
                  <span className="truncate text-[14px] font-medium text-text-primary">{f.name}</span>
                  {f.access === "private" && <Lock className="size-3.5 shrink-0 text-neutral-500" aria-label="나만 보기" />}
                  {f.access === "members" && <Users className="size-3.5 shrink-0 text-neutral-500" aria-label="고른 멤버만" />}
                </span>
                <span className="truncate text-[13px] text-neutral-600">{f.createdBy}</span>
                <span className="text-[13px] text-neutral-600">{shortDate(f.updatedAt)}</span>
                <span className="text-[13px] text-neutral-600">항목 {f.items}</span>
                <span className="text-[13px] text-neutral-400">—</span>
                <RowMenu
                  open={menu === `folder:${f.id}`}
                  onToggle={() => toggleMenu(`folder:${f.id}`)}
                  items={
                    canEdit
                      ? [
                          { icon: Pencil, label: "이름 바꾸기", onClick: () => setNaming({ id: f.id, name: f.name }) },
                          { icon: Share2, label: "공유", onClick: () => setSharing(f.id) },
                          { icon: FolderInput, label: "옮기기", onClick: () => setMoving([{ id: `folder:${f.id}`, kind: "doc" }]) },
                          { icon: Trash2, label: "지우기", danger: true, onClick: () => window.confirm(`'${f.name}' 폴더를 지울까요? 안의 문서·데이터는 한 칸 위로 옮겨집니다.`) && void run(() => deleteFolder(ws.workspaceId, f.id), "지우지 못했습니다.") },
                        ]
                      : []
                  }
                />
              </div>
            ))}
            {d.jobs.map((j) => (
              <div key={j.id} className="grid grid-cols-[minmax(0,1fr)_120px_96px_72px_76px_36px] items-center gap-x-3 px-3 py-2.5 text-[14px] text-neutral-500">
                <span className="flex min-w-0 items-center gap-2.5">
                  <FileTypeIcon type={j.fileName.split(".").pop() ?? ""} />
                  <span className="truncate">{j.fileName}</span>
                </span>
                <span className="col-span-5 flex items-center gap-1.5 text-[13px]">
                  {j.status === "error" ? <span className="text-[#f04452]">실패 {j.error ?? ""}</span> : <><Loader2 className="size-3.5 animate-spin" aria-hidden />처리 중</>}
                </span>
              </div>
            ))}
            {d.docs.map((r) => (
              <div
                key={r.id}
                draggable={canEdit}
                onDragStart={() => (dragRef.current = { id: r.id, kind: "doc" })}
                onDragEnd={() => (dragRef.current = null, setDropOver(null))}
                onClick={() => ws.nav.openReport(r.id)}
                className="group grid cursor-pointer grid-cols-[minmax(0,1fr)_120px_96px_72px_76px_36px] items-center gap-x-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-neutral-50"
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="flex h-8 w-7 shrink-0 items-center justify-center rounded-md bg-primary text-white">
                    <FileText className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] font-medium text-text-primary">{r.title}</span>
                    <span className="block truncate text-[12px] text-neutral-500">
                      {ws.meta.reportTypes.find((t) => t.id === r.reportType)?.title ?? "문서"} · {r.written}/{r.sections} 섹션
                    </span>
                  </span>
                </span>
                <span className="truncate text-[13px] text-neutral-600">{r.createdBy}</span>
                <span className="text-[13px] text-neutral-600">{shortDate(r.updatedAt)}</span>
                <span className="text-[13px] text-neutral-400">—</span>
                <span className="text-[13px] text-neutral-400">—</span>
                <RowMenu
                  open={menu === `doc:${r.id}`}
                  onToggle={() => toggleMenu(`doc:${r.id}`)}
                  items={canEdit ? [{ icon: FolderInput, label: "옮기기", onClick: () => setMoving([{ id: r.id, kind: "doc" }]) }] : []}
                />
              </div>
            ))}
            {d.tables.map((t) => (
              <div
                key={t.id}
                draggable={canEdit}
                onDragStart={() => (dragRef.current = { id: t.id, kind: "table" })}
                onDragEnd={() => (dragRef.current = null, setDropOver(null))}
                onClick={() => (t.chatId ? ws.nav.openReport(t.chatId, t.id) : setTableOpen(t.id))}
                className="group grid cursor-pointer grid-cols-[minmax(0,1fr)_120px_96px_72px_76px_36px] items-center gap-x-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-neutral-50"
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="flex h-8 w-7 shrink-0 items-center justify-center rounded-md bg-emerald-600 text-white">
                    <Table2 className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] font-medium text-text-primary">{t.title}</span>
                    <span className="block truncate text-[12px] text-neutral-500">
                      {FEATURES.assets ? "" : "정리한 데이터 · "}
                      {t.kind === "note" ? "메모" : t.kind === "chart" ? "차트" : `표 · ${t.rows}행 × ${t.cols}열`}
                    </span>
                  </span>
                </span>
                <span className="truncate text-[13px] text-neutral-600">{t.createdBy}</span>
                <span className="text-[13px] text-neutral-600">{shortDate(t.updatedAt)}</span>
                <span className="text-[13px] text-neutral-400">—</span>
                <span className="text-[13px] text-neutral-400">—</span>
                <RowMenu
                  open={menu === `table:${t.id}`}
                  onToggle={() => toggleMenu(`table:${t.id}`)}
                  items={canEdit ? [{ icon: FolderInput, label: "옮기기", onClick: () => setMoving([{ id: t.id, kind: "table" }]) }] : []}
                />
              </div>
            ))}
            {d.data.map((c) => (
              <div
                key={c.id}
                draggable={canEdit}
                onDragStart={() => (dragRef.current = { id: c.id, kind: "data" })}
                onDragEnd={() => (dragRef.current = null, setDropOver(null))}
                onClick={() => (setPreview(c), setComparing(null))}
                className={cn("group grid cursor-pointer grid-cols-[minmax(0,1fr)_120px_96px_72px_76px_36px] items-center gap-x-3 rounded-xl px-3 py-2.5 transition-colors hover:bg-neutral-50", preview?.id === c.id && "bg-primary-soft hover:bg-primary-soft")}
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <FileTypeIcon type={c.fileType} />
                  <span className={cn("truncate text-[14px] font-medium", c.excluded ? "text-neutral-400" : "text-text-primary")} title={c.fileName}>
                    {c.label}
                  </span>
                  {FEATURES.versions && c.version && c.version.version > 1 && <span className="shrink-0 rounded bg-violet-50 px-1 text-[11px] font-semibold text-violet-700">v{c.version.version}</span>}
                  {FEATURES.assets && c.assets && (
                    <button
                      type="button"
                      onClick={(e) => (e.stopPropagation(), setTablesOf(c))}
                      title="자료 속 표 — 에셋으로 꺼내기"
                      className={cn("shrink-0 cursor-pointer rounded-full px-2 py-0.5 text-[11px] font-semibold", c.assets.similar ? "bg-primary-soft text-primary hover:bg-primary-soft/70" : "bg-neutral-100 text-neutral-500 hover:bg-neutral-200")}
                    >
                      {c.assets.similar ? `같은 모양 표 ${c.assets.similar}` : `표 ${c.assets.tables}`}
                    </button>
                  )}
                </span>
                <span className="truncate text-[13px] text-neutral-600">{c.uploadedBy}</span>
                <span className="text-[13px] text-neutral-600">{shortDate(c.uploadedAt ?? c.createdAt)}</span>
                <span className="text-[13px] text-neutral-600">{formatSize(c.size)}</span>
                <span onClick={(e) => e.stopPropagation()}>
                  <Switch on={!c.excluded} disabled={!canEdit} onChange={(on) => void run(() => setDocumentEvidence(ws.workspaceId, c.id, on), "바꾸지 못했습니다.")} label={`${c.label} AI 참고`} />
                </span>
                <RowMenu
                  open={menu === `data:${c.id}`}
                  onToggle={() => toggleMenu(`data:${c.id}`)}
                  items={[
                    ...(canEdit ? [{ icon: FolderInput, label: "옮기기", onClick: () => setMoving([{ id: c.id, kind: "data" as const }]) }] : []),
                    ...(FEATURES.versions && c.version && c.version.version > 1 ? [{ icon: History, label: "이전 판과 비교", onClick: () => (setComparing(c), setPreview(null)) }] : []),
                    ...(canEdit ? [{ icon: Trash2, label: "워크스페이스에서 빼기", danger: true, onClick: () => window.confirm("이 데이터를 워크스페이스에서 뺄까요? 이미 쓴 본문의 출처 표기는 남습니다.") && void run(() => removeDocument(ws.workspaceId, { doc: c.id }), "빼지 못했습니다.") }] : []),
                  ]}
                />
              </div>
            ))}
          </section>
        )}

        {empty && (
          <div className="mt-16 flex flex-col items-center gap-3 text-center">
            <Folder className="size-14 fill-neutral-100 text-neutral-300" aria-hidden />
            <p className="text-[16px] font-semibold text-text-primary">{d?.folder ? "폴더가 비어 있어요" : "드라이브가 비어 있어요"}</p>
            {canUpload && (
              <div className="flex gap-2">
                <button type="button" onClick={pick} className={cn(btnGray, "flex items-center gap-1.5")}>
                  <Upload className="size-4" aria-hidden />
                  파일 올리기
                </button>
                {canEdit && (
                  <button type="button" onClick={() => setNewDoc(true)} className={cn(btnBlue, "flex items-center gap-1.5")}>
                    <FilePlus2 className="size-4" aria-hidden />새 문서
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      {(preview || comparing) && (
        <aside className="flex w-[440px] shrink-0 flex-col border-l border-neutral-200 bg-white">
          <div className="flex justify-end border-b border-neutral-100 px-2 py-1">
            <button type="button" aria-label="닫기" onClick={() => (setPreview(null), setComparing(null))} className="cursor-pointer rounded-lg p-1.5 text-neutral-500 hover:bg-neutral-100">
              <X className="size-4" aria-hidden />
            </button>
          </div>
          <div className="min-h-0 flex-1">
            {comparing ? <VersionCompare workspaceId={ws.workspaceId} doc={comparing} onView={() => undefined} onClose={() => setComparing(null)} /> : preview && <DocViewerBody workspaceId={ws.workspaceId} doc={preview} />}
          </div>
        </aside>
      )}

      {naming && (
        <Modal
          title={naming.id ? "이름 바꾸기" : "새 폴더"}
          onClose={() => setNaming(null)}
          footer={
            <>
              <button type="button" onClick={() => setNaming(null)} className={btnGray}>
                취소
              </button>
              <button
                type="button"
                disabled={!naming.name.trim()}
                onClick={() => void run(() => (naming.id ? updateFolder(ws.workspaceId, naming.id, { name: naming.name }) : createFolder(ws.workspaceId, naming.name, folder)), "저장하지 못했습니다.").then((ok) => ok && setNaming(null))}
                className={btnBlue}
              >
                {naming.id ? "바꾸기" : "만들기"}
              </button>
            </>
          }
        >
          <input
            autoFocus
            value={naming.name}
            onChange={(e) => setNaming({ ...naming, name: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && naming.name.trim() && void run(() => (naming.id ? updateFolder(ws.workspaceId, naming.id, { name: naming.name }) : createFolder(ws.workspaceId, naming.name, folder)), "저장하지 못했습니다.").then((ok) => ok && setNaming(null))}
            placeholder="폴더 이름"
            className="h-11 w-full rounded-xl bg-neutral-100 px-4 text-[15px] outline-none focus:bg-white focus:ring-2 focus:ring-primary/30"
          />
        </Modal>
      )}

      {sharing && d && <ShareDialog folderId={sharing} listing={d} onClose={() => setSharing(null)} onSave={(access, memberIds) => run(() => updateFolder(ws.workspaceId, sharing, { access, memberIds }), "공유 설정을 바꾸지 못했습니다.").then(() => load(folder))} />}

      {moving && d && (
        <MoveDialog
          listing={d}
          exclude={moving[0]?.id.startsWith("folder:") ? moving[0].id.slice(7) : null}
          onClose={() => setMoving(null)}
          onMove={(target) => {
            const first = moving[0];
            const task = first?.id.startsWith("folder:") ? () => updateFolder(ws.workspaceId, first.id.slice(7), { parentId: target }) : () => moveDriveItems(ws.workspaceId, moving, target, folder);
            return run(task, "옮기지 못했습니다.").then(() => (setMoving(null), load(folder)));
          }}
        />
      )}

      {newDoc && <NewDocumentDialog folderId={folder} onClose={() => setNewDoc(false)} />}
      {tablesOf && <DocTablesDialog doc={tablesOf} onClose={() => setTablesOf(null)} onChanged={() => void load(folder)} />}
      {tableOpen && (
        <div className="fixed inset-y-0 right-0 z-40 flex shadow-2xl">
          <AssetDrawer key={tableOpen} id={tableOpen} taskId={null} onClose={() => setTableOpen(null)} onChanged={() => void load(folder)} onRemoved={() => (setTableOpen(null), void load(folder))} />
        </div>
      )}
    </div>
  );
}

function MenuItem({ icon: Icon, label, onClick, danger }: { icon: typeof Folder; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={cn("flex w-full cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2 text-left text-[14px] font-medium hover:bg-neutral-100", danger ? "text-[#f04452]" : "text-text-primary")}
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </button>
  );
}

function RowMenu({ open, onToggle, items }: { open: boolean; onToggle: () => void; items: { icon: typeof Folder; label: string; onClick: () => void; danger?: boolean }[] }) {
  if (!items.length) return <span />;
  return (
    <span className="relative" onClick={(e) => e.stopPropagation()}>
      <button type="button" aria-label="메뉴" onClick={onToggle} className="cursor-pointer rounded-lg p-1 text-neutral-500 opacity-0 group-hover:opacity-100 hover:bg-neutral-100">
        <MoreHorizontal className="size-4" aria-hidden />
      </button>
      {open && (
        <div className="absolute top-full right-0 z-30 mt-1 w-48 rounded-2xl bg-white p-1.5 shadow-[0_8px_24px_rgba(0,27,55,0.14)]">
          {items.map((it) => (
            <MenuItem key={it.label} {...it} onClick={() => (onToggle(), it.onClick())} />
          ))}
        </div>
      )}
    </span>
  );
}

function Switch({ on, disabled, onChange, label }: { on: boolean; disabled?: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)} className={cn("relative h-6 w-10 cursor-pointer rounded-full transition-colors disabled:cursor-default disabled:opacity-50", on ? "bg-primary" : "bg-neutral-300")}>
      <span className={cn("absolute top-0.5 size-5 rounded-full bg-white shadow transition-all", on ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

function ShareDialog({ folderId, listing, onClose, onSave }: { folderId: string; listing: DriveListing; onClose: () => void; onSave: (access: FolderAccess, memberIds: string[]) => Promise<unknown> }) {
  const ws = useWorkspace();
  const current = listing.folder?.id === folderId ? listing.folder : null;
  const card = listing.folders.find((f) => f.id === folderId);
  const [access, setAccess] = useState<FolderAccess>(current?.access ?? card?.access ?? "all");
  const [members, setMembers] = useState<string[]>(current?.memberIds ?? []);
  const others = listing.members.filter((m) => m.id !== ws.me.id);
  const options: { id: FolderAccess; label: string; icon: typeof Folder }[] = [
    { id: "all", label: "워크스페이스 멤버 전체", icon: Users },
    { id: "members", label: "고른 멤버만", icon: Users },
    { id: "private", label: "나만", icon: Lock },
  ];
  return (
    <Modal
      title={`'${current?.name ?? card?.name ?? ""}' 공유`}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={btnGray}>
            취소
          </button>
          <button type="button" onClick={() => void onSave(access, members).then(onClose)} className={btnBlue}>
            저장
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-1.5">
        {options.map((o) => (
          <button key={o.id} type="button" onClick={() => setAccess(o.id)} className={cn("flex cursor-pointer items-center gap-3 rounded-xl px-3.5 py-3 text-left transition-colors", access === o.id ? "bg-primary-soft ring-2 ring-primary/40" : "bg-neutral-50 hover:bg-neutral-100")}>
            <o.icon className={cn("size-[18px]", access === o.id ? "text-primary" : "text-neutral-500")} aria-hidden />
            <span className="text-[15px] font-semibold text-text-primary">{o.label}</span>
          </button>
        ))}
      </div>
      {access === "members" && (
        <div className="mt-3 flex flex-col gap-1">
          {others.map((m) => (
            <label key={m.id} className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-neutral-50">
              <input type="checkbox" checked={members.includes(m.id)} onChange={(e) => setMembers((cur) => (e.target.checked ? [...cur, m.id] : cur.filter((x) => x !== m.id)))} className="size-4 accent-primary" />
              <span className="text-[14px] text-text-primary">{m.name}</span>
            </label>
          ))}
        </div>
      )}
    </Modal>
  );
}

function MoveDialog({ listing, exclude, onClose, onMove }: { listing: DriveListing; exclude: string | null; onClose: () => void; onMove: (target: string | null) => Promise<unknown> }) {
  const [target, setTarget] = useState<string | null>(null);
  const tree = listing.tree;
  const blocked = new Set<string>();
  if (exclude) {
    const todo = [exclude];
    while (todo.length) {
      const id = todo.pop()!;
      blocked.add(id);
      todo.push(...tree.filter((f) => f.parentId === id).map((f) => f.id));
    }
  }
  const rows: { id: string; name: string; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const f of tree.filter((x) => (x.parentId ?? null) === parent).sort((a, b) => a.name.localeCompare(b.name))) {
      if (blocked.has(f.id)) continue;
      rows.push({ id: f.id, name: f.name, depth });
      walk(f.id, depth + 1);
    }
  };
  walk(null, 0);
  return (
    <Modal
      title="옮기기"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={btnGray}>
            취소
          </button>
          <button type="button" onClick={() => void onMove(target)} className={btnBlue}>
            여기로 옮기기
          </button>
        </>
      }
    >
      <div className="thin-scrollbar flex max-h-[300px] flex-col gap-0.5 overflow-y-auto">
        <button type="button" onClick={() => setTarget(null)} className={cn("flex cursor-pointer items-center gap-2.5 rounded-xl px-3 py-2.5 text-left text-[15px] font-semibold", target === null ? "bg-primary-soft text-primary" : "text-text-primary hover:bg-neutral-50")}>
          드라이브
        </button>
        {rows.map((r) => (
          <button key={r.id} type="button" onClick={() => setTarget(r.id)} style={{ paddingLeft: 12 + r.depth * 18 + 8 }} className={cn("flex cursor-pointer items-center gap-2.5 rounded-xl py-2.5 pr-3 text-left text-[15px]", target === r.id ? "bg-primary-soft text-primary" : "text-text-primary hover:bg-neutral-50")}>
            <Folder className="size-[18px] shrink-0 fill-amber-300 text-amber-400" aria-hidden />
            <span className="truncate">{r.name}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}

/** 왼쪽 폴더 트리 — 지금 폴더까지의 경로는 펼쳐 두고(직접 접으면 접힌 채로), 누르면 그 폴더를 연다. 끌어다 놓으면 그 폴더로 옮긴다 */
function FolderTree({ tree, current, path, onOpen, dropTarget, dropOver }: { tree: DriveListing["tree"]; current: string | null; path: string[]; onOpen: (id: string | null) => void; dropTarget: (key: string, target: string | null) => DropProps; dropOver: string | null }) {
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const children = (parent: string | null) => tree.filter((f) => (f.parentId ?? null) === parent);
  const row = (active: boolean, over: boolean) =>
    cn("flex h-8 cursor-pointer items-center gap-1.5 rounded-lg pr-2 text-[14px] transition-colors", active ? "bg-primary-soft font-semibold text-primary" : "text-neutral-700 hover:bg-neutral-100", over && "ring-2 ring-primary/40");

  const render = (parent: string | null, depth: number): ReactNode =>
    children(parent).map((f) => {
      const kids = children(f.id).length > 0;
      const isOpen = toggled[f.id] ?? path.includes(f.id);
      const active = current === f.id;
      return (
        <div key={f.id}>
          <div {...dropTarget(`t-${f.id}`, f.id)} onClick={() => onOpen(f.id)} style={{ paddingLeft: 4 + depth * 16 }} className={row(active, dropOver === `t-${f.id}`)}>
            <button
              type="button"
              aria-label={isOpen ? "접기" : "펼치기"}
              onClick={(e) => {
                e.stopPropagation();
                setToggled((t) => ({ ...t, [f.id]: !isOpen }));
              }}
              className={cn("flex size-5 shrink-0 cursor-pointer items-center justify-center rounded text-neutral-400 hover:bg-neutral-200", !kids && "invisible")}
            >
              <ChevronRight className={cn("size-3.5 transition-transform", isOpen && "rotate-90")} aria-hidden />
            </button>
            {active ? <FolderOpen className="size-4 shrink-0 fill-amber-200 text-amber-500" aria-hidden /> : <Folder className="size-4 shrink-0 fill-amber-300 text-amber-400" aria-hidden />}
            <span className="min-w-0 truncate">{f.name}</span>
            {f.access === "private" && <Lock className="size-3 shrink-0 text-neutral-400" aria-label="나만 보기" />}
            {f.access === "members" && <Users className="size-3 shrink-0 text-neutral-400" aria-label="고른 멤버만" />}
          </div>
          {kids && isOpen && render(f.id, depth + 1)}
        </div>
      );
    });

  return (
    <nav aria-label="폴더" className="thin-scrollbar flex w-[240px] shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-neutral-100 bg-white px-3 py-7">
      <div {...dropTarget("t-root", null)} onClick={() => onOpen(null)} className={cn(row(current === null, dropOver === "t-root"), "pl-1")}>
        <HardDrive className="ml-0.5 size-4 shrink-0" aria-hidden />
        <span className="ml-1 min-w-0 truncate">드라이브</span>
      </div>
      {render(null, 1)}
    </nav>
  );
}
