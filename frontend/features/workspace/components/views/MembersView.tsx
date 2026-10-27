"use client";

/** 멤버·설정 — 역할(소유자·편집자·검토자·열람자), 초대, 퇴근 시각(기록 비서 배치). 바꾸기는 소유자만. */
import { useState } from "react";
import { Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError } from "../../../report/api";
import type { Role } from "../../../report/types";
import { inviteMember, patchWorkspace, removeMember, setMemberRole } from "../../api";
import { useWorkspace } from "../../context";
import { FEATURES } from "../../features";
import type { WorkspaceDetail } from "../../types";
import { RoleBadge } from "../RoleBadge";
import { PageHeader } from "./PageHeader";

export function MembersView() {
  const ws = useWorkspace();
  const detail = ws.detail!;
  const owner = ws.can("owner");
  const roles = ws.meta.roles;
  const outsiders = detail.users.filter((u) => !detail.members.some((m) => m.user.id === u.id));
  const [picked, setInvitee] = useState("");
  // 초대한 사람은 후보에서 빠진다 — 고른 값이 후보에 없으면 첫 후보
  const invitee = outsiders.some((u) => u.id === picked) ? picked : (outsiders[0]?.id ?? "");
  const [inviteRole, setInviteRole] = useState<Role>("editor");
  const [offHour, setOffHour] = useState(detail.workspace.settings.offHour);

  const run = async (fn: () => Promise<WorkspaceDetail>, fail: string) => {
    try {
      ws.setDetail(await fn());
    } catch (e) {
      toast.error(e instanceof ApiError && e.status < 500 ? e.message : fail, { position: "top-center" });
    }
  };

  return (
    <div className="thin-scrollbar min-h-0 flex-1 overflow-y-auto">
      <PageHeader title="멤버·설정" />
      <div className="mx-auto max-w-[960px] px-6 pb-10">
        <div className="overflow-hidden rounded-xl border border-neutral-200">
          {detail.members.map((m) => (
            <div key={m.user.id} className="flex items-center gap-3 border-b border-neutral-100 px-4 py-3 last:border-b-0">
              <span className="min-w-0 flex-1">
                <span className="block text-sm text-text-primary">
                  {m.user.name} {m.user.title}
                  {m.user.id === ws.me.id && <span className="ml-1 text-xs text-text-secondary">(나)</span>}
                </span>
              </span>
              {owner ? (
                <select
                  aria-label={`${m.user.name} 역할`}
                  value={m.role}
                  onChange={(e) => void run(() => setMemberRole(ws.workspaceId, m.user.id, e.target.value as Role), "역할을 바꾸지 못했습니다.")}
                  className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-xs"
                >
                  {roles.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.label}
                    </option>
                  ))}
                </select>
              ) : (
                <RoleBadge role={m.role} />
              )}
              {owner && m.user.id !== ws.me.id && (
                <button
                  type="button"
                  title="멤버에서 빼기"
                  aria-label="멤버에서 빼기"
                  onClick={() => window.confirm(`${m.user.name}님을 멤버에서 뺄까요?`) && void run(() => removeMember(ws.workspaceId, m.user.id), "빼지 못했습니다.")}
                  className="cursor-pointer rounded p-1 text-text-secondary hover:text-red-600"
                >
                  <Trash2 className="size-4" aria-hidden />
                </button>
              )}
            </div>
          ))}
        </div>

        {owner && outsiders.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-neutral-300 px-4 py-3">
            <UserPlus className="size-4 text-primary" aria-hidden />
            <span className="text-sm text-text-primary">초대</span>
            <select aria-label="초대할 사람" value={invitee} onChange={(e) => setInvitee(e.target.value)} className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm">
              {outsiders.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} {u.title}
                </option>
              ))}
            </select>
            <select aria-label="역할" value={inviteRole} onChange={(e) => setInviteRole(e.target.value as Role)} className="rounded-md border border-neutral-200 bg-white px-2 py-1 text-sm">
              {roles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
            <Button size="sm" disabled={!invitee} onClick={() => void run(() => inviteMember(ws.workspaceId, invitee, inviteRole), "초대하지 못했습니다.")}>
              초대하기
            </Button>
          </div>
        )}

        {FEATURES.records && (
        <>
        <h2 className="mt-8 text-sm font-semibold text-text-primary">기록 비서</h2>
        <div className="mt-2 rounded-xl border border-neutral-200 px-4 py-3">
          <div className="flex items-center gap-2">
            <label htmlFor="off-hour" className="text-sm text-text-primary">
              퇴근 시각
            </label>
            <input id="off-hour" type="time" disabled={!owner} value={offHour} onChange={(e) => setOffHour(e.target.value)} className="rounded-md border border-neutral-200 px-2 py-1 text-sm disabled:bg-background-gray" />
            {owner && offHour !== detail.workspace.settings.offHour && (
              <Button size="sm" onClick={() => void run(() => patchWorkspace(ws.workspaceId, { settings: { offHour } }), "저장하지 못했습니다.")}>
                저장
              </Button>
            )}
          </div>
        </div>
        </>
        )}
      </div>
    </div>
  );
}
