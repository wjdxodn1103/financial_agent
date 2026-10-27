"use client";

/** 데모 로그인 — 계정을 골라 들어간다(비밀번호 없음). 실제 도입 때는 사내 통합 로그인으로 바뀐다. */
import { UserRound } from "lucide-react";

import type { UserInfo } from "../../report/types";
import { Brand } from "./Brand";

export function Login({ users, onPick }: { users: UserInfo[]; onPick: (id: string) => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <div className="w-full max-w-[420px] rounded-3xl bg-white p-8 shadow-[0_8px_30px_rgba(0,27,55,0.06)]">
        <Brand />
        <h1 className="mt-6 text-[22px] font-bold tracking-tight text-text-primary">계정 선택</h1>
        <div className="mt-6 flex flex-col gap-1">
          {users.map((u) => (
            <button
              key={u.id}
              type="button"
              onClick={() => onPick(u.id)}
              className="flex cursor-pointer items-center gap-3 rounded-2xl px-3 py-3 text-left transition-colors hover:bg-neutral-50"
            >
              <span className="flex size-11 items-center justify-center rounded-full bg-primary-soft text-primary">
                <UserRound className="size-5" aria-hidden />
              </span>
              <span>
                <span className="block text-[16px] font-semibold text-text-primary">{u.name}</span>
                <span className="block text-[13px] text-text-secondary">{u.title}</span>
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
