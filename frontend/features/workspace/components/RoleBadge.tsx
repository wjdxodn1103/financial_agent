import { cn } from "@/lib/utils";
import type { Role } from "../../report/types";

const LABEL: Record<Role, string> = { owner: "소유자", editor: "편집자", reviewer: "검토자", viewer: "열람자" };
const TONE: Record<Role, string> = {
  owner: "bg-primary text-white",
  editor: "bg-primary-soft text-primary-soft-foreground",
  reviewer: "bg-amber-50 text-amber-800",
  viewer: "bg-neutral-100 text-text-secondary",
};

export function roleLabel(role: Role): string {
  return LABEL[role] ?? role;
}

export function RoleBadge({ role, className }: { role: Role; className?: string }) {
  return <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium", TONE[role], className)}>{LABEL[role] ?? role}</span>;
}
