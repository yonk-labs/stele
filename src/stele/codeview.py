"""Bounded code reads: span + resolved deps + outline + expansion handles.

The over-fetch fix (see docs/specs/bounded-code-read-design.md). Code structure
is resolved through a pluggable ``Resolver`` (the provider pattern): the
``StdlibResolver`` (stdlib ``ast``, canonical for Python) is the default and
zero-dependency fallback; ``CodeparseResolver`` delegates to
``chunkshop.codeparse`` for other languages, reusing its multi-language parser
rather than reinventing one. A future graph-backed resolver (pg-raggraph's CALLS
graph) slots in the same way for cross-file resolution.

``codeview`` itself is only the bounded-VIEW assembler: it shapes what the model
sees at a Read (span verbatim + referenced same-file defs with bodies + signature
outline of the rest + expansion handles, under a char budget), and owns none of
the parsing or indexing. Never raises: malformed/unresolvable input degrades to a
head-of-file view.
"""

from __future__ import annotations

import ast
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Protocol, cast

Span = tuple[int, int]
_Def = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_OUTLINEABLE = {"function", "class"}
_EXT = {"python": ".py", "javascript": ".js", "typescript": ".ts", "go": ".go", "rust": ".rs"}


@dataclass(frozen=True)
class SymbolInfo:
    name: str
    kind: str  # function | class | method | assign | symbol
    line_start: int
    line_end: int
    signature: str
    parent: str | None = None


class Resolver(Protocol):
    def symbols(self, source: str) -> list[SymbolInfo]: ...
    def referenced(self, source: str, span: Span) -> set[str]: ...


class _ParseResult(Protocol):
    symbols: list[Any]
    call_sites: list[Any]


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #


class StdlibResolver:
    """Canonical Python resolver via the stdlib ``ast`` module."""

    def symbols(self, source: str) -> list[SymbolInfo]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        lines = source.splitlines()
        out: list[SymbolInfo] = []
        for node in tree.body:
            if isinstance(node, _Def):
                s, e = _node_range(node)
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                out.append(SymbolInfo(node.name, kind, s, e, _sig(node)))
                if isinstance(node, ast.ClassDef):
                    for m in node.body:
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            ms, me = _node_range(m)
                            out.append(SymbolInfo(m.name, "method", ms, me, _sig(m), node.name))
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        s, e = _node_range(node)
                        out.append(SymbolInfo(tgt.id, "assign", s, e, _line(lines, s)))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                s, e = _node_range(node)
                out.append(SymbolInfo(node.target.id, "assign", s, e, _line(lines, s)))
        return out

    def referenced(self, source: str, span: Span) -> set[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return set()
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


class CodeparseResolver:
    """Multi-language resolver via chunkshop.codeparse (tree-sitter, regex fallback)."""

    def __init__(self, language: str) -> None:
        self.language = language

    def _parse(self, source: str) -> _ParseResult:
        from chunkshop.codeparse import parse_file

        suffix = _EXT.get(self.language, ".txt")
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as f:
            f.write(source)
            path = f.name
        try:
            return cast(_ParseResult, parse_file(path, language=self.language))
        finally:
            os.unlink(path)

    def symbols(self, source: str) -> list[SymbolInfo]:
        result = self._parse(source)
        raw = sorted(result.symbols, key=lambda s: s.line_start)
        lines = source.splitlines()
        out: list[SymbolInfo] = []
        for i, sym in enumerate(raw):
            end = sym.line_end
            if end <= sym.line_start:  # regex mode: no body span -> heuristic end
                end = raw[i + 1].line_start - 1 if i + 1 < len(raw) else len(lines)
            out.append(
                SymbolInfo(sym.name, sym.symbol_type or "symbol", sym.line_start, end,
                           _line(lines, sym.line_start), sym.parent_name)
            )
        return out

    def referenced(self, source: str, span: Span) -> set[str]:
        result = self._parse(source)
        start, end = span
        return {
            cs.callee_name
            for cs in result.call_sites
            if start <= cs.line <= end and cs.callee_name
        }


def _select_resolver(language: str) -> Resolver:
    if language == "python":
        return StdlibResolver()
    try:
        import chunkshop.codeparse  # noqa: F401
    except ImportError:
        return StdlibResolver()
    return CodeparseResolver(language)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


# Adaptive output budget, by file size (CodeGraph's explore-budget tiers, applied
# per-file): a 30-line helper deserves a tight view; a 2000-line module can afford
# more deps + outline before the agent should just read the whole thing.
_BUDGET_TIERS = ((50, 1200), (200, 2000), (800, 3500), (3000, 6000))
_BUDGET_MAX = 9000


def budget_for_lines(n_lines: int) -> int:
    """Adaptive ``max_chars`` for a file of ``n_lines`` lines."""
    for ceiling, budget in _BUDGET_TIERS:
        if n_lines < ceiling:
            return budget
    return _BUDGET_MAX


_STALE_BANNER = (
    "## ⚠️ stale\n- this file changed since it was last indexed; the bounded "
    "view may be out of date. Re-read the file for the latest."
)


def _with_banner(view: str, stale: bool) -> str:
    return f"{_STALE_BANNER}\n\n{view}" if stale else view


def bounded_view(
    source: str,
    *,
    want: Span | str,
    language: str = "python",
    max_chars: int | None = 2000,
    stale: bool = False,
) -> str:
    """Bounded view of ``source`` around ``want`` (a line range or symbol name).

    ``max_chars=None`` selects an adaptive budget scaled to the file's line count.
    ``stale=True`` prepends a banner telling the agent the view may be out of date
    (CodeGraph's staleness signal; the source of truth is the manifest).
    """
    lines = source.splitlines()
    n = len(lines)
    budget = budget_for_lines(n) if max_chars is None else max_chars
    resolver = _select_resolver(language)
    syms = resolver.symbols(source)
    span = _resolve_span(syms, want, n)
    if span is None:
        return _with_banner(_fallback(lines, n, budget, note=f"symbol {want!r} not found"), stale)
    start, end = span
    span_text = "\n".join(lines[start - 1 : end])
    by_name = {s.name: s for s in syms}
    deps: list[SymbolInfo] = []
    for name in resolver.referenced(source, span):
        sym = by_name.get(name)
        if sym and not (sym.line_start >= start and sym.line_end <= end):
            deps.append(sym)
    deps.sort(key=lambda s: s.line_start)
    dep_names = {s.name for s in deps}
    outline = _outline(syms, span, dep_names)
    label = want if isinstance(want, str) else f"lines {want[0]}-{want[1]}"
    return _with_banner(_assemble(label, span_text, lines, deps, outline, n, budget), stale)


def bounded_python(source: str, *, want: Span | str, max_chars: int | None = 2000) -> str:
    """Bounded view of Python ``source`` (shim over :func:`bounded_view`)."""
    return bounded_view(source, want=want, language="python", max_chars=max_chars)


_LANG_BY_EXT = {ext: lang for lang, ext in _EXT.items()}


def language_for_path(path: str) -> str:
    """Best-effort language from a file extension (defaults to ``python``)."""
    _, ext = os.path.splitext(path)
    return _LANG_BY_EXT.get(ext, "python")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _node_range(node: ast.stmt) -> Span:
    start = node.lineno
    decorators = getattr(node, "decorator_list", [])
    if decorators:
        start = min(start, decorators[0].lineno)
    return (start, node.end_lineno or node.lineno)


def _line(lines: list[str], n: int) -> str:
    return lines[n - 1].strip() if 0 < n <= len(lines) else ""


def _sig(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{kw} {node.name}({ast.unparse(node.args)}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}" + (f"({bases})" if bases else "")
    return ""


def _resolve_span(syms: list[SymbolInfo], want: Span | str, n: int) -> Span | None:
    if isinstance(want, tuple):
        return (max(1, want[0]), min(n, want[1]))
    matches = [s for s in syms if s.name == want]
    if not matches:
        return None
    top = next((s for s in matches if s.parent is None), matches[0])
    return (top.line_start, top.line_end)


def _outline(syms: list[SymbolInfo], span: Span, dep_names: set[str]) -> list[str]:
    start, end = span
    rows: list[str] = []
    for sym in syms:
        if sym.parent is not None or sym.kind not in _OUTLINEABLE or sym.name in dep_names:
            continue
        if sym.line_start >= start and sym.line_end <= end:
            continue
        rows.append(f"L{sym.line_start}\t{sym.signature}")
        if sym.kind == "class":
            for m in syms:
                if m.parent == sym.name:
                    rows.append(f"L{m.line_start}\t    {m.signature}")
    return rows


def _assemble(
    label: str,
    span_text: str,
    lines: list[str],
    deps: list[SymbolInfo],
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
    for i, dep in enumerate(deps):
        txt = "\n".join(lines[dep.line_start - 1 : dep.line_end])
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
    head = f"# bounded view ({n} lines, head)\n"
    return (head + "\n".join(body_lines) + "\n\n" + handles)[:max_chars]
