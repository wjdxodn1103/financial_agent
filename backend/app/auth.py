"""로그인 자리 — v1 은 데모 계정 전환(비밀번호 없음, 요청 헤더 `X-User-Id`). 사내 통합 로그인(SSO)으로 바꿀 때 이 파일만 고친다.

역할(높은 순): owner > editor > reviewer > viewer
  viewer   읽기만
  reviewer + 자료 올리기·검수·채널 글·기록 후보 확인(자기 발언)·작업 상태 바꾸기
  editor   + 리포트 만들기·자료 빼기·작업 만들기
  owner    + 멤버·설정·배치 지금 실행
"""
from __future__ import annotations

from typing import Annotated, Dict, List

from fastapi import Depends, Header, HTTPException, Query
from sqlmodel import Session

from app.db import Membership, Repo, SessionDep, User, Workspace, engine

ROLE_RANK: Dict[str, int] = {"viewer": 0, "reviewer": 1, "editor": 2, "owner": 3}
ROLES: List[str] = list(ROLE_RANK)

DEMO_USERS = [
    {"id": "u_kim", "name": "김민준", "title": "팀장"},
    {"id": "u_lee", "name": "이서연", "title": "과장"},
    {"id": "u_park", "name": "박지훈", "title": "대리"},
]


def seed_users() -> None:
    with Session(engine) as s:
        for u in DEMO_USERS:
            if s.get(User, u["id"]) is None:
                s.add(User(**u))
        s.commit()


def current_user(session: SessionDep, x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None, uid: Annotated[str | None, Query()] = None) -> User:
    """헤더가 정본. 링크로 여는 파일(원본 내려받기)은 헤더를 못 실어 `?uid=` 로도 받는다."""
    x_user_id = x_user_id or uid
    if not x_user_id:
        raise HTTPException(401, "로그인이 필요합니다(계정을 고르세요).")
    user = session.get(User, x_user_id)
    if user is None:
        raise HTTPException(401, "모르는 계정입니다. 다시 로그인해 주세요.")
    return user


UserDep = Annotated[User, Depends(current_user)]


def user_view(u: User) -> Dict[str, str]:
    return {"id": u.id, "name": u.name, "title": u.title}


def display_name(u: User | None) -> str:
    if u is None:
        return "에이전트"
    return f"{u.name} {u.title}".strip()


def require_member(session: Session, workspace_id: str, user: User, min_role: str = "viewer") -> tuple[Workspace, Membership]:
    """워크스페이스와 내 멤버십 — 없으면 404(존재를 드러내지 않는다), 역할이 모자라면 403."""
    repo = Repo(session)
    ws = repo.workspace(workspace_id)
    m = repo.membership(workspace_id, user.id) if ws else None
    if ws is None or m is None:
        raise HTTPException(404, "워크스페이스가 없거나 멤버가 아닙니다.")
    if ROLE_RANK.get(m.role, 0) < ROLE_RANK[min_role]:
        raise HTTPException(403, f"이 작업은 {_ROLE_KO[min_role]} 이상 역할이 필요합니다.")
    return ws, m


def can(m: Membership, min_role: str) -> bool:
    return ROLE_RANK.get(m.role, 0) >= ROLE_RANK[min_role]


_ROLE_KO = {"viewer": "열람자", "reviewer": "검토자", "editor": "편집자", "owner": "소유자"}
ROLE_KO = _ROLE_KO
