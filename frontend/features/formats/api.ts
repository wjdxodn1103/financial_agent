/** 문서 양식 메뉴 API — BE app/api/import_routes.py */
import { API_BASE } from "../report/constants";
import { jsonInit, req } from "../report/api";
import type { TemplateScope } from "../research/types";
import { getUserId } from "../workspace/auth";
import type { DocFormat, FormatImportState, FormatSection } from "./types";

/** 에셋 고치기 — 이름·설명·빼기·순서와 차트 종류(VL 오독 바로잡기)만. 구성·겉모양·위치는 서버에 저장된 것 */
type AssetEdit = { id: string; name: string; desc: string; chartType?: string };

const wid = (w: string) => `/api/workspaces/${encodeURIComponent(w)}`;

export const listFormats = async (w: string) => (await req<{ formats: DocFormat[] }>(`${wid(w)}/formats`)).formats;
/** from = 복사할 양식 id(기본·등록), 없으면 빈 섹션 하나짜리 */
export const createFormat = (w: string, body: { name?: string; scope?: TemplateScope; from?: string }) => req<DocFormat>(`${wid(w)}/formats`, jsonInit("POST", body));
export const patchFormat = (w: string, id: string, body: { name?: string; desc?: string; style?: string; sections?: FormatSection[]; assets?: AssetEdit[]; scope?: TemplateScope }) =>
  req<DocFormat>(`${wid(w)}/formats/${encodeURIComponent(id)}`, jsonInit("PATCH", body));
/** 예시 문서 — 브라우저에서 바로 연다(PDF 는 창 안에) */
export const formatSampleUrl = (w: string, id: string) => `${API_BASE}${wid(w)}/formats/${encodeURIComponent(id)}/sample?uid=${encodeURIComponent(getUserId() ?? "")}`;
/** 표·차트 양식이 샘플(PDF)에서 있던 부분만 잘라 낸 그림 */
export const formatAssetImageUrl = (w: string, id: string, assetId: string) => `${API_BASE}${wid(w)}/formats/${encodeURIComponent(id)}/assets/${encodeURIComponent(assetId)}/image?uid=${encodeURIComponent(getUserId() ?? "")}`;

/** 새 양식 — 샘플(PDF·DOCX)을 올리면 뒤에서 LLM 이 분석하고 끝나면 '등록 전' 양식을 만든다(7쪽에 약 5분). 상태는 getFormatImport 로 다시 묻는다 */
export const uploadFormatSample = (w: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return req<FormatImportState>(`${wid(w)}/format-imports`, { method: "POST", body: fd });
};
export const getFormatImport = (w: string, id: string) => req<FormatImportState>(`${wid(w)}/format-imports/${encodeURIComponent(id)}`);
/** 등록 전 양식을 등록 — 이제 다른 사람·새 문서에 보인다 */
export const registerFormat = (w: string, id: string, scope: TemplateScope) => req<DocFormat>(`${wid(w)}/formats/${encodeURIComponent(id)}/register`, jsonInit("POST", { scope }));
/** 말로 고치기 — AI 가 양식을 고쳐 저장하고 고친 양식과 한 줄 요약을 돌려준다 */
export const reviseFormat = (w: string, id: string, instruction: string) => req<{ format: DocFormat; summary: string }>(`${wid(w)}/formats/${encodeURIComponent(id)}/revise`, jsonInit("POST", { instruction }));
