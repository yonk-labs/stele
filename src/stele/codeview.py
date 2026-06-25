"""Bounded code reads, slice 0: span + signature outline + expansion handles.

The over-fetch fix (see docs/specs/bounded-code-read-design.md). Slice 0 is
Python-only and dependency-free: given a source file and a requested span (a line
range or a symbol name), return the span verbatim, a signature outline of the
*other* top-level symbols (names and signatures, no bodies), and expansion handles
so the agent keeps agency to escalate. No in-file or cross-file dependency
resolution yet (slices 1-2). Never raises: malformed or unresolvable input
degrades to a head-of-file view.
"""

from __future__ import annotations

import ast

Span = tuple[int, int]
_Def = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def bounded_python(source: str, *, want: Span | str, max_chars: int = 2000) -> str:
    """Return a bounded view of Python ``source`` around ``want``.

    ``want`` is a 1-based inclusive ``(start, end)`` line range or a symbol name.
    """
    lines = source.splitlines()
    n = len(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _fallback(lines, n, max_chars)
    span = _resolve_span(tree, want, n)
    if span is None:
        return _fallback(lines, n, max_chars, note=f"symbol {want!r} not found")
    start, end = span
    span_text = "\n".join(lines[start - 1 : end])
    outline = _outline(tree, covered=(start, end))
    label = want if isinstance(want, str) else f"lines {want[0]}-{want[1]}"
    return _assemble(label, span_text, outline, n, max_chars)


def _resolve_span(tree: ast.Module, want: Span | str, n: int) -> Span | None:
    if isinstance(want, tuple):
        start, end = want
        return (max(1, start), min(n, end))
    for node in ast.walk(tree):
        if isinstance(node, _Def) and node.name == want:
            start = node.lineno
            if node.decorator_list:
                start = min(start, node.decorator_list[0].lineno)
            return (start, node.end_lineno or start)
    return None


def _sig(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{kw} {node.name}({ast.unparse(node.args)}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}" + (f"({bases})" if bases else "")
    return ""


def _outline(tree: ast.Module, *, covered: Span) -> list[str]:
    start, end = covered
    rows: list[str] = []
    for node in tree.body:
        if not isinstance(node, _Def):
            continue
        node_end = node.end_lineno or node.lineno
        if node.lineno >= start and node_end <= end:
            continue  # already shown verbatim in the span
        rows.append(f"L{node.lineno}\t{_sig(node)}")
        if isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    rows.append(f"L{m.lineno}\t    {_sig(m)}")
    return rows


def _assemble(label: str, span_text: str, outline: list[str], n: int, max_chars: int) -> str:
    head = f"# bounded view ({n} lines)\n\n## requested: {label}\n{span_text}"
    handles = (
        "## expand\n- expand a symbol, expand lines A-B, "
        f"or read the full file ({n} lines) without bounds"
    )
    reserved = len(head) + len(handles) + len("## other symbols\n") + 8
    budget = max_chars - reserved
    shown: list[str] = []
    used = 0
    for row in outline:
        if used + len(row) + 1 > budget:
            shown.append(f"(+{len(outline) - len(shown)} more symbols)")
            break
        shown.append(row)
        used += len(row) + 1
    parts = [head]
    if shown:
        parts.append("## other symbols\n" + "\n".join(shown))
    parts.append(handles)
    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[: max_chars - 3].rstrip() + "..."
    return result


def _fallback(lines: list[str], n: int, max_chars: int, note: str | None = None) -> str:
    body_lines: list[str] = []
    used = 0
    for ln in lines:
        if used + len(ln) + 1 > max_chars - 140:
            break
        body_lines.append(ln)
        used += len(ln) + 1
    note_s = f" ({note})" if note else ""
    handles = f"## expand\n- could not bound{note_s}; read the full file ({n} lines) without bounds"
    out = f"# bounded view ({n} lines, head)\n" + "\n".join(body_lines) + "\n\n" + handles
    return out[:max_chars]
