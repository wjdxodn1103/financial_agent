"use client";

/** 내 워크스페이스 목록 + 새로 만들기. 워크스페이스 하나 = 작업 하나(투자 검토·정기 점검·규정 검토·자유). */
import { useEffect, useState } from "react";
import { FolderKanban, LogOut, Plus, Users } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Meta, UserInfo } from "../../report/types";
import { createWorkspace, listWorkspaces } from "../api";
import type { WorkspaceListItem } from "../types";
import { Brand } from "./Brand";
import { RoleBadge } from "./RoleBadge";

export function WorkspaceHome({ me, meta, onOpen, onLogout }: { me: UserInfo; meta: Meta; onOpen: (id: string) => void; onLogout: () => void }) {
  const [items, setItems] = useState<WorkspaceListItem[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("deal");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listWorkspaces()
      .then((x) => !cancelled && setItems(x))
      .catch(() => !cancelled && setItems([]));
    return () => {
      cancelled = true;
    };
  }, [me.id]);

  const kindTitle = (id: string) => meta.workspaceKinds.find((k) => k.id === id)?.title ?? id;

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const d = await createWorkspace({ name: name.trim(), kind, description: description.trim() });
      onOpen(d.workspace.id);
    } catch {
      toast.error("워크스페이스를 만들지 못했습니다.", { position: "top-center" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-white">
      <header className="flex h-14 items-center justify-between border-b border-neutral-200 bg-white px-6">
        <Brand />
        <div className="flex items-center gap-3 text-sm">
          <span className="text-text-secondary">
            {me.name} {me.title}
          </span>
          <button type="button" onClick={onLogout} className="flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-xs text-text-secondary hover:bg-neutral-100 hover:text-text-primary">
            <LogOut className="size-3.5" aria-hidden />
            계정 바꾸기
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-[960px] px-8 py-10">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h1 className="text-[26px] leading-tight font-bold tracking-tight text-text-primary">워크스페이스</h1>
          </div>
          {!creating && (
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden />새 워크스페이스
            </Button>
          )}
        </div>

        {creating && (
          <div className="mt-6 rounded-2xl bg-neutral-50 p-6">
            <label className="block text-xs font-medium text-text-secondary" htmlFor="ws-name">
              이름
            </label>
            <input
              id="ws-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void submit()}
              placeholder="예: A사 투자 검토"
              className="mt-1.5 w-full rounded-xl border border-neutral-200 bg-white px-3.5 py-2.5 text-[15px] outline-none focus:border-primary"
            />
            <p className="mt-5 text-xs font-medium text-text-secondary">유형</p>
            <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {meta.workspaceKinds.map((k) => (
                <button
                  key={k.id}
                  type="button"
                  onClick={() => setKind(k.id)}
                  className={cn("cursor-pointer rounded-xl border-2 bg-white px-4 py-3 text-left transition-colors", kind === k.id ? "border-primary" : "border-transparent hover:border-neutral-200")}
                >
                  <span className="block text-[15px] font-semibold text-text-primary">{k.title}</span>
                  <span className="block text-xs text-text-secondary">{k.desc}</span>
                </button>
              ))}
            </div>
            <label className="mt-4 block text-xs font-medium text-text-secondary" htmlFor="ws-desc">
              설명(선택)
            </label>
            <input
              id="ws-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="무엇을 하는 공간인지 한 줄로"
              className="mt-1.5 w-full rounded-xl border border-neutral-200 bg-white px-3.5 py-2.5 text-[15px] outline-none focus:border-primary"
            />
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setCreating(false)}>
                취소
              </Button>
              <Button disabled={!name.trim() || busy} onClick={() => void submit()}>
                만들기
              </Button>
            </div>
          </div>
        )}

        <div className="mt-7 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {items === null && <p className="text-sm text-text-secondary">불러오는 중…</p>}
          {items?.length === 0 && !creating && <p className="text-sm text-text-secondary">아직 참여한 워크스페이스가 없습니다.</p>}
          {items?.map((w) => (
            <button key={w.id} type="button" onClick={() => onOpen(w.id)} className="cursor-pointer rounded-2xl bg-neutral-50 p-5 text-left transition-colors hover:bg-neutral-100">
              <div className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-white text-[16px] font-bold text-primary ring-1 ring-neutral-200">{w.name.slice(0, 1)}</span>
                  <span className="min-w-0">
                    <span className="block truncate text-[16px] font-bold tracking-tight text-text-primary">{w.name}</span>
                    <span className="block text-[12px] text-text-secondary">{kindTitle(w.kind)}</span>
                  </span>
                </span>
                <RoleBadge role={w.role} />
              </div>
              {w.description && <p className="mt-3 line-clamp-2 text-[13px] text-text-secondary">{w.description}</p>}
              <p className="mt-3 flex items-center gap-2 text-[12px] text-text-secondary">
                <FolderKanban className="size-3.5" aria-hidden />
                <span>자료 {w.documentCount}</span>
                <span>·</span>
                <span className="inline-flex items-center gap-0.5">
                  <Users className="size-3" aria-hidden />
                  {w.members}
                </span>
              </p>
            </button>
          ))}
        </div>
      </main>
    </div>
  );
}
