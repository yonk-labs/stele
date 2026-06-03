# ruff: noqa: E501 -- benchmark helper.
"""Mine THIS session's real artifacts as `real_trace` corpora.

The benchmark was built for cross-session memory; the most honest real_trace is
the project's own history. This reads the real git commits on the current branch
(the actual task episodes of the session) so precedent-recall and
resume-task-state run on real data instead of only synthetic fixtures. No gold
is invented: a commit's sha is its own exact join key, and a feature is "done"
iff a commit actually shipped it.
"""

from __future__ import annotations

import subprocess


def session_commits(base: str = "main") -> list[tuple[str, str]]:
    """(short_sha, subject) for commits on the current branch since `base`.

    Returns [] if git is unavailable, so a mode degrades to no real_trace cases
    rather than crashing."""
    try:
        r = subprocess.run(
            ["git", "log", "--format=%h%x09%s", f"{base}..HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return []
    rows: list[tuple[str, str]] = []
    for line in r.stdout.splitlines():
        if "\t" in line:
            sha, subj = line.split("\t", 1)
            rows.append((sha.strip(), subj.strip()))
    return rows


# Session deliverables and the commit-subject keyword that marks each shipped.
# "done" iff a real commit references it; anything with no commit is "absent"
# (the honest record of what we left unbuilt, e.g. the benchmark-to-blog workflow).
SESSION_FEATURES: tuple[tuple[str, str], ...] = (
    ("guardrail-adherence-mode", "guardrail"),
    ("skill-adherence-mode", "skill"),
    ("best-practice-mode", "best-practice"),
    ("precedent-recall-mode", "precedent"),
    ("fact-recall-mode", "fact-recall"),
    ("resume-task-state-mode", "resume"),
    ("harness-unit-tests", "test(bench)"),
    ("benchmark-to-blog-workflow", "benchmark-to-blog workflow"),
)
