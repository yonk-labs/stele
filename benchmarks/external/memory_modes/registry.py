"""The single extension point: the ordered list of modes the runner iterates.

Adding a mode is one import + one entry here. No runner edit, no schema change.
Modes are added as they land (build order: guardrail + the enforcement twins,
then resume-task-state, then fact-recall, then precedent-recall)."""

from __future__ import annotations

from benchmarks.external.memory_modes.base import Mode
from benchmarks.external.memory_modes.guardrail_adherence import GuardrailAdherence

MODES: list[Mode] = [
    GuardrailAdherence(),
]
