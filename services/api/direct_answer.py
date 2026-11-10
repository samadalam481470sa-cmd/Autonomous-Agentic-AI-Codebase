"""Deterministic answers for simple arithmetic questions.

Small factual questions should not depend on a model's instruction following.
This module only accepts expressions made entirely of numbers and arithmetic
operators; anything ambiguous falls through to the normal assistant.
"""
from __future__ import annotations

import ast
import operator
import re

_MAX_EXPRESSION = 200
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_PREFIX = re.compile(
    r"^(?:what(?:'s|s| is| are)|how much is|calculate|compute|solve|evaluate)\s+",
    re.I,
)
_MATH_ONLY = re.compile(r"[0-9+\-*/%(). ]+\Z")
_OPERATORS = (
    (re.compile(r"\b(?:plus|added to|add)\b", re.I), "+"),
    (re.compile(r"\b(?:minus|subtract(?:ed)?(?: from)?)\b", re.I), "-"),
    (re.compile(r"\b(?:times|multiplied by)\b", re.I), "*"),
    (re.compile(r"\b(?:divided by|over)\b", re.I), "/"),
)
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def _number_words(text: str) -> str:
    def compound(match: re.Match) -> str:
        value = _TENS[match.group(1).lower()]
        if match.group(2):
            value += _NUMBER_WORDS[match.group(2).lower()]
        return str(value)

    text = re.sub(
        r"\b(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
        r"(?:[-\s]+(one|two|three|four|five|six|seven|eight|nine))?\b",
        compound,
        text,
        flags=re.I,
    )
    return re.sub(
        r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen)\b",
        lambda match: str(_NUMBER_WORDS[match.group(0).lower()]),
        text,
        flags=re.I,
    )


def _evaluate(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool) or abs(node.value) > 10**12:
            raise ValueError("unsupported number")
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ZeroDivisionError
        return _BINARY[type(node.op)](left, right)
    raise ValueError("unsupported expression")


def _format(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return format(value, ".12g")


def answer_directly(message: str) -> str | None:
    """Return an exact answer for an unambiguous arithmetic expression."""
    text = _PREFIX.sub("", message.strip(), count=1).strip()
    text = re.sub(r"[?.!]+$", "", text).strip()
    text = re.sub(r"=+$", "", text).strip()
    text = text.replace(",", "").replace("^", "**")
    text = _number_words(text)
    for pattern, replacement in _OPERATORS:
        text = pattern.sub(f" {replacement} ", text)
    text = re.sub(r"\bx\b", "*", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) > _MAX_EXPRESSION or not _MATH_ONLY.fullmatch(text):
        return None
    try:
        tree = ast.parse(text, mode="eval")
        if not any(isinstance(node, ast.BinOp) for node in ast.walk(tree)):
            return None
        value = _evaluate(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        if text and re.search(r"/\s*0(?:\D|$)|%\s*0(?:\D|$)", text):
            return "That expression is undefined because division by zero is not allowed."
        return None

    display = re.sub(r"\s*([+\-*/%])\s*", r" \1 ", text)
    display = re.sub(r"\s+", " ", display).strip()
    return f"{display} = {_format(value)}"
