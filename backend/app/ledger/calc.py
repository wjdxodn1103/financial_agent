"""계산 — 파생 수치(증감률·비율·배수)는 코드가 계산하고 계산식을 남긴다. LLM 은 식만 고르고 값을 지어내지 않는다.

식 문법: 숫자, + - * / ( ), 원장 참조 F1·F2…(호출자가 넘긴 refs), 함수 growth(새, 옛)=(새/옛-1)×100, ratio(분자, 분모)=분자/분모×100,
cagr(끝, 시작, 햇수)=((끝/시작)^(1/햇수)-1)×100, diff(a, b)=a-b. 파이썬 ast 로 허용한 노드만 평가한다(eval 금지).
값은 원장의 abs(배율 적용 값) — 금액 비율은 단위가 상쇄되고, 금액 차이는 원 단위로 나온다.
"""
from __future__ import annotations

import ast
import math
from typing import Any, Callable, Dict, List

FUNCS: Dict[str, Callable[..., float]] = {
    "growth": lambda new, old: (new / old - 1.0) * 100.0,
    "ratio": lambda num, den: num / den * 100.0,
    "cagr": lambda end, start, years: ((end / start) ** (1.0 / years) - 1.0) * 100.0,
    "diff": lambda a, b: a - b,
}
FUNC_KO = {"growth": "증감률", "ratio": "비율", "cagr": "연평균 성장률", "diff": "차이"}
_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


class CalcError(ValueError):
    pass


def evaluate(expr: str, refs: Dict[str, float]) -> float:
    """refs = {"F1": 3150e8, …}. 허용하지 않은 식·없는 참조·0 나누기는 CalcError."""
    try:
        tree = ast.parse((expr or "").strip(), mode="eval")
    except SyntaxError as e:
        raise CalcError(f"식을 읽지 못했습니다: {expr}") from e

    def ev(n: ast.AST) -> float:
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id not in refs:
                raise CalcError(f"원장에 없는 참조입니다: {n.id}")
            return float(refs[n.id])
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Div) and b == 0:
                raise CalcError("0 으로 나눌 수 없습니다.")
            return _OPS[type(n.op)](a, b)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS and not n.keywords:
            args = [ev(a) for a in n.args]
            try:
                return float(FUNCS[n.func.id](*args))
            except (ZeroDivisionError, TypeError, ValueError) as e:
                raise CalcError(f"{n.func.id} 를 계산하지 못했습니다: {e}") from e
        raise CalcError(f"허용하지 않는 식입니다: {ast.unparse(n) if hasattr(ast, 'unparse') else type(n).__name__}")

    v = ev(tree)
    if math.isnan(v) or math.isinf(v):
        raise CalcError("계산 결과가 숫자가 아닙니다.")
    return v


def refs_in(expr: str) -> List[str]:
    try:
        tree = ast.parse((expr or "").strip(), mode="eval")
    except SyntaxError:
        return []
    return list(dict.fromkeys(n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in FUNCS))


def readable(expr: str, names: Dict[str, str]) -> str:
    """'growth(F2, F1)' → '증감률(매출액 2024, 매출액 2023)' — 화면·엑셀 주석용."""
    out = expr
    for ref in sorted(names, key=len, reverse=True):
        out = out.replace(ref, names[ref])
    for f, ko in FUNC_KO.items():
        out = out.replace(f"{f}(", f"{ko}(")
    return out


def excel_formula(expr: str, cells: Dict[str, str]) -> str:
    """같은 식을 엑셀 수식으로 — 운용역이 열어서 직접 검증할 수 있게(growth → (a/b-1)*100 등)."""
    try:
        tree = ast.parse((expr or "").strip(), mode="eval")
    except SyntaxError:
        return ""

    def fx(n: ast.AST) -> str:
        if isinstance(n, ast.Expression):
            return fx(n.body)
        if isinstance(n, ast.Constant):
            return repr(n.value)
        if isinstance(n, ast.Name):
            return cells.get(n.id, "0")
        if isinstance(n, ast.UnaryOp):
            return f"-({fx(n.operand)})" if isinstance(n.op, ast.USub) else fx(n.operand)
        if isinstance(n, ast.BinOp):
            op = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}.get(type(n.op), "+")
            return f"({fx(n.left)}{op}{fx(n.right)})"
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            a = [fx(x) for x in n.args]
            name = n.func.id
            if name == "growth" and len(a) == 2:
                return f"(({a[0]}/{a[1]})-1)*100"
            if name == "ratio" and len(a) == 2:
                return f"({a[0]}/{a[1]})*100"
            if name == "cagr" and len(a) == 3:
                return f"((({a[0]}/{a[1]})^(1/{a[2]}))-1)*100"
            if name == "diff" and len(a) == 2:
                return f"({a[0]}-{a[1]})"
        return "0"

    return "=" + fx(tree)


__all__: List[Any] = ["CalcError", "FUNCS", "evaluate", "excel_formula", "readable", "refs_in"]
