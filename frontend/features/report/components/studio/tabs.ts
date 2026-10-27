import { FolderOpen, ListChecks, Quote, ScrollText, Table2 } from "lucide-react";

/** 오른쪽 패널 탭 — 패널 머리에만 둔다(상단 바는 패널 열기·닫기 토글 하나). '결과' = 이 작업에서 정리한 표·차트·메모 */
export const RIGHT_TABS = [
  { id: "result" as const, label: "결과", icon: Table2 },
  { id: "library" as const, label: "데이터", icon: FolderOpen },
  { id: "viewer" as const, label: "문서 보기", icon: ScrollText },
  { id: "evidence" as const, label: "근거", icon: Quote },
  { id: "numbers" as const, label: "숫자 출처", icon: ListChecks },
];
