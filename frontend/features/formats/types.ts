/** 문서 양식 메뉴 — BE app/templates_import/registry.py (format_views·create_format·update_format) · analyze.py(샘플 분석 제안) */

/** 섹션 뒤 자리 — 설명 자리(표·차트 이름과 구성 한 줄, 샘플 분석·화면에서 더함), 옛 표 양식 자리(templateId), builtin = 기본 양식의 고정 블록(이름만) */
export interface FormatSlot {
  kind: "table" | "chart" | "figure";
  title: string;
  desc?: string;
  position?: "main" | "sidebar";
  templateId?: string;
  rows?: string[];
  builtin?: boolean;
}

export interface FormatSection {
  /** 저장한 섹션 id(s1·s2…) — 새 섹션은 없음(서버가 붙인다) */
  id?: string;
  title: string;
  level: number;
  guide: string;
  slots: FormatSlot[];
}

export type FormatScope = "builtin" | "company" | "workspace" | "user";

/** 표·차트 양식(에셋) — 샘플에서 뽑은 형식만(구성 + 겉모양 + 샘플 속 위치). 섹션에 묶지 않는 양식 전체의 모음. BE templates_import/forms.py */
export interface FormatAsset {
  id: string;
  kind: "table" | "chart";
  name: string;
  desc: string;
  /** 샘플에서 있던 섹션(참고만) */
  sectionId: string | null;
  position: "main" | "sidebar";
  /** 원본 위치 — box 가 있으면 그 부분만 잘라 보인다. caption = 샘플 제목 그대로 */
  source: { page: number | null; box: [number, number, number, number] | null; caption: string };
  caption: { label: string; numbered: boolean };
  sourceLine: boolean;
  note: boolean;
  table?: { stub: string; rowKind: string; rows: number; groups: { label: string; unit: string; columns: string[] }[] };
  chart?: {
    type: "line" | "bar" | "barh" | "area" | "pie" | "combo" | "band" | "other";
    x: "date" | "period" | "category";
    series: { name: string; type: "line" | "bar" | "area"; axis: "left" | "right" }[];
    unit: string;
    unit2: string;
    legend: "top" | "bottom" | "right" | "none";
  };
  look: { headerFill?: string; headerText?: string; rule?: string; lines?: "horizontal" | "grid" | "none"; numberAlign?: "right" | "center" | "left"; colors?: string[]; grid?: boolean; labels?: boolean; captionBold?: boolean; captionColor?: string };
}

export interface DocFormat {
  id: string;
  title: string;
  desc: string;
  kind: "type" | "format" | "registered";
  scope: FormatScope;
  owner: string;
  ownerId: string;
  /** 고치기·지우기 — 만든 사람이나 관리자(워크스페이스 소유자)만 */
  editable: boolean;
  /** 등록 전(샘플 분석이 끝난 직후) — 만든 사람에게만 보이고, 등록해야 다른 사람·새 문서에 보인다 */
  draft?: boolean;
  /** 예시 문서 파일 이름(등록 양식) 또는 설명(기본 양식) */
  sample: string;
  hasSample?: boolean;
  /** 문체·형식 안내(작성기가 따른다) */
  style?: string;
  sections: FormatSection[];
  /** 표·차트 양식(샘플로 만든 양식) */
  assets?: FormatAsset[];
  updatedAt: string;
  /** 이 양식으로 쓴 문서 수(사내 = 전체, 워크스페이스 = 이 워크스페이스) */
  uses?: number;
  /** 내가 마지막으로 이 양식으로 쓴 때 */
  lastUsed?: string | null;
}

export interface FormatImportState {
  id: string;
  name: string;
  status: "analyzing" | "ready" | "error";
  progress?: { done: number; total: number };
  /** 분석이 끝나면 만든 '등록 전' 양식 id — 양식 화면으로 연다 */
  formatId?: string | null;
  error?: string | null;
}
