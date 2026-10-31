/** 경제 일정 REST — BE api/calendar_routes.py. 알림 메시지는 서버 코드가 양식으로 만든다(AI 없음). */
import { jsonInit, req } from "../report/api";

const wid = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

export interface MarketEventView {
  id: string;
  key: string;
  country: string;
  countryKo: string;
  category: "release" | "meeting" | "issue" | "industry" | "earnings" | "holiday";
  categoryKo: string;
  importance: number;
  indicatorId: string | null;
  title: string;
  short: string;
  agency: string;
  period: string;
  at: string;
  /** 한국 날짜·시각(표시 기준) */
  date: string;
  kstTime: string;
  /** 현지 시각(미국·유럽) */
  localTime: string;
  unit: string;
  decimals: number;
  previous: number | null;
  forecast: number | null;
  actual: number | null;
  actualText: string;
  status: "scheduled" | "released";
  releasedAt: string | null;
  confirmed: boolean;
  note: string;
  sourceUrl: string;
  source: string;
  detect: { via?: string; url?: string; obs?: string; lagSec?: number; backfill?: boolean };
  detectable: boolean;
  alerted: boolean;
}

export interface KeyStatus {
  fred: boolean;
  bls: boolean;
  ecos: boolean;
  blsLeft: number;
  webhook: boolean;
}

export interface EventAlertView {
  id: string;
  eventId: string | null;
  indicatorId: string | null;
  repeat: boolean;
  title: string;
  event: MarketEventView | null;
  all: boolean;
  channels: { inbox?: boolean; workspace?: boolean; webhook?: boolean };
  enabled: boolean;
  userId: string;
  lastSentAt: string | null;
  createdAt: string;
}

export interface CalendarMeta {
  countries: Record<string, string>;
  categories: Record<string, string>;
  indicators: { id: string; name: string; short: string; country: string; importance: number }[];
  keys: KeyStatus;
  isAdmin: boolean;
}

export const getCalendar = (w: string, p: { start: string; end: string; country?: string; category?: string; minImportance?: number }) => {
  const q = new URLSearchParams({ start: p.start, end: p.end, country: p.country ?? "", category: p.category ?? "", minImportance: String(p.minImportance ?? 1) });
  return req<{ events: MarketEventView[]; keys: KeyStatus }>(`${wid(w)}/calendar?${q}`);
};
export const getCalendarMeta = () => req<CalendarMeta>("/api/calendar/meta");
export const setForecast = (w: string, id: string, forecast: number | null) => req<MarketEventView>(`${wid(w)}/calendar/events/${encodeURIComponent(id)}`, jsonInit("PATCH", { forecast }));
export const listEventAlerts = async (w: string) => (await req<{ alerts: EventAlertView[] }>(`${wid(w)}/calendar/alerts`)).alerts ?? [];
export const createEventAlerts = async (
  w: string,
  body: { eventIds?: string[]; indicatorIds?: string[]; repeat?: boolean; all?: boolean; workspace?: boolean; webhook?: boolean; source?: Record<string, unknown> },
) => (await req<{ alerts: EventAlertView[] }>(`${wid(w)}/calendar/alerts`, jsonInit("POST", body))).alerts ?? [];
export const deleteEventAlert = (id: string) => req<{ ok: boolean }>(`/api/calendar/alerts/${encodeURIComponent(id)}`, { method: "DELETE" });
export const syncCalendar = () => req<{ added: number; updated: number; errors: string[]; previousFilled: number; pastFilled: number }>("/api/admin/calendar/sync", jsonInit("POST", {}));
export const putActual = (id: string, value: number, text = "") => req<MarketEventView>(`/api/admin/calendar/events/${encodeURIComponent(id)}/actual`, jsonInit("POST", { value, text }));

/** 값 표기 — 지표의 소수 자리·단위 그대로(% 는 붙여, 천 명·천 건은 띄워) */
export function fmtValue(v: number | null | undefined, e: Pick<MarketEventView, "unit" | "decimals">): string {
  if (v == null) return "—";
  const d = Math.max(0, e.decimals ?? 1);
  const n = v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
  return e.unit === "%" ? `${n}%` : e.unit ? `${n} ${e.unit}` : n;
}
