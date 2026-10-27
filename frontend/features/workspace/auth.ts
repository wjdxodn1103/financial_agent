/**
 * 로그인 자리 — v1 은 데모 계정 전환(비밀번호 없음). 고른 계정 id 를 브라우저에 두고 모든 요청에 `X-User-Id` 로 싣는다.
 * 사내 통합 로그인(SSO)으로 바꿀 때 이 파일과 BE app/auth.py 만 고친다.
 */
const KEY = "evidesk.user";
let current: string | null | undefined;

export function getUserId(): string | null {
  if (current === undefined) {
    try {
      current = localStorage.getItem(KEY);
    } catch {
      current = null;
    }
  }
  return current ?? null;
}

export function setUserId(id: string | null): void {
  current = id;
  try {
    if (id) localStorage.setItem(KEY, id);
    else localStorage.removeItem(KEY);
  } catch {
    /* 저장소를 못 써도 이 탭에서는 동작한다 */
  }
}

export function authHeaders(): Record<string, string> {
  const id = getUserId();
  return id ? { "X-User-Id": id } : {};
}
