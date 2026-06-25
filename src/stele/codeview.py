"""Bounded code reads, slices 0-1: span + in-file deps + outline + handles.

The over-fetch fix (see docs/specs/bounded-code-read-design.md). Given Python
source and a requested span (a line range or symbol name), returns:

  1. the requested span, verbatim;
  2. resolved in-file dependencies (the module-level defs/assignments the span
     references, included with their bodies) -- the load-bearing leg the
     falsification proved mandatory (a span without its referenced defs breaks
     the task);
  3. a signature outline of the *remaining* top-level symbols (no bodies);
  4. expansion handles so the agent keeps agency to escalate.

Python-only, dependency-free (stdlib ``ast``), one level of resolution. Cross-file
resolution (the graph path) is slice 2; recursion and multi-language are later.
Never raises: malformed or unresolvable input degrades to a head-of-file view.
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
    defs = _module_defs(tree)
    referenced = _referenced_names(tree, span)
    deps = _resolve_deps(defs, referenced, span)
    dep_names = {name for name, _ in deps}
    outline = _outline(tree, span, dep_names)
    label = want if isinstance(want, str) else f"lines {want[0]}-{want[1]}"
    return _assemble(label, span_text, lines, deps, outline, n, max_chars)


def _resolve_span(tree: ast.Module, want: Span | str, n: int) -> Span | None:
    if isinstance(want, tuple):
        start, end = want
        return (max(1, start), min(n, end))
    for node in ast.walk(tree):
        if isinstance(node, _Def) and node.name == want:
            return _node_range(node)
    return None


def _node_range(node: ast.stmt) -> Span:
    start = node.lineno
    decorators = getattr(node, "decorator_list", [])
    if decorators:
        start = min(start, decorators[0].lineno)
    return (start, node.end_lineno or node.lineno)


def _module_defs(tree: ast.Module) -> dict[str, tuple[ast.stmt, Span]]:
    """Top-level name -> (node, line range) for defs, classes, and assignments."""
    defs: dict[str, tuple[ast.stmt, Span]] = {}
    for node in tree.body:
        if isinstance(node, _Def):
            defs[node.name] = (node, _node_range(node))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    defs[tgt.id] = (node, _node_range(node))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defs[node.target.id] = (node, _node_range(node))
    return defs


def _referenced_names(tree: ast.Module, span: Span) -> set[str]:
    """Names loaded within the span (the attribute root is a Name, so it counts)."""
    start, end = span
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and start <= node.lineno <= end
        ):
            names.add(node.id)
    return names


def _resolve_deps(
    defs: dict[str, tuple[ast.stmt, Span]], referenced: set[str], span: Span
) -> list[tuple[str, Span]]:
    start, end = span
    deps: list[tuple[str, Span]] = []
    for name in referenced:
        if name not in defs:
            continue
        _, (ds, de) = defs[name]
        if ds >= start and de <= end:
            continue  # the definition is already inside the span
        deps.append((name, (ds, de)))
    deps.sort(key=lambda d: d[1][0])
    return deps


def _sig(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{kw} {node.name}({ast.unparse(node.args)}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}" + (f"({bases})" if bases else "")
    return ""


def _outline(tree: ast.Module, span: Span, dep_names: set[str]) -> list[str]:
    start, end = span
    rows: list[str] = []
    for node in tree.body:
        if not isinstance(node, _Def) or node.name in dep_names:
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


def _assemble(
    label: str,
    span_text: str,
    lines: list[str],
    deps: list[tuple[str, Span]],
    outline: list[str],
    n: int,
    max_chars: int,
) -> str:
    head = f"# bounded view ({n} lines)\n\n## requested: {label}\n{span_text}"
    handles = (
        "## expand\n- expand a symbol, expand lines A-B, "
        f"or read the full file ({n} lines) without bounds"
    )
    parts = [head]
    used = len(head) + len(handles) + 8

    dep_texts: list[str] = []
    for i, (_, (ds, de)) in enumerate(deps):
        txt = "\n".join(lines[ds - 1 : de])
        if dep_texts and used + len(txt) + 40 > max_chars:
            dep_texts.append(f"(+{len(deps) - i} more deps; expand)")
            break
        dep_texts.append(txt)
        used += len(txt) + 2
    if dep_texts:
        parts.append("## dependencies (same file)\n" + "\n\n".join(dep_texts))

    shown: list[str] = []
    for row in outline:
        if used + len(row) + 1 > max_chars - len(handles) - 20:
            shown.append(f"(+{len(outline) - len(shown)} more symbols)")
            break
        shown.append(row)
        used += len(row) + 1
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
