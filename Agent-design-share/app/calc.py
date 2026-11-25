"""Arithmetic is done by the program, not the model.

The evaluator (an LLM) judged a correct answer wrong because it could not keep its own arithmetic straight
(ITERATION_LOG.md). So every "expression = result" in the learner's answer is computed here, and the results are
given to the evaluator as facts. Its job is limited to judging the method (formula, scope, reasoning). Numbers
the evaluator writes in its own feedback are checked here too.
"""

import ast
import operator
import re

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_TRANS = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "（": "(", "）": ")", "＋": "+", "＝": "=", "^": "**"})
_NUM = r"\d+(?:\.\d+)?(?:\s?(?:%|万|亿))?"
# an expression: numbers joined by at least one operator, optionally parenthesised
_EXPR = rf"[(（]*\s*{_NUM}(?:\s*[)）]*\s*[×÷*/+\-−–＋^]\s*[(（]*\s*{_NUM})+\s*[)）]*"
_SEG = rf"(?:{_EXPR}|[-−]?{_NUM})"
_MARK = r"(?:=|＝|≈|约等于|约为|约|等于|得到|得)"
# a chain "a = b = c": a number or expression must not be cut out of a longer one (Chinese text may touch it)
_PAT = re.compile(rf"(?<![A-Za-z0-9_.×÷*/+\-−–＋^(（]){_SEG}(?:\s*{_MARK}\s*{_SEG})+")
_SPLIT = re.compile(rf"\s*({_MARK})\s*")
_OPCHAR = re.compile(r"\d\s*(?:%|万|亿)?\s*[)）]*\s*[×÷*/+\-−–＋^]")


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported")


_SCALE = {"%": 0.01, "万": 1e4, "亿": 1e8}


def _num(s: str) -> float:
    s = s.replace(" ", "").replace("−", "-")
    return float(s[:-1]) * _SCALE[s[-1]] if s[-1] in _SCALE else float(s)


def evaluate(expr: str) -> float:
    """Safe arithmetic: + - * / ** and parentheses only; 12% means 0.12, 3万 means 30000."""
    if "÷" in expr and "/" in expr:  # "3000/8500÷20/110": "/" is a fraction bar, so each fraction binds first
        expr = re.sub(rf"({_NUM})\s*/\s*({_NUM})", r"(\1/\2)", expr)
    e = re.sub(rf"({_NUM})", lambda m: repr(_num(m.group(1))), expr.translate(_TRANS))
    return _eval(ast.parse(e, mode="eval").body)


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def check(text: str) -> list[dict]:
    """Every "expression = result" in `text` (also chains "a = b = c"), recomputed and compared with the last,
    written result. "=" must match after rounding to the digits written; "约" / "≈" also allows 5%."""
    out = []
    for m in _PAT.finditer(text):
        parts = _SPLIT.split(m.group(0).strip())
        segs, marks = parts[::2], parts[1::2]
        claimed = segs[-1].replace(" ", "")
        if _OPCHAR.search(claimed):
            continue  # no plain number at the end: nothing written to compare with
        want = _num(claimed)
        unit = claimed[-1] if claimed[-1] in _SCALE else ""
        digits = claimed[:-1] if unit else claimed
        tol = 0.5 * 10 ** -(len(digits.split(".")[1]) if "." in digits else 0) * (_SCALE[unit] if unit else 1)
        if marks[-1] in ("≈", "约等于", "约为", "约"):
            tol = max(tol, 0.05 * abs(want))
        close = lambda v: abs(v - want) <= tol + 1e-12  # noqa: E731
        for expr in segs[:-1]:
            if not _OPCHAR.search(expr):
                continue
            try:
                value = evaluate(expr)
            except (ValueError, SyntaxError, ZeroDivisionError, OverflowError):
                continue
            if unit in ("万", "亿") and not re.search("[万亿]", expr):
                # "100×(1+8%)^3=125.97万" writes the unit only on the result, "120×7000=84万" does not: accept
                # either, and report the reading closer to what was written
                scaled = value * _SCALE[unit]
                if close(scaled) or (not close(value) and abs(scaled - want) < abs(value - want)):
                    value = scaled
            out.append({"text": f"{expr}={claimed}", "expr": expr, "claimed": claimed,
                        "value": _fmt(value / _SCALE[unit]) + unit if unit else _fmt(value), "ok": close(value)})
    return out


def as_prompt(checks: list[dict]) -> str:
    return "\n".join(f"- {c['expr']} = {c['value']}；回答中写的是「{c['claimed']}」→ "
                     f"{'一致' if c['ok'] else '不一致，算错了'}" for c in checks)
