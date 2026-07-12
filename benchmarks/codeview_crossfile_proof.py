"""In-repo value-proof: does CROSS-FILE resolution improve bounded code reads?

Context (the decision this informs)
-----------------------------------
`codeview.bounded_view` resolves a span's dependencies *within the same file*
only. The frozen `codeintel` work (AAT freeze, 2026-06-25) would add cross-file
resolution via pg-raggraph's CALLS graph (`GraphResolver`), but that ingestion
pipeline (backfill + chunkshop symbol-aware + tree-sitter + a Postgres-resident
graph) was deferred for "zero consumer pull / commoditized space / no moat".

Before un-freezing that pipeline, this proof answers the one empirical question
that should gate the decision: **on real read tasks, how often does a function's
body call symbols defined in OTHER files (so the in-file bounded view cannot show
them), and how much would a cross-file resolver recover, at what token cost?**

What is "real" here vs. what is modelled
----------------------------------------
- **Real**: the corpus is stele's own ``src/stele`` (genuine multi-file Python);
  the baseline is the production ``codeview.bounded_view``; the treatment drives
  the production ``codeintel.GraphResolver`` class.
- **Modelled**: the CALLS graph fed to ``GraphResolver`` is built here with the
  stdlib ``ast`` (codeview's canonical Python resolver) instead of being ingested
  into Postgres by ``backfill_code_graph``. tree-sitter grammars are not installed,
  so chunkshop runs in degraded regex-fallback mode (observed: mangled line numbers
  + def-as-call artifacts); ``ast`` is the accurate Python extractor. The edge
  STORE differs from Postgres (in-memory BFS replicating ``code_impact``'s
  traversal), which does not change the measured *value*.
- The graph resolution is **conservative / false-negative-biased**: a callee is
  counted cross-file-internal only when it resolves unambiguously to a stele symbol
  (via imports or a unique global name). Ambiguous/relative-import/dynamic cases are
  charged to "external", so the cross-file value reported here is a LOWER BOUND.

Run:
    .venv/bin/python -m benchmarks.codeview_crossfile_proof
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from benchmarks._versions import versions_md_line
from stele.codeintel.graph import GraphResolver
from stele.codeview import bounded_view
from stele.core.artifact import estimate_tokens

VERSION = "0.1.0"

# How much extra context the treatment is allowed to add per task (cross-file
# callee signatures). Keeps the comparison honest: cross-file deps are not free.
TREATMENT_BUDGET_CHARS = 1_200


# --------------------------------------------------------------------------- #
# Corpus model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SymbolDef:
    fqn: str           # stele.extraction.identity.canonical_subject
    module: str        # stele.extraction.identity
    name: str          # canonical_subject  (the simple name a call uses)
    file: str
    lineno: int
    end_lineno: int
    signature: str
    kind: str          # function | method | class


def _module_fqn(path: Path, root: Path) -> str:
    rel = path.relative_to(root.parent).with_suffix("")  # keep the 'stele' head
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts)


def _sig(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kw = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{kw} {node.name}({ast.unparse(node.args)}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"class {node.name}" + (f"({bases})" if bases else "")
    return ""


@dataclass
class ModuleParse:
    module: str
    file: str
    source: str
    defs: list[SymbolDef] = field(default_factory=list)
    # caller fqn -> list of (callee_simple_name, ast.Call) collected for resolution
    from_imports: dict[str, str] = field(default_factory=dict)   # name -> source module
    module_aliases: dict[str, str] = field(default_factory=dict)  # alias -> module
    calls: list[tuple[str, ast.AST]] = field(default_factory=list)  # (caller_fqn, callnode)


def parse_module(path: Path, root: Path) -> ModuleParse | None:
    source = path.read_text(errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    module = _module_fqn(path, root)
    mp = ModuleParse(module=module, file=str(path), source=source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for alias in node.names:
                mp.from_imports[alias.asname or alias.name] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mp.module_aliases[alias.asname or alias.name] = alias.name

    def record_calls(scope_node: ast.AST, caller_fqn: str) -> None:
        for n in ast.walk(scope_node):
            if isinstance(n, ast.Call):
                mp.calls.append((caller_fqn, n.func))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fqn = f"{module}.{node.name}"
            mp.defs.append(SymbolDef(fqn, module, node.name, mp.file,
                                     node.lineno, node.end_lineno or node.lineno,
                                     _sig(node), "function"))
            record_calls(node, fqn)
        elif isinstance(node, ast.ClassDef):
            fqn = f"{module}.{node.name}"
            mp.defs.append(SymbolDef(fqn, module, node.name, mp.file,
                                     node.lineno, node.end_lineno or node.lineno,
                                     _sig(node), "class"))
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mfqn = f"{module}.{node.name}.{m.name}"
                    mp.defs.append(SymbolDef(mfqn, module, m.name, mp.file,
                                             m.lineno, m.end_lineno or m.lineno,
                                             _sig(m), "method"))
                    record_calls(m, mfqn)
    return mp


# --------------------------------------------------------------------------- #
# Cross-file CALLS graph (the data a real graph DB would hold)
# --------------------------------------------------------------------------- #
@dataclass
class CallGraph:
    by_fqn: dict[str, SymbolDef]
    name_index: dict[str, list[SymbolDef]]      # simple name -> defs (across modules)
    callees: dict[str, set[str]]                # caller fqn -> cross-file callee fqns
    counts: dict[str, int]                      # in_file / cross_file / external


def _callee_name(func: ast.AST) -> tuple[str, str | None]:
    """(simple_name, base) for a call target. base is the receiver for x.y()."""
    if isinstance(func, ast.Name):
        return func.id, None
    if isinstance(func, ast.Attribute):
        base = func.value.id if isinstance(func.value, ast.Name) else None
        return func.attr, base
    return "", None


def build_call_graph(mods: list[ModuleParse]) -> CallGraph:
    by_fqn: dict[str, SymbolDef] = {}
    name_index: dict[str, list[SymbolDef]] = defaultdict(list)
    local_names: dict[str, set[str]] = defaultdict(set)  # module -> names defined there
    for mp in mods:
        for d in mp.defs:
            by_fqn[d.fqn] = d
            name_index[d.name].append(d)
            local_names[mp.module].add(d.name)

    def resolve_cross_file(mp: ModuleParse, name: str, base: str | None) -> str | None:
        """Resolve a call target to a stele symbol fqn in ANOTHER module, or None.
        Conservative: only unambiguous resolutions count (lower-bound bias)."""
        # x.y() where x is `import a.b.c (as x)`  -> a.b.c.y
        if base is not None and base in mp.module_aliases:
            cand = f"{mp.module_aliases[base]}.{name}"
            return cand if cand in by_fqn else None
        # bare name imported via `from M import name`
        if base is None and name in mp.from_imports:
            cand = f"{mp.from_imports[name]}.{name}"
            return cand if cand in by_fqn else None
        # bare name defined in exactly one OTHER stele module
        if base is None and name not in local_names[mp.module]:
            defs = [d for d in name_index.get(name, []) if d.module != mp.module]
            uniq_modules = {d.module for d in defs}
            if len(uniq_modules) == 1:
                # prefer a function/class top-level def for stability
                top = next((d for d in defs if d.kind != "method"), defs[0])
                return top.fqn
        return None

    callees: dict[str, set[str]] = defaultdict(set)
    counts = {"in_file": 0, "cross_file": 0, "external": 0}
    for mp in mods:
        for caller_fqn, func in mp.calls:
            name, base = _callee_name(func)
            if not name:
                continue
            if base in ("self", "cls") or (base is None and name in local_names[mp.module]):
                counts["in_file"] += 1
                continue
            target = resolve_cross_file(mp, name, base)
            if target is not None and target != caller_fqn:
                counts["cross_file"] += 1
                callees[caller_fqn].add(target)
            else:
                counts["external"] += 1
    return CallGraph(by_fqn, dict(name_index), dict(callees), counts)


# --------------------------------------------------------------------------- #
# Drive the REAL GraphResolver with the in-memory graph
# --------------------------------------------------------------------------- #
@dataclass
class _Edge:
    fqn: str


@dataclass
class _Impact:
    callees: list[_Edge] = field(default_factory=list)
    callers: list[_Edge] = field(default_factory=list)


def make_resolver(graph: CallGraph) -> GraphResolver:
    """A real GraphResolver whose impact_fn does the BFS code_impact would do."""
    async def impact_fn(db: object, fqn: str, *, namespace: str, depth: int) -> _Impact:
        seen: set[str] = set()
        frontier = {fqn}
        for _ in range(max(1, depth)):
            nxt: set[str] = set()
            for f in frontier:
                for callee in graph.callees.get(f, set()):
                    if callee not in seen:
                        seen.add(callee)
                        nxt.add(callee)
            frontier = nxt
        return _Impact(callees=[_Edge(f) for f in sorted(seen)])

    return GraphResolver(db=object(), namespace="stele", impact_fn=impact_fn)


# --------------------------------------------------------------------------- #
# The measurement
# --------------------------------------------------------------------------- #
@dataclass
class TaskResult:
    fqn: str
    cross_file_callees: int
    baseline_visible: int
    treatment_visible: int
    added_tokens: int
    baseline_tokens: int


def measure(graph: CallGraph, resolver: GraphResolver) -> list[TaskResult]:
    results: list[TaskResult] = []
    sources: dict[str, str] = {}
    for fqn, callee_set in graph.callees.items():
        sym = graph.by_fqn.get(fqn)
        if sym is None or not callee_set:
            continue
        src = sources.get(sym.file)
        if src is None:
            src = Path(sym.file).read_text(errors="replace")
            sources[sym.file] = src

        # Baseline: the production bounded view (in-file deps only).
        view = bounded_view(src, want=sym.name, max_chars=None, language="python")
        baseline_tokens = estimate_tokens(view)

        # How many cross-file callee DEFINITIONS are visible in the baseline view?
        # (~0 by construction — codeview is in-file only — but checked, not assumed.)
        callee_defs = [graph.by_fqn[c] for c in callee_set if c in graph.by_fqn]
        baseline_visible = sum(1 for d in callee_defs if d.signature and d.signature in view)

        # Treatment: real GraphResolver -> cross-file callee fqns -> append sigs.
        resolved = resolver.callees(fqn, depth=1)
        added = 0
        appended = 0
        for cfqn in resolved:
            d = graph.by_fqn.get(cfqn)
            if d is None:
                continue
            line = f"# {d.module}\n{d.signature}"
            if added + len(line) > TREATMENT_BUDGET_CHARS:
                break
            added += len(line) + 2
            appended += 1
        treatment_visible = baseline_visible + appended

        results.append(TaskResult(
            fqn=fqn,
            cross_file_callees=len(callee_set),
            baseline_visible=baseline_visible,
            treatment_visible=min(treatment_visible, len(callee_set)),
            added_tokens=estimate_tokens("x" * added) if added else 0,
            baseline_tokens=baseline_tokens,
        ))
    return results


@dataclass
class Report:
    timestamp: str
    version: str
    summary: dict[str, object]
    verdict: str


def _verdict(s: dict[str, object]) -> str:
    prevalence = float(s["task_prevalence"])              # type: ignore[arg-type]
    cf_share = float(s["cross_file_call_share"])          # type: ignore[arg-type]
    coverage = float(s["treatment_coverage"])             # type: ignore[arg-type]
    cost = float(s["avg_added_token_pct"])                # type: ignore[arg-type]
    if cf_share < 0.10 or prevalence < 0.10:
        return ("MARGINAL — cross-file calls are rare in this corpus; the in-file "
                "bounded view already covers most dependencies. The freeze holds: "
                "building the cross-file ingestion pipeline is not justified by value.")
    if prevalence >= 0.25 and cf_share >= 0.15 and coverage >= 0.70 and cost <= 0.25:
        return ("MATERIAL — a meaningful share of read tasks depend on cross-file "
                "symbols the in-file view cannot show, and cross-file resolution "
                "recovers them at modest token cost. This supports building the "
                "NARROW path (cross-file dependency-completion for bounded reads), "
                "not a general code-graph product.")
    return ("MIXED — cross-file dependencies exist and are recoverable, but the "
            "prevalence/cost trade-off is not decisive. Judgment call; see numbers. "
            "A targeted consumer use case should gate the build.")


def run(root: Path = Path("src/stele"), output_root: Path = Path("benchmarks/runs"),
        write: bool = True) -> Report:
    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    mods = [mp for p in files if (mp := parse_module(p, root)) is not None]
    graph = build_call_graph(mods)
    resolver = make_resolver(graph)
    results = measure(graph, resolver)

    callable_syms = sum(1 for d in graph.by_fqn.values() if d.kind in ("function", "method"))
    total_calls = sum(graph.counts.values())
    total_cf = sum(r.cross_file_callees for r in results)
    total_treatment_visible = sum(r.treatment_visible for r in results)
    total_baseline_visible = sum(r.baseline_visible for r in results)
    avg_added_pct = (
        sum(r.added_tokens / r.baseline_tokens for r in results if r.baseline_tokens)
        / len(results) if results else 0.0
    )
    cf_share = round(graph.counts["cross_file"] / total_calls, 4) if total_calls else 0.0

    summary: dict[str, object] = {
        "corpus_files": len(mods),
        "corpus_symbols": len(graph.by_fqn),
        "callable_symbols": callable_syms,
        "total_calls": total_calls,
        "calls_in_file": graph.counts["in_file"],
        "calls_cross_file_internal": graph.counts["cross_file"],
        "calls_external": graph.counts["external"],
        "cross_file_call_share": cf_share,
        "tasks": len(results),
        "task_prevalence": round(len(results) / callable_syms, 4) if callable_syms else 0.0,
        "avg_cross_file_callees_per_task": round(total_cf / len(results), 2) if results else 0.0,
        "baseline_coverage": round(total_baseline_visible / total_cf, 4) if total_cf else 0.0,
        "treatment_coverage": round(total_treatment_visible / total_cf, 4) if total_cf else 0.0,
        "avg_added_token_pct": round(avg_added_pct, 4),
    }
    report = Report(
        timestamp=datetime.now(UTC).isoformat(),
        version=VERSION,
        summary=summary,
        verdict=_verdict(summary),
    )
    if write:
        _write(report, results, output_root)
    return report


def _write(report: Report, results: list[TaskResult], output_root: Path) -> tuple[Path, Path]:
    out_dir = output_root / datetime.now(UTC).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "CodeviewCrossfileProof.json"
    md_path = out_dir / "CodeviewCrossfileProof.md"
    json_path.write_text(json.dumps(
        {"report": asdict(report), "tasks": [asdict(r) for r in results[:50]]}, indent=2))
    md_path.write_text(render_md(report, results))
    return json_path, md_path


def render_md(report: Report, results: list[TaskResult]) -> str:
    s = report.summary
    top = sorted(results, key=lambda r: r.cross_file_callees, reverse=True)[:10]
    lines = [
        "# Codeview cross-file value-proof",
        "",
        versions_md_line(),
        f"- generated: {report.timestamp}",
        f"- proof version: {report.version}",
        "",
        "## Question",
        "",
        "Does adding CROSS-FILE dependency resolution (the frozen `GraphResolver`) "
        "materially improve `codeview`'s in-file-only bounded reads, on stele's own source?",
        "",
        "## Result",
        "",
        f"**VERDICT: {report.verdict}**",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| corpus files | {s['corpus_files']} |",
        f"| symbols (defs) | {s['corpus_symbols']} |",
        f"| total calls | {s['total_calls']} |",
        f"| &nbsp;&nbsp;in-file (codeview handles) | {s['calls_in_file']} |",
        f"| &nbsp;&nbsp;cross-file internal (addressable) | {s['calls_cross_file_internal']} |",
        f"| &nbsp;&nbsp;external / stdlib (no graph helps) | {s['calls_external']} |",
        f"| **cross-file call share** | **{s['cross_file_call_share']:.1%}** |",
        f"| read tasks (≥1 cross-file callee) | {s['tasks']} |",
        f"| **task prevalence** | **{s['task_prevalence']:.1%}** of callables |",
        f"| avg cross-file callees / task | {s['avg_cross_file_callees_per_task']} |",
        f"| baseline cross-file coverage | {s['baseline_coverage']:.1%} |",
        f"| **treatment cross-file coverage** | **{s['treatment_coverage']:.1%}** |",
        f"| avg added context (tokens, % of baseline view) | {s['avg_added_token_pct']:.1%} |",
        "",
        "## How to read this",
        "",
        "- **cross-file call share** is the addressable surface: of all calls, the "
        "fraction that target another stele module (not stdlib/third-party, which no "
        "code graph can resolve). A small share ⇒ small ceiling on value.",
        "- **baseline coverage ≈ 0** by construction: `codeview` only shows same-file "
        "defs, so cross-file callees appear as bare names with no definition.",
        "- **treatment coverage** is what the real `GraphResolver` recovers within a "
        f"{TREATMENT_BUDGET_CHARS}-char add budget.",
        "",
        "## Highest cross-file-dependency tasks",
        "",
        "| symbol | cross-file callees | baseline→treatment visible |",
        "| --- | --- | --- |",
    ]
    lines += [f"| `{r.fqn}` | {r.cross_file_callees} | {r.baseline_visible}→{r.treatment_visible} |"
              for r in top]
    lines += [
        "",
        "## Honesty notes",
        "",
        "- The CALLS graph is built with stdlib `ast` (codeview's canonical Python "
        "resolver), not ingested into Postgres by `backfill_code_graph`. tree-sitter "
        "is unavailable here, so chunkshop runs degraded; `ast` is the accurate Python "
        "extractor. The real `GraphResolver` class is driven with these edges.",
        "- Cross-file resolution is conservative (unambiguous imports / unique global "
        "names only); relative imports, dynamic dispatch and ambiguous names are "
        "charged to 'external'. So the cross-file value here is a **lower bound**.",
        "- Treatment appends callee *signatures* (not full bodies) under a fixed budget; "
        "a real integration could expand bodies on demand via the existing handles.",
        "",
        "## Reproducing",
        "",
        "```bash",
        ".venv/bin/python -m benchmarks.codeview_crossfile_proof",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="stele codeview cross-file value-proof")
    parser.add_argument("--root", type=Path, default=Path("src/stele"))
    parser.add_argument("--output-root", type=Path, default=Path("benchmarks/runs"))
    args = parser.parse_args()
    report = run(root=args.root, output_root=args.output_root)
    print(json.dumps(report.summary, indent=2))
    print("\nVERDICT:", report.verdict)


if __name__ == "__main__":
    main()
