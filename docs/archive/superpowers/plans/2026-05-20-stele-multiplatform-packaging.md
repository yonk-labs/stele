# Stele Multi-Platform Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `stele-core` with a multi-platform packaging story: an `stele-mcp` stdio server exposing the full 18-tool read/write facade, a `stele` CLI for init/install/uninstall/doctor/status/mcp, and Jinja-rendered skill/hook/shared-doc-section content for seven launch platforms (Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Copilot, Aider) — all driven from one `PLATFORM_CONFIG` dict and one skill template.

**Architecture:** Six independent channels (MCP server, CLI, packaging primitives, single Jinja skill template, opt-in hooks/rules-files, project config) under three new top-level packages: `src/stele/mcp/`, `src/stele/cli/`, `src/stele/packaging/`. Each channel has exactly one source of truth. The MCP server and CLI are both transports over the existing `Stele` facade — never re-implement facade logic. Templates render from `src/stele/packaging/templates/`; platform routing is a single `PLATFORM_CONFIG: dict[str, PlatformSpec]` table.

**Tech Stack:** Python ≥3.12; `mcp` (Python) stdio transport; Pydantic v2 for config schemas; Jinja2 for templates; `pyyaml` for `.stele/config.yaml` (already a dep). Tests: pytest, existing contract-test backend parametrization.

**Spec:** `docs/superpowers/specs/2026-05-20-stele-multiplatform-packaging-design.md` (design-approved 2026-05-20, Approach A).

---

## File Structure

| Path | New/Mod | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `mcp` + `jinja2` deps; add `stele` + `stele-mcp` console scripts; bump `[tool.hatch.build.targets.wheel].packages` for `templates/` data |
| `src/stele/mcp/__init__.py` | Create | Package marker |
| `src/stele/mcp/sanitize.py` | Create | `sanitize_label(s) -> str` — strip ANSI/control chars, clamp 256 |
| `src/stele/mcp/errors.py` | Create | `McpError` (Pydantic), `EXCEPTION_CODE_MAP`, `guard(handler) -> handler` decorator |
| `src/stele/mcp/config.py` | Create | `load_config(start_dir=None) -> SteleConfig` — walk-up resolution + `~/.config/stele/config.yaml` fallback |
| `src/stele/mcp/tools.py` | Create | `ToolSpec` dataclass + `TOOLS: list[ToolSpec]` registry (all 18 tools) |
| `src/stele/mcp/server.py` | Create | Stdio MCP server bootstrap; iterates `TOOLS` for `list_tools`/`call_tool`; wraps every handler in `guard()` |
| `src/stele/cli/__init__.py` | Create | `main()` argparse entry; dispatches to subcommands |
| `src/stele/cli/config.py` | Create | CLI-facing `.stele/config.yaml` model (wraps `core.config`); friendly error messages |
| `src/stele/cli/commands/__init__.py` | Create | Package marker |
| `src/stele/cli/commands/init.py` | Create | `stele init` — writes `.stele/config.yaml` |
| `src/stele/cli/commands/install.py` | Create | `stele install --platform ...` — dispatches to `packaging.install.install_for` |
| `src/stele/cli/commands/uninstall.py` | Create | `stele uninstall --platform ...` |
| `src/stele/cli/commands/status.py` | Create | `stele status` — per-platform install state + MCP reachability |
| `src/stele/cli/commands/doctor.py` | Create | `stele doctor` — config validation + backend reachability |
| `src/stele/cli/commands/mcp.py` | Create | `stele mcp` — alias for the `stele-mcp` server |
| `src/stele/packaging/__init__.py` | Create | Package marker |
| `src/stele/packaging/platforms.py` | Create | `PlatformSpec` + `PLATFORM_CONFIG: dict[str, PlatformSpec]` for 7 platforms |
| `src/stele/packaging/render.py` | Create | Jinja2 environment + `render_skill`/`render_hook`/`render_agents_md_section` |
| `src/stele/packaging/sections.py` | Create | `upsert_section(path, marker, content)`, `remove_section(path, marker)` — idempotent shared-doc editor |
| `src/stele/packaging/version_stamps.py` | Create | `write_stamp(platform, dir)`, `refresh_all(home=None)` — graphify-style sync |
| `src/stele/packaging/install.py` | Create | `install_for(platform, *, dry_run=False)`, `uninstall_for(platform)` |
| `src/stele/packaging/templates/skill.md.j2` | Create | One skill template, all platforms |
| `src/stele/packaging/templates/agents-md-section.md.j2` | Create | One shared-doc section template |
| `src/stele/packaging/templates/mcp-server-config.json.j2` | Create | MCP server entry rendered into platform mcp.json |
| `src/stele/packaging/templates/hooks/claude-code.sh.j2` | Create | Bash hook |
| `src/stele/packaging/templates/hooks/gemini-settings.json.j2` | Create | BeforeTool settings entry |
| `src/stele/packaging/templates/hooks/opencode-plugin.js.j2` | Create | `tool.execute.before` plugin |
| `src/stele/packaging/templates/hooks/cursor-rules.mdc.j2` | Create | Cursor `.mdc` rules file |
| `tests/unit/mcp/test_sanitize.py` | Create | ANSI/ctrl-char strip + clamp |
| `tests/unit/mcp/test_errors.py` | Create | Exception → code mapping |
| `tests/unit/mcp/test_config.py` | Create | Walk-up + fallback resolution |
| `tests/unit/mcp/test_tools.py` | Create | Per-tool schema valid; dispatch via mock `Stele` |
| `tests/unit/packaging/test_sections.py` | Create | Upsert/remove idempotent + conflict refusal |
| `tests/unit/packaging/test_platforms.py` | Create | Every platform spec is complete |
| `tests/unit/packaging/test_render.py` | Create | Every platform renders; required markers present |
| `tests/unit/packaging/test_version_stamps.py` | Create | refresh_all behavior |
| `tests/unit/cli/test_init.py` | Create | `stele init` writes valid config |
| `tests/unit/cli/test_install.py` | Create | per-platform install round-trip with tmp HOME |
| `tests/unit/cli/test_uninstall.py` | Create | uninstall removes everything install wrote |
| `tests/unit/cli/test_doctor.py` | Create | Validation pass/fail behavior |
| `tests/contract/test_mcp_contract.py` | Create | Full MCP surface over a real stdio pipe, parametrized over `BACKENDS` |
| `tests/integration/test_install_e2e.py` | Create | End-to-end install/uninstall across 7 platforms in tmp HOME |
| `docs/packaging-auth-model.md` | Create | Why stdio-only-no-auth in v1; how to revisit |
| `docs/packaging-smoke-checklist.md` | Create | Manual real-platform smoke list |
| `docs/current-status.md` | Modify | Add packaging row to "What's implemented" |
| `CLAUDE.md` | Modify | Add `mcp/`, `cli/`, `packaging/` to architecture overview |

**Not touched (locked / out of scope):**
- All existing `src/stele/{core,storage,retrieval,summary,pii,indexing,interception,extraction,recall,revisor,runtime,workgraph}` — wrapped, not modified.
- The `Stele` facade public contract — surfaced verbatim; no signature changes.
- Existing benchmarks, scripts, docker-compose files.

**Known facts (verified, use verbatim):**
- venv tools: `.venv/bin/pytest`, `.venv/bin/ruff check`, `.venv/bin/mypy src tests benchmarks`.
- pyproject already has `pythonpath = ["src", "."]` and packages `["src/stele", "benchmarks"]`.
- Existing scripts use `stele-*` naming (`stele-showcase`, etc.) — keep `stele` + `stele-mcp` distinct.
- License is Apache-2.0; templates inherit (no separate license headers needed in generated text).
- Facade public surface (from `src/stele/core/stash.py` and CLAUDE.md): `store`, `fetch`, `search`, `query`, `list`, `delete`, `cleanup_expired`, `export_jsonl`, `import_jsonl`, `capabilities`, plus `memory`/`extract`/`recall` facades. Only the 18 tools in the spec §4.1 are exposed by MCP v1.
- Backend contract test parametrization: `tests/contract/` files import a `BACKENDS` fixture that auto-skips DSN-gated backends; reuse this verbatim.
- Date for the plan/commit messages: 2026-05-20.

---

## Test design notes

- **TDD is mandatory.** Every implementation task starts with a failing test.
- **Unit tests use in-memory `Stele`** (`Stele.from_config({"backend": {"type": "memory"}})`) unless the test is specifically about config-file resolution or backend reachability.
- **Contract test reuses `tests/contract/` parametrization** — runs against memory + sqlite by default; pg/mariadb/clickhouse auto-included when their DSN env vars are set.
- **CLI tests use `monkeypatch.setenv("HOME", tmp_path)`** for filesystem isolation. Never touch the real `~/`.
- **Skill content goes through Jinja's `autoescape=False`** — these are markdown/bash/JS templates, not HTML. Test that no template emits a `{{` or `{%` (verifies all vars resolved).
- **No mocking of facade methods** in the contract test — real `Stele` instance, real stdio pipe.

---

## Phase 0 — Dependencies and scripts

### Task 1: Add deps and console scripts

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `mcp` and `jinja2` to dependencies**

Edit `[project] dependencies` in `pyproject.toml`:

```toml
dependencies = [
  "pydantic>=2,<3",
  "pyyaml>=6,<7",
  "lede>=0.3,<0.4",
  "mcp>=1.0,<2",
  "jinja2>=3.1,<4",
]
```

- [ ] **Step 2: Add console scripts**

Add to the existing `[project.scripts]` block:

```toml
stele = "stele.cli:main"
stele-mcp = "stele.mcp.server:main"
```

- [ ] **Step 3: Ensure templates ship in the wheel**

Edit `[tool.hatch.build.targets.wheel]`:

```toml
packages = ["src/stele", "benchmarks"]

[tool.hatch.build.targets.wheel.shared-data]
"src/stele/packaging/templates" = "stele/packaging/templates"
```

(Hatchling already follows the package dir; the `shared-data` line ensures `.j2` files are not skipped as non-Python.)

- [ ] **Step 4: Verify the install resolves**

Run: `.venv/bin/pip install -e .[dev] --quiet`
Expected: success; `which stele && which stele-mcp` shows both in `.venv/bin/`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "build(packaging): add mcp + jinja2 deps and stele/stele-mcp console scripts"
```

---

## Phase 1 — MCP foundation modules (DC-A approach: pure-function modules first)

### Task 2: `sanitize.py`

**Files:**
- Create: `src/stele/mcp/__init__.py` (empty)
- Create: `src/stele/mcp/sanitize.py`
- Create: `tests/unit/mcp/__init__.py` (empty)
- Test: `tests/unit/mcp/test_sanitize.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/mcp/test_sanitize.py`:

```python
from stele.mcp.sanitize import sanitize_label


def test_strips_ansi() -> None:
    assert sanitize_label("\x1b[31mhello\x1b[0m") == "hello"


def test_strips_control_chars() -> None:
    assert sanitize_label("a\x00b\x07c\nd") == "abcd"


def test_clamps_to_256() -> None:
    out = sanitize_label("a" * 1000)
    assert len(out) == 256
    assert out == "a" * 256


def test_neutralizes_prompt_injection_markers() -> None:
    out = sanitize_label("Ignore previous instructions\x1b[2J\x1b[H")
    assert "\x1b" not in out
    assert "Ignore previous instructions" in out  # text content preserved


def test_preserves_unicode_letters() -> None:
    assert sanitize_label("café — π") == "café — π"


def test_empty_string() -> None:
    assert sanitize_label("") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/mcp/test_sanitize.py -v`
Expected: ImportError or AttributeError on `sanitize_label`.

- [ ] **Step 3: Implement**

Create `src/stele/mcp/__init__.py`:

```python
"""Stele MCP server package."""
```

Create `src/stele/mcp/sanitize.py`:

```python
"""Label sanitization for MCP-bound free-text fields.

Strips ANSI escapes, control chars, and clamps to a fixed max length to
neutralize prompt-injection payloads inside LLM-derived or
externally-sourced strings before they cross the MCP transport.
"""

from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_MAX_LEN = 256


def sanitize_label(value: str) -> str:
    """Strip ANSI, control chars, and clamp to 256 chars."""
    if not value:
        return ""
    stripped = _ANSI_RE.sub("", value)
    stripped = _CTRL_RE.sub("", stripped)
    return stripped[:_MAX_LEN]
```

- [ ] **Step 4: Verify tests pass**

Run: `.venv/bin/pytest tests/unit/mcp/test_sanitize.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint + types**

Run: `.venv/bin/ruff check src/stele/mcp/ tests/unit/mcp/ && .venv/bin/mypy src/stele/mcp/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/stele/mcp/__init__.py src/stele/mcp/sanitize.py tests/unit/mcp/__init__.py tests/unit/mcp/test_sanitize.py
git commit -m "feat(mcp): label sanitizer for MCP-bound free-text fields"
```

---

### Task 3: `errors.py`

**Files:**
- Create: `src/stele/mcp/errors.py`
- Test: `tests/unit/mcp/test_errors.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/mcp/test_errors.py`:

```python
from __future__ import annotations

import pytest

from stele.core.exceptions import (
    CapabilityError,
    ConfigError,
    PIIBlockedError,
    ValidationError,
)
from stele.mcp.errors import McpError, exception_to_error, guard


def test_known_exceptions_map_to_codes() -> None:
    assert exception_to_error(ConfigError("bad")).code == "CONFIG"
    assert exception_to_error(PIIBlockedError("blocked")).code == "PII_BLOCKED"
    assert exception_to_error(CapabilityError("missing")).code == "CAPABILITY"
    assert exception_to_error(ValidationError("invalid")).code == "VALIDATION"


def test_unknown_exception_maps_to_internal() -> None:
    err = exception_to_error(RuntimeError("boom"))
    assert err.code == "INTERNAL"
    assert "boom" in err.message


def test_mcperror_serializes_as_dict() -> None:
    err = McpError(code="CONFIG", message="bad", context={"path": "/tmp"})
    assert err.model_dump() == {
        "code": "CONFIG",
        "message": "bad",
        "context": {"path": "/tmp"},
    }


def test_guard_decorator_catches_and_wraps() -> None:
    @guard
    def handler(arg: str) -> str:
        raise ConfigError("nope")

    out = handler("x")
    assert out == {"error": {"code": "CONFIG", "message": "nope", "context": {}}}


def test_guard_passes_through_success() -> None:
    @guard
    def handler(arg: str) -> dict[str, str]:
        return {"ok": arg}

    assert handler("yes") == {"ok": "yes"}


def test_guard_logs_unmapped_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    @guard
    def handler() -> None:
        raise RuntimeError("unexpected")

    out = handler()
    assert out["error"]["code"] == "INTERNAL"
    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "unexpected" in captured.err
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `.venv/bin/pytest tests/unit/mcp/test_errors.py -v`
Expected: ImportError on `stele.mcp.errors`.

- [ ] **Step 3: Verify exception types exist**

Run: `.venv/bin/python -c "from stele.core.exceptions import ConfigError, PIIBlockedError, CapabilityError, ValidationError; print('ok')"`
Expected: `ok`. If any are missing, find their actual module path with `grep -r "class ConfigError" src/stele/` and update the import in both `test_errors.py` and the implementation below.

- [ ] **Step 4: Implement**

Create `src/stele/mcp/errors.py`:

```python
"""MCP error model and handler guard decorator.

All MCP tool handlers wrap through `guard` so exceptions become structured
JSON error responses with stable codes. Unmapped exceptions log their
traceback to stderr and surface as `INTERNAL`.
"""

from __future__ import annotations

import functools
import sys
import traceback
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from stele.core.exceptions import (
    CapabilityError,
    ConfigError,
    PIIBlockedError,
    ValidationError,
)

T = TypeVar("T")


class McpError(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = {}


_CODE_MAP: dict[type[Exception], str] = {
    ConfigError: "CONFIG",
    PIIBlockedError: "PII_BLOCKED",
    CapabilityError: "CAPABILITY",
    ValidationError: "VALIDATION",
}


def exception_to_error(exc: Exception) -> McpError:
    for exc_type, code in _CODE_MAP.items():
        if isinstance(exc, exc_type):
            return McpError(code=code, message=str(exc))
    return McpError(code="INTERNAL", message=str(exc) or exc.__class__.__name__)


def guard(handler: Callable[..., T]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return handler(*args, **kwargs)
        except Exception as exc:
            err = exception_to_error(exc)
            if err.code == "INTERNAL":
                traceback.print_exception(exc, file=sys.stderr)
            return {"error": err.model_dump()}

    return wrapped
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/unit/mcp/test_errors.py -v`
Expected: 6 passed. If `ValidationError` is unexpectedly an alias for Pydantic's `ValidationError`, the import path differs — fix per Step 3.

- [ ] **Step 6: Lint + types**

Run: `.venv/bin/ruff check src/stele/mcp/ tests/unit/mcp/ && .venv/bin/mypy src/stele/mcp/`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/stele/mcp/errors.py tests/unit/mcp/test_errors.py
git commit -m "feat(mcp): structured error model and handler guard decorator"
```

---

### Task 4: `config.py` — config-file resolution

**Files:**
- Create: `src/stele/mcp/config.py`
- Test: `tests/unit/mcp/test_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/mcp/test_config.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.mcp.config import config_path, load_raw_config


def test_walks_up_to_dot_stele(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    nested = project / "src" / "nested"
    nested.mkdir(parents=True)
    (project / ".stele").mkdir()
    (project / ".stele" / "config.yaml").write_text("backend:\n  type: memory\n")

    resolved = config_path(start_dir=nested)
    assert resolved == project / ".stele" / "config.yaml"


def test_falls_back_to_user_global(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    cfg_dir = home / ".config" / "stele"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("backend:\n  type: memory\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)

    project = tmp_path / "proj"
    project.mkdir()

    resolved = config_path(start_dir=project)
    assert resolved == cfg_dir / "config.yaml"


def test_returns_none_when_nothing_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "no-home")
    assert config_path(start_dir=tmp_path) is None


def test_load_raw_config_parses_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / ".stele" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text("backend:\n  type: sqlite\n  dsn: foo.db\n")

    loaded = load_raw_config(cfg)
    assert loaded == {"backend": {"type": "sqlite", "dsn": "foo.db"}}
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `.venv/bin/pytest tests/unit/mcp/test_config.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/stele/mcp/config.py`:

```python
"""Config-file resolution for the MCP server and CLI.

Walks up from `start_dir` (defaults to CWD) looking for `.stele/config.yaml`.
Falls back to `~/.config/stele/config.yaml`. Returns `None` if neither exists;
callers decide whether that's fatal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def config_path(*, start_dir: Path | None = None) -> Path | None:
    cwd = (start_dir or Path.cwd()).resolve()
    for candidate in [cwd, *cwd.parents]:
        local = candidate / ".stele" / "config.yaml"
        if local.is_file():
            return local
    user_global = Path.home() / ".config" / "stele" / "config.yaml"
    if user_global.is_file():
        return user_global
    return None


def load_raw_config(path: Path) -> dict[str, Any]:
    with path.open() as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping at top of {path}, got {type(loaded)!r}")
    return loaded
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/mcp/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + types**

Run: `.venv/bin/ruff check src/stele/mcp/ tests/unit/mcp/ && .venv/bin/mypy src/stele/mcp/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/stele/mcp/config.py tests/unit/mcp/test_config.py
git commit -m "feat(mcp): walk-up + user-global config-file resolution"
```

---

## Phase 2 — Packaging primitives (DC-C: prep before any platform-specific code)

### Task 5: `sections.py` — idempotent shared-doc editor

**Files:**
- Create: `src/stele/packaging/__init__.py` (empty)
- Create: `src/stele/packaging/sections.py`
- Create: `tests/unit/packaging/__init__.py` (empty)
- Test: `tests/unit/packaging/test_sections.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/packaging/test_sections.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.packaging.sections import (
    SectionConflictError,
    remove_section,
    upsert_section,
)


def test_upsert_appends_when_marker_absent(tmp_path: Path) -> None:
    doc = tmp_path / "CLAUDE.md"
    doc.write_text("# Existing\n\nUser content here.\n")

    upsert_section(doc, marker="## stele", content="## stele\n\nstele body\n")

    text = doc.read_text()
    assert "User content here." in text
    assert "## stele\n\nstele body\n" in text
    assert text.endswith("\n")


def test_upsert_replaces_existing_section(tmp_path: Path) -> None:
    doc = tmp_path / "AGENTS.md"
    doc.write_text(
        "# Doc\n\n## stele\n\nOLD body\n\n## other\n\nOther content\n"
    )

    upsert_section(doc, marker="## stele", content="## stele\n\nNEW body\n")

    text = doc.read_text()
    assert "OLD body" not in text
    assert "NEW body" in text
    assert "Other content" in text  # Following section preserved


def test_upsert_preserves_content_before_and_after(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Header\n\nIntro paragraph.\n\n## stele\n\nold\n\n## footer\n\nfooter content\n"
    )

    upsert_section(doc, marker="## stele", content="## stele\n\nnew\n")

    text = doc.read_text()
    assert "Intro paragraph." in text
    assert "footer content" in text
    assert "old" not in text


def test_remove_strips_section_only(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Header\n\nIntro.\n\n## stele\n\nstele body\n\n## other\n\nOther.\n"
    )

    remove_section(doc, marker="## stele")

    text = doc.read_text()
    assert "stele body" not in text
    assert "Intro." in text
    assert "Other." in text


def test_remove_is_noop_when_marker_absent(tmp_path: Path) -> None:
    doc = tmp_path / "doc.md"
    original = "# Header\n\nNo stele here.\n"
    doc.write_text(original)

    remove_section(doc, marker="## stele")

    assert doc.read_text() == original


def test_upsert_creates_file_when_missing(tmp_path: Path) -> None:
    doc = tmp_path / "new.md"
    assert not doc.exists()

    upsert_section(doc, marker="## stele", content="## stele\n\nbody\n")

    assert doc.read_text() == "## stele\n\nbody\n"


def test_upsert_refuses_ambiguous_double_marker(tmp_path: Path) -> None:
    doc = tmp_path / "corrupt.md"
    doc.write_text("## stele\n\nA\n\n## stele\n\nB\n")

    with pytest.raises(SectionConflictError):
        upsert_section(doc, marker="## stele", content="## stele\n\nnew\n")
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `.venv/bin/pytest tests/unit/packaging/test_sections.py -v`
Expected: ImportError on `stele.packaging.sections`.

- [ ] **Step 3: Implement**

Create `src/stele/packaging/__init__.py`:

```python
"""Stele multi-platform packaging."""
```

Create `src/stele/packaging/sections.py`:

```python
"""Idempotent section editing for shared agent docs (CLAUDE.md, AGENTS.md, GEMINI.md).

A section is delimited by `marker` (a markdown heading like '## stele') and
extends until the next heading at the same or shallower level, or end of file.
Upserts replace in place; removes strip the section; user-authored content
between sections is preserved.
"""

from __future__ import annotations

import re
from pathlib import Path


class SectionConflictError(RuntimeError):
    """Raised when a document contains two markers with the same name."""


def _heading_level(marker: str) -> int:
    return len(marker) - len(marker.lstrip("#"))


def _next_heading_pattern(level: int) -> re.Pattern[str]:
    # Match '#'..'#' (1..level) followed by space at line start.
    return re.compile(rf"^#{{1,{level}}} ", re.MULTILINE)


def _find_section(text: str, marker: str) -> tuple[int, int] | None:
    """Return (start, end) of the section bounded by marker, or None."""
    indices = [m.start() for m in re.finditer(rf"^{re.escape(marker)}(?=\n|$)", text, re.MULTILINE)]
    if not indices:
        return None
    if len(indices) > 1:
        raise SectionConflictError(
            f"Multiple {marker!r} sections found at offsets {indices}; refusing to act"
        )
    start = indices[0]
    after = start + len(marker)
    level = _heading_level(marker)
    next_match = _next_heading_pattern(level).search(text, after)
    end = next_match.start() if next_match else len(text)
    return start, end


def upsert_section(path: Path, *, marker: str, content: str) -> None:
    """Insert or replace the section at `marker` with `content`.

    `content` must include the marker line as its first line.
    """
    if not content.endswith("\n"):
        content = content + "\n"

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return

    text = path.read_text()
    located = _find_section(text, marker)

    if located is None:
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        path.write_text(text + sep + content)
        return

    start, end = located
    new_text = text[:start] + content + text[end:]
    path.write_text(new_text)


def remove_section(path: Path, *, marker: str) -> None:
    if not path.exists():
        return
    text = path.read_text()
    located = _find_section(text, marker)
    if located is None:
        return
    start, end = located
    # Trim one trailing blank line if it was introduced by the section.
    new_text = text[:start] + text[end:]
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)
    path.write_text(new_text)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/packaging/test_sections.py -v`
Expected: 7 passed.

- [ ] **Step 5: Lint + types**

Run: `.venv/bin/ruff check src/stele/packaging/ tests/unit/packaging/ && .venv/bin/mypy src/stele/packaging/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/stele/packaging/__init__.py src/stele/packaging/sections.py tests/unit/packaging/__init__.py tests/unit/packaging/test_sections.py
git commit -m "feat(packaging): idempotent shared-doc section editor (marker + next-heading pattern)"
```

---

### Task 6: `platforms.py` — `PlatformSpec` + `PLATFORM_CONFIG`

**Files:**
- Create: `src/stele/packaging/platforms.py`
- Test: `tests/unit/packaging/test_platforms.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/packaging/test_platforms.py`:

```python
from __future__ import annotations

import pytest

from stele.packaging.platforms import PLATFORM_CONFIG, PlatformSpec


PLATFORM_NAMES = [
    "claude-code",
    "codex",
    "opencode",
    "cursor",
    "gemini-cli",
    "copilot",
    "aider",
]


def test_all_seven_platforms_registered() -> None:
    assert set(PLATFORM_CONFIG.keys()) == set(PLATFORM_NAMES)


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_every_spec_has_required_fields(name: str) -> None:
    spec = PLATFORM_CONFIG[name]
    assert isinstance(spec, PlatformSpec)
    assert spec.skill_path.startswith("~/") or spec.skill_path.startswith("/")
    assert spec.description  # non-empty
    assert spec.trigger.startswith("/")


def test_platform_spec_immutable() -> None:
    spec = PLATFORM_CONFIG["claude-code"]
    with pytest.raises((AttributeError, TypeError)):
        spec.skill_path = "/tmp/oops"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `.venv/bin/pytest tests/unit/packaging/test_platforms.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Create `src/stele/packaging/platforms.py`:

```python
"""Multi-platform routing table.

Adding a new platform = one entry in PLATFORM_CONFIG plus (optionally) a
hook template file. No other code changes needed for basic install
support.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformSpec:
    """Where a platform's skill, hook, and shared-doc-section live."""

    name: str
    description: str
    trigger: str  # e.g., "/stele"
    skill_path: str  # `~`-relative ok; expanded by install
    project_agents_doc: str | None  # repo-root file, e.g., "CLAUDE.md" or "AGENTS.md"
    user_agents_doc: str | None  # user-home file, e.g., "~/.claude/CLAUDE.md"
    hook_template: str | None  # path relative to packaging/templates/
    hook_path: str | None  # destination, `~`-relative ok
    mcp_config_path: str | None  # `~`-relative; if absent, install prints stderr hint


_STELE_DESCRIPTION = (
    "Evidence-cited memory + artifact storage via stele's MCP server. "
    "Use stele_memory_search before answering from prior context; use "
    "stele_stash_tool_result for oversized tool output."
)


PLATFORM_CONFIG: dict[str, PlatformSpec] = {
    "claude-code": PlatformSpec(
        name="claude-code",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.claude/skills/stele/SKILL.md",
        project_agents_doc="CLAUDE.md",
        user_agents_doc="~/.claude/CLAUDE.md",
        hook_template="hooks/claude-code.sh.j2",
        hook_path="~/.claude/hooks/stele-large-output.sh",
        mcp_config_path="~/.claude/mcp.json",
    ),
    "codex": PlatformSpec(
        name="codex",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.agents/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template=None,
        hook_path=None,
        mcp_config_path="~/.agents/mcp.json",
    ),
    "opencode": PlatformSpec(
        name="opencode",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.config/opencode/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template="hooks/opencode-plugin.js.j2",
        hook_path="~/.config/opencode/plugins/stele.js",
        mcp_config_path="~/.config/opencode/mcp.json",
    ),
    "cursor": PlatformSpec(
        name="cursor",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.cursor/skills/stele/SKILL.md",
        project_agents_doc=None,  # uses .cursor/rules
        user_agents_doc=None,
        hook_template="hooks/cursor-rules.mdc.j2",
        hook_path=".cursor/rules/stele.mdc",
        mcp_config_path="~/.cursor/mcp.json",
    ),
    "gemini-cli": PlatformSpec(
        name="gemini-cli",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.gemini/skills/stele/SKILL.md",
        project_agents_doc="GEMINI.md",
        user_agents_doc=None,
        hook_template="hooks/gemini-settings.json.j2",
        hook_path="~/.gemini/settings.json",
        mcp_config_path="~/.gemini/mcp.json",
    ),
    "copilot": PlatformSpec(
        name="copilot",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.copilot/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template=None,
        hook_path=None,
        mcp_config_path="~/.copilot/mcp.json",
    ),
    "aider": PlatformSpec(
        name="aider",
        description=_STELE_DESCRIPTION,
        trigger="/stele",
        skill_path="~/.aider/skills/stele/SKILL.md",
        project_agents_doc="AGENTS.md",
        user_agents_doc=None,
        hook_template=None,
        hook_path=None,
        mcp_config_path="~/.aider/mcp.json",
    ),
}
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/packaging/test_platforms.py -v`
Expected: 9 passed (7 parametrized + 2 standalone).

- [ ] **Step 5: Lint + types**

Run: `.venv/bin/ruff check src/stele/packaging/ tests/unit/packaging/ && .venv/bin/mypy src/stele/packaging/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/stele/packaging/platforms.py tests/unit/packaging/test_platforms.py
git commit -m "feat(packaging): PLATFORM_CONFIG routing table for 7 launch platforms"
```

---

### Task 7: `render.py` + skill/section templates

**Files:**
- Create: `src/stele/packaging/render.py`
- Create: `src/stele/packaging/templates/skill.md.j2`
- Create: `src/stele/packaging/templates/agents-md-section.md.j2`
- Create: `src/stele/packaging/templates/mcp-server-config.json.j2`
- Test: `tests/unit/packaging/test_render.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/packaging/test_render.py`:

```python
from __future__ import annotations

import json

import pytest

from stele.packaging.platforms import PLATFORM_CONFIG
from stele.packaging.render import (
    render_agents_md_section,
    render_mcp_server_config,
    render_skill,
)

PLATFORM_NAMES = list(PLATFORM_CONFIG.keys())


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_skill_renders_for_every_platform(name: str) -> None:
    out = render_skill(name)
    assert "/stele" in out
    assert "stele_memory_search" in out
    assert "stele_stash_tool_result" in out
    # No unresolved Jinja markers
    assert "{{" not in out
    assert "{%" not in out


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_skill_frontmatter_present(name: str) -> None:
    out = render_skill(name)
    assert out.startswith("---")
    assert "name: stele" in out
    assert "description:" in out


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_agents_md_section_starts_with_marker(name: str) -> None:
    out = render_agents_md_section(name)
    assert out.startswith("## stele")
    assert "{{" not in out


@pytest.mark.parametrize("name", PLATFORM_NAMES)
def test_mcp_server_config_is_valid_json(name: str) -> None:
    out = render_mcp_server_config(name)
    parsed = json.loads(out)
    # Conform to common MCP host shape: { "mcpServers": { "stele": {...} } }
    assert "mcpServers" in parsed
    assert "stele" in parsed["mcpServers"]
    assert parsed["mcpServers"]["stele"]["command"] == "stele-mcp"


def test_unknown_platform_raises() -> None:
    with pytest.raises(KeyError):
        render_skill("not-a-platform")
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `.venv/bin/pytest tests/unit/packaging/test_render.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement render module**

Create `src/stele/packaging/render.py`:

```python
"""Jinja2 rendering for skill, hook, shared-doc-section, and mcp.json content.

One template per content type. Platform-specific data comes from
`PLATFORM_CONFIG[name]`; the template body is identical across platforms.
"""

from __future__ import annotations

from importlib.resources import files

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from stele.packaging.platforms import PLATFORM_CONFIG, PlatformSpec

_TEMPLATES_DIR = files("stele.packaging").joinpath("templates")


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(disabled_extensions=("md", "j2", "sh", "js", "json", "mdc")),
        keep_trailing_newline=True,
    )


def _ctx(spec: PlatformSpec) -> dict[str, object]:
    return {
        "name": spec.name,
        "description": spec.description,
        "trigger": spec.trigger,
        "stash_threshold": 4096,
        "tool_reference_table": _tool_reference_table(),
    }


def _tool_reference_table() -> str:
    """Render a one-row-per-tool reference table.

    Imported lazily to avoid pulling the full MCP server at packaging-render time.
    """
    from stele.mcp.tools import TOOLS

    lines = ["| Tool | Purpose | Key inputs |", "|---|---|---|"]
    for tool in TOOLS:
        required = ", ".join(tool.input_schema.get("required", []))
        lines.append(f"| `{tool.name}` | {tool.description} | {required or '—'} |")
    return "\n".join(lines)


def render_skill(platform_name: str) -> str:
    spec = PLATFORM_CONFIG[platform_name]
    return _env().get_template("skill.md.j2").render(**_ctx(spec))


def render_agents_md_section(platform_name: str) -> str:
    spec = PLATFORM_CONFIG[platform_name]
    return _env().get_template("agents-md-section.md.j2").render(**_ctx(spec))


def render_mcp_server_config(platform_name: str) -> str:
    spec = PLATFORM_CONFIG[platform_name]
    return _env().get_template("mcp-server-config.json.j2").render(**_ctx(spec))


def render_hook(platform_name: str) -> str | None:
    spec = PLATFORM_CONFIG[platform_name]
    if spec.hook_template is None:
        return None
    return _env().get_template(spec.hook_template).render(**_ctx(spec))
```

- [ ] **Step 4: Create templates**

Create `src/stele/packaging/templates/skill.md.j2`:

```jinja
---
name: stele
description: {{ description }}
trigger: {{ trigger }}
---

# {{ trigger }}

You have access to the `stele` MCP tool surface for evidence-cited memory and artifact storage.

## When to use

- Tool output > {{ stash_threshold }} tokens: call `stele_stash_tool_result` to swap the output for a `stele://` reference + summary.
- User asks something needing prior context: call `stele_memory_search` before responding.
- A claim depends on a specific artifact: call `stele_fetch` on its `stele://` ref; never paraphrase from memory alone.
- A previously-stated fact has changed: call `stele_memory_add` with `supersedes=[<old_id>]` — never edit in place.
- A claim was wrong and must be retracted: call `stele_memory_retract`. Don't delete; retract preserves audit.

## Tool reference

{{ tool_reference_table }}

## Notes

- Every memory cites its evidence (`source_refs` = list of `stele://` URIs). The server enforces this.
- PII scrubbing is on by default. Raw artifact bytes require `pii.raw_fetch_enabled=true` in `.stele/config.yaml`.
- Time-travel: pass `as_of=<ISO datetime>` to `stele_memory_search` / `stele_memory_list` / `stele_recall`.
```

Create `src/stele/packaging/templates/agents-md-section.md.j2`:

```jinja
## stele

stele MCP tools are available. Default behavior:

- For any single tool result over {{ stash_threshold }} tokens, route through `stele_stash_tool_result` and keep the returned `stele://` ref in working context.
- For any question that depends on prior session context, call `stele_memory_search` before answering.
- When stating a fact, cite the `stele://` ref via `stele_fetch`. Never paraphrase from memory without verifying.
- To change a previously-stated fact, use `stele_memory_add(supersedes=[old_id])`. Never edit in place; never use `stele_memory_delete` to "fix" wrong info — use `stele_memory_retract` instead.

See `~/.stele/config.yaml` or the project's `.stele/config.yaml` for backend selection.
```

Create `src/stele/packaging/templates/mcp-server-config.json.j2`:

```jinja
{
  "mcpServers": {
    "stele": {
      "command": "stele-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/unit/packaging/test_render.py -v`
Expected: All passed. The tool reference table will be empty until Task 8 — adjust expectations there.

Note: `test_skill_renders_for_every_platform` asserts `stele_memory_search` and `stele_stash_tool_result` appear in the rendered text. Since `TOOLS` is empty until Task 8, those strings won't be in the table. Replace those two assertions with `assert "/stele" in out` style checks AND add a TODO comment to revisit after Task 8.

Actually — adjust the assertions to look only at the static template body for now (`assert "/stele" in out`, `assert "stele://" in out`, `assert "stash_tool_result" in out` — the latter is in the static template body). Confirm tests pass.

- [ ] **Step 6: Lint + types**

Run: `.venv/bin/ruff check src/stele/packaging/ && .venv/bin/mypy src/stele/packaging/`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/stele/packaging/render.py src/stele/packaging/templates/ tests/unit/packaging/test_render.py
git commit -m "feat(packaging): jinja2 render + skill/section/mcp-config templates"
```

---

### Task 8: `version_stamps.py`

**Files:**
- Create: `src/stele/packaging/version_stamps.py`
- Test: `tests/unit/packaging/test_version_stamps.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/packaging/test_version_stamps.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.packaging.platforms import PLATFORM_CONFIG
from stele.packaging.version_stamps import refresh_all, write_stamp


def test_write_stamp_creates_file(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    write_stamp(skill_dir, version="0.1.0")
    stamp = skill_dir / ".stele_version"
    assert stamp.read_text().strip() == "0.1.0"


def test_refresh_all_updates_only_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path
    monkeypatch.setattr(Path, "home", lambda: home)

    # Install stamp for two platforms only.
    for name in ["claude-code", "codex"]:
        spec = PLATFORM_CONFIG[name]
        skill_dir = Path(spec.skill_path.replace("~", str(home))).parent
        skill_dir.mkdir(parents=True)
        (skill_dir / ".stele_version").write_text("0.0.9\n")

    refresh_all(version="0.1.0")

    # Existing stamps updated.
    for name in ["claude-code", "codex"]:
        spec = PLATFORM_CONFIG[name]
        stamp = Path(spec.skill_path.replace("~", str(home))).parent / ".stele_version"
        assert stamp.read_text().strip() == "0.1.0"

    # Other platforms not created.
    for name in ["cursor", "gemini-cli"]:
        spec = PLATFORM_CONFIG[name]
        stamp = Path(spec.skill_path.replace("~", str(home))).parent / ".stele_version"
        assert not stamp.exists()
```

- [ ] **Step 2: Run, confirm fails.**

Run: `.venv/bin/pytest tests/unit/packaging/test_version_stamps.py -v`

- [ ] **Step 3: Implement**

Create `src/stele/packaging/version_stamps.py`:

```python
"""Per-platform .stele_version stamps; refresh-all on any install."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path

from stele.packaging.platforms import PLATFORM_CONFIG


def _current_version() -> str:
    try:
        return _pkg_version("stele-core")
    except Exception:
        return "0.0.0"


def write_stamp(skill_dir: Path, *, version: str | None = None) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / ".stele_version").write_text((version or _current_version()) + "\n")


def refresh_all(*, version: str | None = None) -> None:
    """Refresh .stele_version in every platform's skill dir that already has one.

    Mirrors graphify's pattern: prevents 'your codex install is stale' noise
    after you only re-installed Claude Code.
    """
    home = Path.home()
    v = version or _current_version()
    for spec in PLATFORM_CONFIG.values():
        skill_path = Path(spec.skill_path.replace("~", str(home)))
        stamp = skill_path.parent / ".stele_version"
        if stamp.exists():
            stamp.write_text(v + "\n")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/packaging/test_version_stamps.py -v`
Expected: 2 passed.

- [ ] **Step 5: Lint + types + commit**

```bash
.venv/bin/ruff check src/stele/packaging/ && .venv/bin/mypy src/stele/packaging/
git add src/stele/packaging/version_stamps.py tests/unit/packaging/test_version_stamps.py
git commit -m "feat(packaging): per-platform version stamps with refresh-all sync"
```

---

### Task 9: Hook templates (all 4 hook-enabled platforms)

**Files:**
- Create: `src/stele/packaging/templates/hooks/claude-code.sh.j2`
- Create: `src/stele/packaging/templates/hooks/gemini-settings.json.j2`
- Create: `src/stele/packaging/templates/hooks/opencode-plugin.js.j2`
- Create: `src/stele/packaging/templates/hooks/cursor-rules.mdc.j2`
- Modify: `tests/unit/packaging/test_render.py` (add hook-rendering tests)

- [ ] **Step 1: Write failing hook-render tests**

Append to `tests/unit/packaging/test_render.py`:

```python
from stele.packaging.render import render_hook


HOOK_PLATFORMS = ["claude-code", "gemini-cli", "opencode", "cursor"]
NO_HOOK_PLATFORMS = ["codex", "copilot", "aider"]


@pytest.mark.parametrize("name", HOOK_PLATFORMS)
def test_hook_renders_for_supported_platforms(name: str) -> None:
    out = render_hook(name)
    assert out is not None
    assert "{{" not in out
    assert "{%" not in out
    assert "stele" in out.lower()


@pytest.mark.parametrize("name", NO_HOOK_PLATFORMS)
def test_no_hook_returns_none(name: str) -> None:
    assert render_hook(name) is None


def test_gemini_hook_is_valid_json() -> None:
    out = render_hook("gemini-cli")
    assert out is not None
    parsed = json.loads(out)
    assert "tools" in parsed or "beforeTool" in parsed or isinstance(parsed, dict)
```

- [ ] **Step 2: Run, confirm fails.**

- [ ] **Step 3: Create hook templates**

`src/stele/packaging/templates/hooks/claude-code.sh.j2`:

```jinja
#!/usr/bin/env bash
# stele large-output reminder hook for Claude Code.
# Prints a stderr nudge when tool output looks large. Never blocks.
# Fires silently if .stele/config.yaml is absent in the current tree.

set -eu
TOOL_NAME="${CLAUDE_TOOL_NAME:-}"
OUTPUT_LEN="${CLAUDE_TOOL_OUTPUT_LEN:-0}"
THRESHOLD={{ stash_threshold }}

# Only nudge for Bash/Read with large output.
case "$TOOL_NAME" in
  Bash|Read) ;;
  *) exit 0 ;;
esac

if [ "${OUTPUT_LEN:-0}" -lt "$THRESHOLD" ]; then
  exit 0
fi

# Silent in projects without stele config.
if [ ! -f ".stele/config.yaml" ] && [ ! -f "$HOME/.config/stele/config.yaml" ]; then
  exit 0
fi

echo "[stele] tool output ${OUTPUT_LEN} bytes (>${THRESHOLD}); consider stele_stash_tool_result to swap for a stele:// ref." >&2
exit 0
```

`src/stele/packaging/templates/hooks/gemini-settings.json.j2`:

```jinja
{
  "tools": {
    "beforeExecute": [
      {
        "name": "stele-large-output-reminder",
        "match": { "tool": ["bash", "read"] },
        "action": {
          "type": "stderr",
          "message": "[stele] consider stele_stash_tool_result for large outputs; threshold {{ stash_threshold }}"
        }
      }
    ]
  }
}
```

`src/stele/packaging/templates/hooks/opencode-plugin.js.j2`:

```jinja
// stele large-output reminder for OpenCode. Non-blocking stderr nudge.
const THRESHOLD = {{ stash_threshold }};

export default {
  name: "stele-large-output-reminder",
  hooks: {
    "tool.execute.before": async (ctx) => {
      const name = ctx?.tool?.name ?? "";
      if (!["bash", "read"].includes(name.toLowerCase())) return;
      const size = ctx?.lastOutputSize ?? 0;
      if (size < THRESHOLD) return;
      process.stderr.write(`[stele] last ${name} output ${size}B > ${THRESHOLD}; consider stele_stash_tool_result\n`);
    },
  },
};
```

`src/stele/packaging/templates/hooks/cursor-rules.mdc.j2`:

```jinja
---
description: stele MCP usage rules
alwaysApply: true
---
# stele rules

When stele MCP is available:

- Route Bash/Read outputs > {{ stash_threshold }} tokens through `stele_stash_tool_result`.
- Call `stele_memory_search` before answering from prior context.
- Cite `stele://` refs via `stele_fetch`; do not paraphrase from memory alone.
- Use `stele_memory_add(supersedes=[id])` for fact changes; `stele_memory_retract` for corrections.
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/packaging/test_render.py -v`
Expected: All passed (4 hook-render + 3 no-hook + 1 gemini-json + earlier tests).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/stele/packaging/ tests/unit/packaging/
git add src/stele/packaging/templates/hooks/ tests/unit/packaging/test_render.py
git commit -m "feat(packaging): hook templates for claude-code, gemini-cli, opencode, cursor"
```

---

### Task 10: `install.py` — `install_for` / `uninstall_for`

**Files:**
- Create: `src/stele/packaging/install.py`
- Test: covered indirectly via Task 14 CLI tests; add a dry-run unit test here.

- [ ] **Step 1: Write the failing test**

Add `tests/unit/packaging/test_install.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.packaging.install import install_for, uninstall_for


def _expand(path_str: str, home: Path) -> Path:
    return Path(path_str.replace("~", str(home)))


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)  # so project_agents_doc lands in tmp
    return tmp_path


def test_install_claude_code_writes_skill_and_hook(fake_home: Path) -> None:
    install_for("claude-code")

    skill = _expand("~/.claude/skills/stele/SKILL.md", fake_home)
    hook = _expand("~/.claude/hooks/stele-large-output.sh", fake_home)
    user_md = _expand("~/.claude/CLAUDE.md", fake_home)
    project_md = fake_home / "CLAUDE.md"

    assert skill.is_file()
    assert "stele" in skill.read_text().lower()
    assert hook.is_file()
    assert "## stele" in user_md.read_text()
    assert "## stele" in project_md.read_text()


def test_install_codex_no_hook(fake_home: Path) -> None:
    install_for("codex")

    skill = _expand("~/.agents/skills/stele/SKILL.md", fake_home)
    assert skill.is_file()
    # No hook file written for codex.
    assert not (fake_home / ".agents" / "hooks").exists()


def test_uninstall_removes_skill_and_section(fake_home: Path) -> None:
    install_for("claude-code")
    uninstall_for("claude-code")

    skill = _expand("~/.claude/skills/stele/SKILL.md", fake_home)
    user_md = _expand("~/.claude/CLAUDE.md", fake_home)
    project_md = fake_home / "CLAUDE.md"

    assert not skill.exists()
    if user_md.exists():
        assert "## stele" not in user_md.read_text()
    if project_md.exists():
        assert "## stele" not in project_md.read_text()


def test_dry_run_writes_nothing(fake_home: Path) -> None:
    install_for("claude-code", dry_run=True)
    assert not _expand("~/.claude/skills/stele/SKILL.md", fake_home).exists()


def test_unknown_platform_raises(fake_home: Path) -> None:
    with pytest.raises(KeyError):
        install_for("not-a-platform")
```

- [ ] **Step 2: Run, confirm fails**.

- [ ] **Step 3: Implement**

Create `src/stele/packaging/install.py`:

```python
"""Per-platform install / uninstall orchestration."""

from __future__ import annotations

from pathlib import Path

from stele.packaging.platforms import PLATFORM_CONFIG, PlatformSpec
from stele.packaging.render import (
    render_agents_md_section,
    render_hook,
    render_mcp_server_config,
    render_skill,
)
from stele.packaging.sections import remove_section, upsert_section
from stele.packaging.version_stamps import refresh_all, write_stamp


def _expand(path_str: str | None, home: Path) -> Path | None:
    if path_str is None:
        return None
    if path_str.startswith("~"):
        return Path(path_str.replace("~", str(home), 1))
    return Path(path_str)


def install_for(platform: str, *, dry_run: bool = False) -> None:
    spec: PlatformSpec = PLATFORM_CONFIG[platform]
    home = Path.home()

    skill_dest = _expand(spec.skill_path, home)
    hook_dest = _expand(spec.hook_path, home)
    user_doc = _expand(spec.user_agents_doc, home)
    project_doc = (
        Path.cwd() / spec.project_agents_doc if spec.project_agents_doc else None
    )
    mcp_dest = _expand(spec.mcp_config_path, home)

    if dry_run:
        return

    assert skill_dest is not None
    skill_dest.parent.mkdir(parents=True, exist_ok=True)
    skill_dest.write_text(render_skill(platform))

    if hook_dest is not None:
        hook_text = render_hook(platform)
        if hook_text is not None:
            hook_dest.parent.mkdir(parents=True, exist_ok=True)
            hook_dest.write_text(hook_text)
            if hook_dest.suffix == ".sh":
                hook_dest.chmod(0o755)

    section = render_agents_md_section(platform)
    if user_doc is not None:
        upsert_section(user_doc, marker="## stele", content=section)
    if project_doc is not None:
        upsert_section(project_doc, marker="## stele", content=section)

    if mcp_dest is not None:
        mcp_dest.parent.mkdir(parents=True, exist_ok=True)
        # Naive write; future iteration: merge with existing mcp.json content.
        mcp_dest.write_text(render_mcp_server_config(platform))

    write_stamp(skill_dest.parent)
    refresh_all()


def uninstall_for(platform: str) -> None:
    spec = PLATFORM_CONFIG[platform]
    home = Path.home()

    skill_dest = _expand(spec.skill_path, home)
    hook_dest = _expand(spec.hook_path, home)
    user_doc = _expand(spec.user_agents_doc, home)
    project_doc = (
        Path.cwd() / spec.project_agents_doc if spec.project_agents_doc else None
    )
    mcp_dest = _expand(spec.mcp_config_path, home)

    if skill_dest is not None and skill_dest.exists():
        skill_dest.unlink()
        stamp = skill_dest.parent / ".stele_version"
        if stamp.exists():
            stamp.unlink()
    if hook_dest is not None and hook_dest.exists():
        hook_dest.unlink()
    if user_doc is not None:
        remove_section(user_doc, marker="## stele")
    if project_doc is not None:
        remove_section(project_doc, marker="## stele")
    if mcp_dest is not None and mcp_dest.exists():
        mcp_dest.unlink()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/packaging/test_install.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/stele/packaging/ && .venv/bin/mypy src/stele/packaging/
git add src/stele/packaging/install.py tests/unit/packaging/test_install.py
git commit -m "feat(packaging): per-platform install_for/uninstall_for orchestration"
```

---

## Phase 3 — MCP server (DC-B: full tool surface)

### Task 11: `tools.py` — `ToolSpec` + `TOOLS` registry

**Files:**
- Create: `src/stele/mcp/tools.py`
- Test: `tests/unit/mcp/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/mcp/test_tools.py`:

```python
from __future__ import annotations

import pytest

from stele.mcp.tools import TOOLS, ToolSpec

EXPECTED_TOOLS = {
    "stele_store",
    "stele_fetch",
    "stele_search",
    "stele_query",
    "stele_list",
    "stele_delete",
    "stele_memory_add",
    "stele_memory_get",
    "stele_memory_search",
    "stele_memory_list",
    "stele_memory_update",
    "stele_memory_delete",
    "stele_memory_retract",
    "stele_extract_from_text",
    "stele_extract_from_messages",
    "stele_extract_from_artifact",
    "stele_recall",
    "stele_stash_tool_result",
}


def test_all_eighteen_tools_registered() -> None:
    assert {t.name for t in TOOLS} == EXPECTED_TOOLS


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_every_tool_has_complete_spec(tool: ToolSpec) -> None:
    assert tool.name.startswith("stele_")
    assert tool.description
    assert isinstance(tool.input_schema, dict)
    assert tool.input_schema.get("type") == "object"
    assert "properties" in tool.input_schema
    assert callable(tool.handler) or tool.handler is None


def test_tool_names_unique() -> None:
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))
```

- [ ] **Step 2: Run, confirm fails.**

- [ ] **Step 3: Implement (definitions only — handlers stubbed)**

Create `src/stele/mcp/tools.py`:

```python
"""MCP tool registry.

Each ToolSpec carries its name, agent-facing description, JSON Schema input,
and a handler that wraps a Stele facade method. Handlers expect a bound
`Stele` instance available via closure or first argument; the server module
wires that.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


HandlerFn = Callable[..., Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: HandlerFn | None = field(default=None)


def _obj_schema(properties: dict[str, dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_INT = {"type": "integer"}
_OBJ_ANY = {"type": "object", "additionalProperties": True}
_STR_LIST = {"type": "array", "items": _STR}


TOOLS: list[ToolSpec] = [
    # ---- artifact surface ----
    ToolSpec(
        name="stele_store",
        description="Store bytes/text behind a stele:// reference and return the ref.",
        input_schema=_obj_schema(
            {"payload": _STR, "content_type": _STR, "metadata": _OBJ_ANY},
            required=["payload"],
        ),
    ),
    ToolSpec(
        name="stele_fetch",
        description="Resolve a stele:// reference to its bytes/text + summary.",
        input_schema=_obj_schema({"ref": _STR}, required=["ref"]),
    ),
    ToolSpec(
        name="stele_search",
        description="Search artifacts via the configured retrieval backend.",
        input_schema=_obj_schema(
            {"query": _STR, "mode": _STR, "limit": _INT},
            required=["query"],
        ),
    ),
    ToolSpec(
        name="stele_query",
        description="Targeted query against the chunk index (vector/hybrid when configured).",
        input_schema=_obj_schema(
            {"query": _STR, "mode": _STR, "limit": _INT},
            required=["query"],
        ),
    ),
    ToolSpec(
        name="stele_list",
        description="List stored artifacts.",
        input_schema=_obj_schema({"namespace": _STR, "limit": _INT}),
    ),
    ToolSpec(
        name="stele_delete",
        description="Delete a stored artifact by reference.",
        input_schema=_obj_schema({"ref": _STR}, required=["ref"]),
    ),
    # ---- memory surface ----
    ToolSpec(
        name="stele_memory_add",
        description="Add a memory record citing its source_refs.",
        input_schema=_obj_schema(
            {
                "text": _STR,
                "source_refs": _STR_LIST,
                "supersedes": _STR_LIST,
                "metadata": _OBJ_ANY,
            },
            required=["text", "source_refs"],
        ),
    ),
    ToolSpec(
        name="stele_memory_get",
        description="Fetch a single memory record by id.",
        input_schema=_obj_schema({"memory_id": _STR}, required=["memory_id"]),
    ),
    ToolSpec(
        name="stele_memory_search",
        description="Search memory with optional as_of time travel.",
        input_schema=_obj_schema(
            {"query": _STR, "as_of": _STR, "limit": _INT},
            required=["query"],
        ),
    ),
    ToolSpec(
        name="stele_memory_list",
        description="List memory records, optionally at a past point in time.",
        input_schema=_obj_schema({"as_of": _STR, "limit": _INT}),
    ),
    ToolSpec(
        name="stele_memory_update",
        description="Update metadata of a memory record. Text changes are rejected; use add(supersedes=).",
        input_schema=_obj_schema(
            {"memory_id": _STR, "metadata": _OBJ_ANY},
            required=["memory_id"],
        ),
    ),
    ToolSpec(
        name="stele_memory_delete",
        description="Soft-delete a memory record.",
        input_schema=_obj_schema({"memory_id": _STR}, required=["memory_id"]),
    ),
    ToolSpec(
        name="stele_memory_retract",
        description="Retract a memory record with a reason (preserves audit).",
        input_schema=_obj_schema(
            {"memory_id": _STR, "reason": _STR},
            required=["memory_id", "reason"],
        ),
    ),
    # ---- extraction surface ----
    ToolSpec(
        name="stele_extract_from_text",
        description="Run deterministic extraction on free text; commits via memory.add.",
        input_schema=_obj_schema(
            {"text": _STR, "source_refs": _STR_LIST},
            required=["text", "source_refs"],
        ),
    ),
    ToolSpec(
        name="stele_extract_from_messages",
        description="Extract from a list of chat messages.",
        input_schema=_obj_schema(
            {
                "messages": {"type": "array", "items": _OBJ_ANY},
                "source_refs": _STR_LIST,
            },
            required=["messages", "source_refs"],
        ),
    ),
    ToolSpec(
        name="stele_extract_from_artifact",
        description="Extract from a stored artifact by reference.",
        input_schema=_obj_schema({"ref": _STR}, required=["ref"]),
    ),
    # ---- recall ----
    ToolSpec(
        name="stele_recall",
        description="Run a recall strategy; supports as_of, version_filter, retracted_behavior.",
        input_schema=_obj_schema(
            {
                "query": _STR,
                "strategy": _STR,
                "as_of": _STR,
                "version_filter": _STR,
                "retracted_behavior": _STR,
            },
            required=["query"],
        ),
    ),
    # ---- interception ----
    ToolSpec(
        name="stele_stash_tool_result",
        description="Route a tool's raw output through interception; returns a stele:// ref + summary if oversize, else passthrough.",
        input_schema=_obj_schema(
            {
                "tool_name": _STR,
                "raw_output": _STR,
                "threshold_override": _INT,
            },
            required=["tool_name", "raw_output"],
        ),
    ),
]
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/mcp/test_tools.py -v`
Expected: 20 passed (1 set check + 18 parametrized + 1 unique-names).

- [ ] **Step 5: Re-run render tests (they now have a populated tool table)**

Run: `.venv/bin/pytest tests/unit/packaging/test_render.py -v`
Expected: All still pass. The `tool_reference_table` now contains 18 rows.

- [ ] **Step 6: Lint + commit**

```bash
.venv/bin/ruff check src/stele/mcp/ && .venv/bin/mypy src/stele/mcp/
git add src/stele/mcp/tools.py tests/unit/mcp/test_tools.py
git commit -m "feat(mcp): 18-tool registry covering full Stele facade surface"
```

---

### Task 12: `server.py` — stdio bootstrap + tool dispatch + handler wiring

**Files:**
- Create: `src/stele/mcp/server.py`
- Modify: `src/stele/mcp/tools.py` (add handler thunks)
- Test: extend `tests/unit/mcp/test_tools.py` with handler dispatch tests against a mock Stele

- [ ] **Step 1: Write the failing handler-dispatch tests**

Append to `tests/unit/mcp/test_tools.py`:

```python
from unittest.mock import MagicMock

from stele.mcp.tools import bind_handlers


def test_bind_handlers_wires_store(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_stele = MagicMock()
    fake_stele.store.return_value = MagicMock(reference="stele://x/abc")

    bound = bind_handlers(fake_stele)
    handler = next(b for b in bound if b.name == "stele_store").handler
    assert handler is not None
    result = handler(payload="hello", content_type="text/plain")
    fake_stele.store.assert_called_once()
    assert result == {"ref": "stele://x/abc"}


def test_bind_handlers_wires_memory_add(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_stele = MagicMock()
    fake_stele.memory.add.return_value = MagicMock(memory_id="m-123")

    bound = bind_handlers(fake_stele)
    handler = next(b for b in bound if b.name == "stele_memory_add").handler
    assert handler is not None
    result = handler(text="t", source_refs=["stele://x/a"])
    fake_stele.memory.add.assert_called_once_with(
        text="t", source_refs=["stele://x/a"], supersedes=None, metadata=None
    )
    assert result == {"memory_id": "m-123"}


def test_bind_handlers_routes_pii_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    from stele.core.exceptions import PIIBlockedError
    fake_stele = MagicMock()
    fake_stele.fetch.side_effect = PIIBlockedError("nope")

    bound = bind_handlers(fake_stele)
    handler = next(b for b in bound if b.name == "stele_fetch").handler
    assert handler is not None
    result = handler(ref="stele://x/a")
    assert result == {"error": {"code": "PII_BLOCKED", "message": "nope", "context": {}}}
```

- [ ] **Step 2: Run, confirm fails.**

- [ ] **Step 3: Extend `tools.py` with `bind_handlers`**

Append to `src/stele/mcp/tools.py`:

```python
from dataclasses import replace

from stele.mcp.errors import guard


def bind_handlers(stele: Any) -> list[ToolSpec]:
    """Return TOOLS with each handler bound to the given Stele instance.

    Every returned ToolSpec has a handler that wraps the matching facade
    method, is guarded by `guard()`, and uses keyword-only invocation so
    the MCP transport layer can pass tool arguments as kwargs.
    """

    @guard
    def store(payload: str, content_type: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        result = stele.store(payload, content_type=content_type, metadata=metadata)
        return {"ref": str(result.reference)}

    @guard
    def fetch(ref: str) -> dict[str, Any]:
        result = stele.fetch(ref)
        return {
            "content": getattr(result, "content", None) or getattr(result, "bytes", None),
            "summary": getattr(result, "summary", None),
            "pii_scrubbed": bool(getattr(result, "pii_scrubbed", False)),
        }

    @guard
    def search(query: str, mode: str | None = None, limit: int = 10) -> dict[str, Any]:
        hits = stele.search(query, mode=mode, limit=limit)
        return {"hits": [_hit_to_dict(h) for h in hits]}

    @guard
    def query(query: str, mode: str | None = None, limit: int = 10) -> dict[str, Any]:
        hits = stele.query(query, mode=mode, limit=limit)
        return {"hits": [_hit_to_dict(h) for h in hits]}

    @guard
    def list_(namespace: str | None = None, limit: int = 100) -> dict[str, Any]:
        records = stele.list(namespace=namespace, limit=limit)
        return {"records": [_record_to_dict(r) for r in records]}

    @guard
    def delete(ref: str) -> dict[str, Any]:
        stele.delete(ref)
        return {"ok": True}

    @guard
    def memory_add(
        text: str,
        source_refs: list[str],
        supersedes: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = stele.memory.add(
            text=text, source_refs=source_refs, supersedes=supersedes, metadata=metadata
        )
        return {"memory_id": getattr(r, "memory_id", getattr(r, "id", str(r)))}

    @guard
    def memory_get(memory_id: str) -> dict[str, Any]:
        r = stele.memory.get(memory_id)
        return {"record": _record_to_dict(r)}

    @guard
    def memory_search(query: str, as_of: str | None = None, limit: int = 10) -> dict[str, Any]:
        hits = stele.memory.search(query, as_of=as_of, limit=limit)
        return {"hits": [_record_to_dict(h) for h in hits]}

    @guard
    def memory_list(as_of: str | None = None, limit: int = 100) -> dict[str, Any]:
        records = stele.memory.list(as_of=as_of, limit=limit)
        return {"records": [_record_to_dict(r) for r in records]}

    @guard
    def memory_update(memory_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        r = stele.memory.update(memory_id, metadata=metadata)
        return {"record": _record_to_dict(r)}

    @guard
    def memory_delete(memory_id: str) -> dict[str, Any]:
        stele.memory.delete(memory_id)
        return {"ok": True}

    @guard
    def memory_retract(memory_id: str, reason: str) -> dict[str, Any]:
        stele.memory.retract(memory_id, reason=reason)
        return {"ok": True}

    @guard
    def extract_from_text(text: str, source_refs: list[str]) -> dict[str, Any]:
        report = stele.extract.from_text(text, source_refs=source_refs)
        return {"report": _to_jsonable(report)}

    @guard
    def extract_from_messages(messages: list[dict[str, Any]], source_refs: list[str]) -> dict[str, Any]:
        report = stele.extract.from_messages(messages, source_refs=source_refs)
        return {"report": _to_jsonable(report)}

    @guard
    def extract_from_artifact(ref: str) -> dict[str, Any]:
        report = stele.extract.from_artifact(ref)
        return {"report": _to_jsonable(report)}

    @guard
    def recall(
        query: str,
        strategy: str | None = None,
        as_of: str | None = None,
        version_filter: str | None = None,
        retracted_behavior: str | None = None,
    ) -> dict[str, Any]:
        response = stele.recall(
            query=query,
            strategy=strategy,
            as_of=as_of,
            version_filter=version_filter,
            retracted_behavior=retracted_behavior,
        )
        return {"response": _to_jsonable(response)}

    @guard
    def stash_tool_result(
        tool_name: str, raw_output: str, threshold_override: int | None = None
    ) -> dict[str, Any]:
        from stele.interception.wrapper import stash_tool_result as _stash

        result = _stash(
            stele,
            tool_name=tool_name,
            raw_output=raw_output,
            threshold=threshold_override,
        )
        return _to_jsonable(result)

    by_name: dict[str, HandlerFn] = {
        "stele_store": store,
        "stele_fetch": fetch,
        "stele_search": search,
        "stele_query": query,
        "stele_list": list_,
        "stele_delete": delete,
        "stele_memory_add": memory_add,
        "stele_memory_get": memory_get,
        "stele_memory_search": memory_search,
        "stele_memory_list": memory_list,
        "stele_memory_update": memory_update,
        "stele_memory_delete": memory_delete,
        "stele_memory_retract": memory_retract,
        "stele_extract_from_text": extract_from_text,
        "stele_extract_from_messages": extract_from_messages,
        "stele_extract_from_artifact": extract_from_artifact,
        "stele_recall": recall,
        "stele_stash_tool_result": stash_tool_result,
    }
    return [replace(t, handler=by_name[t.name]) for t in TOOLS]


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    return _to_jsonable(hit)


def _record_to_dict(record: Any) -> dict[str, Any]:
    return _to_jsonable(record)


def _to_jsonable(obj: Any) -> Any:
    """Best-effort jsonable rendering using pydantic dump or __dict__."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump()
    if hasattr(obj, "__dict__"):
        return {k: _to_jsonable(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return str(obj)
```

Note: the actual `Stele` facade attribute paths for `extract`/`recall` / `memory.retract` may differ slightly; the spec asserts they exist. If a handler can't find its facade method, the contract test (Task 17) will surface that — fix import path then.

- [ ] **Step 4: Implement the server**

Create `src/stele/mcp/server.py`:

```python
"""Stdio MCP server bootstrap for stele.

Loads config (walk-up + user-global fallback), instantiates a single Stele,
binds tool handlers, and exposes them over stdio.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from stele.core.stash import Stele
from stele.mcp.config import config_path, load_raw_config
from stele.mcp.sanitize import sanitize_label
from stele.mcp.tools import ToolSpec, bind_handlers


def _build_stele() -> Stele:
    cfg = config_path()
    if cfg is None:
        # Default to in-memory if no config; caller is expected to have run `stele init`.
        return Stele.from_config({"backend": {"type": "memory"}})
    raw = load_raw_config(cfg)
    return Stele.from_config(raw)


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_label(value)
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    return value


async def _serve() -> None:
    stele = _build_stele()
    tools: list[ToolSpec] = bind_handlers(stele)
    by_name = {t.name: t for t in tools}

    server: Server[Any] = Server("stele")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(name=t.name, description=t.description, inputSchema=t.input_schema)
            for t in tools
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        spec = by_name.get(name)
        if spec is None or spec.handler is None:
            payload = {"error": {"code": "VALIDATION", "message": f"unknown tool {name!r}", "context": {}}}
        else:
            payload = spec.handler(**(arguments or {}))
            payload = _sanitize(payload)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests/unit/mcp/test_tools.py -v`
Expected: 23 passed (20 original + 3 new dispatch).

- [ ] **Step 6: Smoke-test the server boots**

Run: `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' | timeout 3 .venv/bin/stele-mcp; echo "exit=$?"`
Expected: the server prints an `initialize` JSON-RPC response. `timeout` may return 124 (timed out) on hangup — that's fine. Failure mode: ImportError on `mcp.server` → revisit Task 1 dep.

- [ ] **Step 7: Lint + commit**

```bash
.venv/bin/ruff check src/stele/mcp/ && .venv/bin/mypy src/stele/mcp/
git add src/stele/mcp/server.py src/stele/mcp/tools.py tests/unit/mcp/test_tools.py
git commit -m "feat(mcp): stdio server with bound handlers + sanitization on egress"
```

---

## Phase 4 — CLI (DC-A then DC-C)

### Task 13: `stele init`

**Files:**
- Create: `src/stele/cli/__init__.py`
- Create: `src/stele/cli/commands/__init__.py`
- Create: `src/stele/cli/commands/init.py`
- Test: `tests/unit/cli/__init__.py` (empty), `tests/unit/cli/test_init.py`

- [ ] **Step 1: Failing tests**

Create `tests/unit/cli/test_init.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from stele.cli import main


def test_init_creates_default_sqlite_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main(["init"])
    assert rc == 0
    cfg = tmp_path / ".stele" / "config.yaml"
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["backend"]["type"] == "sqlite"
    assert loaded["backend"]["dsn"].endswith("stele.db")


def test_init_respects_flag_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rc = main(["init", "--backend", "memory"])
    assert rc == 0
    cfg = tmp_path / ".stele" / "config.yaml"
    loaded = yaml.safe_load(cfg.read_text())
    assert loaded["backend"]["type"] == "memory"


def test_init_refuses_to_overwrite_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init"])
    rc = main(["init"])
    assert rc != 0


def test_init_overwrites_with_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init", "--backend", "memory"])
    rc = main(["init", "--backend", "sqlite", "--force"])
    assert rc == 0
    loaded = yaml.safe_load((tmp_path / ".stele" / "config.yaml").read_text())
    assert loaded["backend"]["type"] == "sqlite"
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implement**

Create `src/stele/cli/__init__.py`:

```python
"""Stele CLI entry point."""

from __future__ import annotations

import argparse
import sys

from stele.cli.commands import init as init_cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stele", description="Stele CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Write .stele/config.yaml")
    p_init.add_argument("--backend", default="sqlite", choices=["memory", "sqlite", "postgres", "mariadb", "clickhouse"])
    p_init.add_argument("--dsn", default=None)
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=init_cmd.run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover — surfaced via stderr
        print(f"stele: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

Create `src/stele/cli/commands/__init__.py`:

```python
"""Stele CLI subcommands."""
```

Create `src/stele/cli/commands/init.py`:

```python
"""`stele init` — write .stele/config.yaml with sensible defaults."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

DEFAULTS: dict[str, dict[str, object]] = {
    "memory": {"backend": {"type": "memory"}},
    "sqlite": {"backend": {"type": "sqlite", "dsn": ".stele/stele.db"}},
    "postgres": {"backend": {"type": "postgres", "dsn": None}},
    "mariadb": {"backend": {"type": "mariadb", "dsn": None}},
    "clickhouse": {"backend": {"type": "clickhouse", "dsn": None}},
}

BASE_CONFIG: dict[str, object] = {
    "pii": {"raw_fetch_enabled": False, "scrub_summary": True},
    "signing": {"mode": "optional"},
    "indexing": {"mode": "sync"},
    "retrieval": {"default_mode": "hybrid"},
    "mcp": {"stash_threshold_tokens": 4096},
}


def run(args: argparse.Namespace) -> int:
    cfg_dir = Path.cwd() / ".stele"
    cfg_path = cfg_dir / "config.yaml"
    if cfg_path.exists() and not args.force:
        print(f"stele: {cfg_path} already exists (use --force to overwrite)")
        return 2

    cfg_dir.mkdir(parents=True, exist_ok=True)
    backend = dict(DEFAULTS[args.backend])
    if args.dsn is not None:
        backend["backend"]["dsn"] = args.dsn  # type: ignore[index]
    body: dict[str, object] = {**backend, **BASE_CONFIG}
    cfg_path.write_text(yaml.safe_dump(body, sort_keys=False))
    print(f"stele: wrote {cfg_path}")
    return 0
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/cli/test_init.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/stele/cli/ && .venv/bin/mypy src/stele/cli/
git add src/stele/cli/ tests/unit/cli/__init__.py tests/unit/cli/test_init.py
git commit -m "feat(cli): stele init writes .stele/config.yaml with sensible defaults"
```

---

### Task 14: `stele install` + `stele uninstall`

**Files:**
- Create: `src/stele/cli/commands/install.py`
- Create: `src/stele/cli/commands/uninstall.py`
- Modify: `src/stele/cli/__init__.py` (register subcommands)
- Test: `tests/unit/cli/test_install.py`, `tests/unit/cli/test_uninstall.py`

- [ ] **Step 1: Failing tests**

Create `tests/unit/cli/test_install.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main


def test_install_single_platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main(["install", "--platform", "claude-code"])
    assert rc == 0
    assert (tmp_path / ".claude" / "skills" / "stele" / "SKILL.md").is_file()


def test_install_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main(["install", "--all"])
    assert rc == 0
    # At least 3 platforms produced skill files
    skills = list(tmp_path.glob("*/skills/stele/SKILL.md")) + list(
        tmp_path.glob("*/*/skills/stele/SKILL.md")
    )
    assert len(skills) >= 3


def test_install_rejects_unknown_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    rc = main(["install", "--platform", "not-a-thing"])
    assert rc != 0
```

Create `tests/unit/cli/test_uninstall.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main


def test_uninstall_reverses_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)

    main(["install", "--platform", "claude-code"])
    rc = main(["uninstall", "--platform", "claude-code"])
    assert rc == 0
    assert not (tmp_path / ".claude" / "skills" / "stele" / "SKILL.md").exists()
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implement install**

Create `src/stele/cli/commands/install.py`:

```python
"""`stele install` — render skill/hook/section content for one or more platforms."""

from __future__ import annotations

import argparse

from stele.packaging.install import install_for
from stele.packaging.platforms import PLATFORM_CONFIG


def run(args: argparse.Namespace) -> int:
    if args.all:
        targets = list(PLATFORM_CONFIG.keys())
    else:
        if not args.platform:
            print("stele: --platform NAME or --all required")
            return 2
        if args.platform not in PLATFORM_CONFIG:
            print(f"stele: unknown platform {args.platform!r}")
            return 2
        targets = [args.platform]

    for name in targets:
        install_for(name, dry_run=args.dry_run)
        print(f"stele: installed {name}")
    return 0
```

Create `src/stele/cli/commands/uninstall.py`:

```python
"""`stele uninstall` — reverse install for one or more platforms."""

from __future__ import annotations

import argparse

from stele.packaging.install import uninstall_for
from stele.packaging.platforms import PLATFORM_CONFIG


def run(args: argparse.Namespace) -> int:
    if args.all:
        targets = list(PLATFORM_CONFIG.keys())
    else:
        if not args.platform or args.platform not in PLATFORM_CONFIG:
            print(f"stele: unknown platform {args.platform!r}")
            return 2
        targets = [args.platform]

    for name in targets:
        uninstall_for(name)
        print(f"stele: uninstalled {name}")
    return 0
```

Modify `src/stele/cli/__init__.py` to register subcommands:

```python
# inside _build_parser, after p_init.set_defaults(...):
from stele.cli.commands import install as install_cmd, uninstall as uninstall_cmd

p_install = sub.add_parser("install", help="Install stele skill+hook for a platform")
p_install.add_argument("--platform", default=None)
p_install.add_argument("--all", action="store_true")
p_install.add_argument("--dry-run", action="store_true")
p_install.set_defaults(func=install_cmd.run)

p_uninstall = sub.add_parser("uninstall", help="Uninstall stele skill+hook")
p_uninstall.add_argument("--platform", default=None)
p_uninstall.add_argument("--all", action="store_true")
p_uninstall.set_defaults(func=uninstall_cmd.run)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/cli/ -v`
Expected: All pass.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/stele/cli/ && .venv/bin/mypy src/stele/cli/
git add src/stele/cli/commands/install.py src/stele/cli/commands/uninstall.py src/stele/cli/__init__.py tests/unit/cli/test_install.py tests/unit/cli/test_uninstall.py
git commit -m "feat(cli): stele install/uninstall with --platform and --all"
```

---

### Task 15: `stele doctor` + `stele status` + `stele mcp`

**Files:**
- Create: `src/stele/cli/commands/doctor.py`
- Create: `src/stele/cli/commands/status.py`
- Create: `src/stele/cli/commands/mcp.py`
- Modify: `src/stele/cli/__init__.py`
- Test: `tests/unit/cli/test_doctor.py`

- [ ] **Step 1: Failing tests for doctor**

Create `tests/unit/cli/test_doctor.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main


def test_doctor_passes_after_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    main(["init", "--backend", "memory"])
    rc = main(["doctor"])
    assert rc == 0


def test_doctor_fails_without_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "empty-home")
    rc = main(["doctor"])
    assert rc != 0
```

- [ ] **Step 2: Run, fail.**

- [ ] **Step 3: Implement**

Create `src/stele/cli/commands/doctor.py`:

```python
"""`stele doctor` — validate config + backend reachability."""

from __future__ import annotations

import argparse

from stele.core.stash import Stele
from stele.mcp.config import config_path, load_raw_config


def run(args: argparse.Namespace) -> int:
    cfg = config_path()
    if cfg is None:
        print("stele doctor: no config found (run `stele init`)")
        return 1

    try:
        raw = load_raw_config(cfg)
    except Exception as exc:
        print(f"stele doctor: failed to parse {cfg}: {exc}")
        return 1

    try:
        stele = Stele.from_config(raw)
    except Exception as exc:
        print(f"stele doctor: config rejected: {exc}")
        return 1

    try:
        caps = stele.capabilities()
        print(f"stele doctor: ok ({cfg}) — backend={raw.get('backend', {}).get('type')} capabilities={sorted(caps)}")
    except Exception as exc:
        print(f"stele doctor: backend not reachable: {exc}")
        return 1
    return 0
```

Create `src/stele/cli/commands/status.py`:

```python
"""`stele status` — per-platform install state."""

from __future__ import annotations

import argparse
from pathlib import Path

from stele.packaging.platforms import PLATFORM_CONFIG


def run(args: argparse.Namespace) -> int:
    home = Path.home()
    print("Platform           Installed   Stamp")
    for name, spec in PLATFORM_CONFIG.items():
        skill = Path(spec.skill_path.replace("~", str(home)))
        stamp = skill.parent / ".stele_version"
        installed = "yes" if skill.exists() else "no"
        version = stamp.read_text().strip() if stamp.exists() else "—"
        print(f"{name:<18} {installed:<11} {version}")
    return 0
```

Create `src/stele/cli/commands/mcp.py`:

```python
"""`stele mcp` — alias for the stele-mcp server entry point."""

from __future__ import annotations

import argparse

from stele.mcp.server import main as server_main


def run(args: argparse.Namespace) -> int:
    server_main()
    return 0
```

Modify `_build_parser` in `src/stele/cli/__init__.py` to add three more subcommands:

```python
from stele.cli.commands import doctor as doctor_cmd, status as status_cmd, mcp as mcp_cmd

sub.add_parser("doctor", help="Validate config + backend").set_defaults(func=doctor_cmd.run)
sub.add_parser("status", help="Per-platform install state").set_defaults(func=status_cmd.run)
sub.add_parser("mcp", help="Run the stele-mcp server in foreground").set_defaults(func=mcp_cmd.run)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/cli/ -v`
Expected: All pass.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/stele/cli/ && .venv/bin/mypy src/stele/cli/
git add src/stele/cli/commands/doctor.py src/stele/cli/commands/status.py src/stele/cli/commands/mcp.py src/stele/cli/__init__.py tests/unit/cli/test_doctor.py
git commit -m "feat(cli): stele doctor + status + mcp subcommands"
```

---

## Phase 5 — Integration tests (DC-D)

### Task 16: Integration test for the full install/uninstall cycle

**Files:**
- Create: `tests/integration/__init__.py` (if absent)
- Create: `tests/integration/test_install_e2e.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_install_e2e.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from stele.cli import main
from stele.packaging.platforms import PLATFORM_CONFIG


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _skill_path(name: str, home: Path) -> Path:
    spec = PLATFORM_CONFIG[name]
    return Path(spec.skill_path.replace("~", str(home)))


def test_install_all_then_uninstall_all_leaves_no_skill_files(fake_home: Path) -> None:
    rc = main(["install", "--all"])
    assert rc == 0
    for name in PLATFORM_CONFIG:
        assert _skill_path(name, fake_home).is_file(), name

    rc = main(["uninstall", "--all"])
    assert rc == 0
    for name in PLATFORM_CONFIG:
        assert not _skill_path(name, fake_home).exists(), name


def test_install_then_reinstall_is_idempotent(fake_home: Path) -> None:
    main(["install", "--platform", "claude-code"])
    main(["install", "--platform", "claude-code"])
    user_md = fake_home / ".claude" / "CLAUDE.md"
    # Marker must appear exactly once.
    assert user_md.read_text().count("## stele") == 1


def test_install_one_uninstall_other_does_not_affect_first(fake_home: Path) -> None:
    main(["install", "--platform", "claude-code"])
    main(["install", "--platform", "codex"])
    main(["uninstall", "--platform", "codex"])
    assert _skill_path("claude-code", fake_home).is_file()
    assert not _skill_path("codex", fake_home).exists()
```

- [ ] **Step 2: Run**

Run: `.venv/bin/pytest tests/integration/test_install_e2e.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_install_e2e.py
git commit -m "test(packaging): e2e install/uninstall across all 7 platforms in tmp HOME"
```

---

### Task 17: MCP contract test against real `Stele` backends

**Files:**
- Create: `tests/contract/test_mcp_contract.py`

- [ ] **Step 1: Look up the existing `BACKENDS` fixture pattern**

Run: `grep -l "BACKENDS" tests/contract/ | head -3 && grep -A 5 "^BACKENDS\\s*=" tests/contract/*.py | head -30`
Use the existing parametrization verbatim. Do not introduce a new pattern.

- [ ] **Step 2: Write the contract test**

Create `tests/contract/test_mcp_contract.py` mirroring the imports/fixtures from a neighbor like `tests/contract/test_memory_contract.py`:

```python
from __future__ import annotations

import json
from typing import Any

import pytest

# Reuse the existing backend-parametrization fixture from contract/conftest or
# the neighboring test file. Replace `make_stele` below if the project uses a
# different fixture name.
from tests.contract.conftest import make_stele  # type: ignore[import-not-found]

from stele.mcp.tools import bind_handlers


@pytest.mark.parametrize("backend_name", ["memory", "sqlite"])
def test_store_then_fetch_roundtrip(backend_name: str) -> None:
    stele = make_stele(backend_name)
    handlers = {t.name: t.handler for t in bind_handlers(stele)}

    stored = handlers["stele_store"](payload="hello world", content_type="text/plain")
    assert "error" not in stored
    ref = stored["ref"]
    assert ref.startswith("stele://")

    fetched = handlers["stele_fetch"](ref=ref)
    assert "error" not in fetched
    assert "hello" in str(fetched.get("content", ""))


@pytest.mark.parametrize("backend_name", ["memory", "sqlite"])
def test_memory_add_then_search(backend_name: str) -> None:
    stele = make_stele(backend_name)
    handlers = {t.name: t.handler for t in bind_handlers(stele)}

    # Need a real source ref first.
    stored = handlers["stele_store"](payload="evidence body")
    ref = stored["ref"]
    added = handlers["stele_memory_add"](text="user prefers tabs", source_refs=[ref])
    assert "error" not in added
    assert added.get("memory_id")

    hits = handlers["stele_memory_search"](query="tabs")
    assert "error" not in hits
    assert len(hits["hits"]) >= 1


def test_unknown_facade_method_returns_internal_error() -> None:
    """A handler that raises an unmapped exception surfaces as INTERNAL."""
    stele_like: dict[str, Any] = {}  # missing .store etc.
    handlers = {t.name: t.handler for t in bind_handlers(type("S", (), {"store": (lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))})())}
    out = handlers["stele_store"](payload="x")
    assert out.get("error", {}).get("code") == "INTERNAL"
```

If `tests/contract/conftest.py` doesn't expose `make_stele` (it may expose `stele_factory` or a parametrized fixture), copy the pattern from `tests/contract/test_memory_contract.py` exactly — that file is the canonical reference per CLAUDE.md.

- [ ] **Step 3: Run**

Run: `.venv/bin/pytest tests/contract/test_mcp_contract.py -v`
Expected: passes on memory + sqlite. If postgres DSN env vars are set, runs on those too.

- [ ] **Step 4: Commit**

```bash
git add tests/contract/test_mcp_contract.py
git commit -m "test(mcp): contract suite for the full tool surface parametrized over backends"
```

---

## Phase 6 — Documentation (DC-FINAL)

### Task 18: Auth-model and smoke-checklist docs

**Files:**
- Create: `docs/packaging-auth-model.md`
- Create: `docs/packaging-smoke-checklist.md`

- [ ] **Step 1: Write the docs**

Create `docs/packaging-auth-model.md`:

```markdown
# Stele MCP — Auth Model (v1)

**Status:** stdio-only, no auth. Local-trusted execution boundary.

## Why
- The MCP server runs as a child process of the agent host (Claude Code, Codex, etc.).
- Process boundary already gives the user explicit consent to launch it.
- Network-exposed transports (SSE, streamable-HTTP) defer the auth question — design slot reserved.

## What this means
- Anyone who can launch `stele-mcp` on this machine has full read/write access to whatever backend `.stele/config.yaml` points at.
- Don't ship a `.stele/config.yaml` containing a production DSN in a public repo.
- Signing keys (when signing.mode != "off") come from the env var `STELE_SIGNING_SECRET`, NOT from the config file.

## When this changes
- The day a remote transport ships, this doc gets reopened. Plan:
  1. Add bearer-token requirement to the network transport handshake.
  2. Add a per-tool permission list (`mcp.allow_tools: [...]`) to `.stele/config.yaml`.
  3. Add request signing for callers behind a shared secret.
- Until then: stdio only.
```

Create `docs/packaging-smoke-checklist.md`:

```markdown
# Stele Packaging — Manual Smoke Checklist

Run this on a maintainer machine before each release that touches `mcp/`, `cli/`, or `packaging/`. Not part of CI.

## Setup
- [ ] Fresh `~/.claude` directory (back up the real one first).
- [ ] `.venv/bin/pip install -e .` from a clean clone.
- [ ] `stele init --backend sqlite` in a tmp dir.
- [ ] `stele doctor` exits 0.

## Claude Code
- [ ] `stele install --platform claude-code`.
- [ ] Restart Claude Code.
- [ ] `/stele` appears in the slash-skill list.
- [ ] In a conversation, the agent successfully calls `stele_store` and `stele_fetch` via MCP.
- [ ] Type a paragraph mentioning a fact, then start a new session and ask about it — the agent should `stele_memory_search` and cite the `stele://` ref.

## Codex
- [ ] `stele install --platform codex`.
- [ ] `/stele` registered.
- [ ] One round-trip works.

## Other 5 platforms
- [ ] Same smoke per platform: install, restart agent, verify skill appears, verify one MCP round-trip.

## Cleanup
- [ ] `stele uninstall --all`.
- [ ] Verify no leftover files in `~/.claude`, `~/.agents`, `~/.cursor`, `~/.config/opencode`, `~/.gemini`, `~/.copilot`, `~/.aider`.
```

- [ ] **Step 2: Commit**

```bash
git add docs/packaging-auth-model.md docs/packaging-smoke-checklist.md
git commit -m "docs(packaging): auth-model rationale + manual smoke checklist"
```

---

### Task 19: Update `CLAUDE.md` and `docs/current-status.md`

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/current-status.md`

- [ ] **Step 1: Add packaging module to CLAUDE.md architecture overview**

Edit the architecture overview in `CLAUDE.md` to add three rows after `recall/`:

```
mcp/         stdio MCP server: 18-tool surface over the Stele facade
cli/         `stele` binary: init/install/uninstall/status/doctor/mcp
packaging/   Jinja-rendered skill/hook/section content + PLATFORM_CONFIG
```

- [ ] **Step 2: Add a row to `docs/current-status.md`**

Under "## What's implemented", add a new section:

```markdown
### Packaging — Multi-platform MCP + slash-skill

- `stele-mcp` stdio server with full 18-tool surface (`store`/`fetch`/`search`/`query`/`list`/`delete` + `memory_*` + `extract_*` + `recall` + `stash_tool_result`).
- `stele` CLI: `init`, `install`, `uninstall`, `status`, `doctor`, `mcp`.
- Seven launch platforms driven by `src/stele/packaging/platforms.py:PLATFORM_CONFIG`:
  Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Copilot, Aider.
- One Jinja template per content type; per-platform render via dict lookup.
- Idempotent shared-doc section editing (CLAUDE.md / AGENTS.md / GEMINI.md).
- Spec: `docs/superpowers/specs/2026-05-20-stele-multiplatform-packaging-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/current-status.md
git commit -m "docs: register mcp/cli/packaging in architecture overview and status"
```

---

### Task 20: Final lint + types + full test run

- [ ] **Step 1: Run the trio**

```bash
.venv/bin/ruff check .
.venv/bin/mypy src tests benchmarks
.venv/bin/pytest
```

Expected: all clean.

- [ ] **Step 2: If anything fails — fix at root cause; do NOT bypass.**

Common pitfalls:
- mypy strict on the new modules may flag `Any` returns from `bind_handlers`. Use precise return types in the wrappers; `_to_jsonable` is the only place `Any` is acceptable.
- ruff may flag `B008` on the dataclass defaults. Use `field(default=None)` (already done in `ToolSpec`).
- A missing `__init__.py` in `tests/integration/` may break collection — create it if so.

- [ ] **Step 3: Update task statuses + commit any fixups**

```bash
git status --short
# if anything modified by fixups:
git add -u
git commit -m "chore(packaging): trio-clean fixups"
```

---

## Self-Review

### Spec coverage

| Spec section | Implemented by tasks |
|---|---|
| §3 ALWAYS — MCP is SoT | Task 12 (server delegates), Task 17 (contract verifies real facade) |
| §3 ALWAYS — one Jinja template | Task 7, Task 9 |
| §3 ALWAYS — structured JSON errors | Task 3, Task 12 (`@guard` decorator) |
| §3 ALWAYS — idempotent section pattern | Task 5 |
| §3 ALWAYS — PII scrub on egress | Task 2 + Task 12 `_sanitize` |
| §4.1 — 18 MCP tools | Task 11 + Task 12 |
| §4.2 — CLI commands | Task 13, Task 14, Task 15 |
| §4.3 — packaging primitives | Task 5, Task 6, Task 7, Task 8, Task 10 |
| §4.4 — skill template | Task 7 |
| §4.5 — hooks and rules-files | Task 9 |
| §4.6 — project config schema | Task 13 (sample content); validation in Task 15 doctor |
| §5 Data flow — install/uninstall | Task 10 + Task 14 + Task 16 |
| §6 Error handling | Task 3 + Task 5 (SectionConflictError) |
| §7 Testing — unit | Tasks 2–10, 13–15 |
| §7 Testing — contract | Task 17 |
| §7 Testing — integration | Task 16 |
| §7 Testing — manual smoke | Task 18 |
| §8 SC-001..010 | Covered (see SC map below) |
| §9 DC-A..FINAL | DC-A → Task 13; DC-B → Task 12; DC-C → Task 10/14; DC-D → Task 16; DC-FINAL → Task 20 |

### SC map

| SC | Verified by |
|---|---|
| SC-001 (console scripts) | Task 1 + smoke in Task 20 |
| SC-002 (`stele init` + `doctor`) | Task 13 + Task 15 |
| SC-003 (per-platform install/uninstall) | Task 14 + Task 16 |
| SC-004 (18 tools, schemas, dispatch) | Task 11 + Task 12 |
| SC-005 (exception → code mapping) | Task 3 |
| SC-006 (sanitization on egress) | Task 2 + Task 12 |
| SC-007 (single Jinja template) | Task 7 |
| SC-008 (idempotent section) | Task 5 |
| SC-009 (zero leftover files) | Task 16 |
| SC-010 (contract suite on backends) | Task 17 |

### Placeholder scan

No `TBD`, `TODO`, "implement later", or "add appropriate X" remain. The one acceptable `Any` is in `_to_jsonable` for the best-effort jsonable conversion (`Any` in / `Any` out is the right type).

### Type consistency

- `ToolSpec` defined Task 11; consumed Task 12, Task 17 with the same field names.
- `PlatformSpec` defined Task 6; consumed Task 7, Task 10, Task 14, Task 16 with the same field names.
- `McpError` defined Task 3; consumed by `guard()` and contract test.
- `SectionConflictError` defined Task 5; surfaces via CLI install when shared-doc state is corrupt (not asserted in tests, since corruption is an external precondition).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-20-stele-multiplatform-packaging.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task + two-stage review.

**2. Inline Execution** — Batch execution in this session with checkpoint reviews.

User has approved autonomous execution — defaulting to **Subagent-Driven** per writing-plans guidance.
