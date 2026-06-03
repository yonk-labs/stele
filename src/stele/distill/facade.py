from __future__ import annotations

from typing import TYPE_CHECKING

from stele.core.memory_record import MemoryScope
from stele.distill.base import LLMSynthesizer
from stele.distill.jobs import DistillJob, submit_job
from stele.distill.models import DistilledView

if TYPE_CHECKING:
    from stele.core.config import DistillConfig


class Distill:
    """Per-mode distillation facade. Consumes only public facades; the LLM
    (if any) is injected."""

    def __init__(
        self,
        *,
        stele: object,
        memory: object,
        extract: object,
        recall: object,
        config: DistillConfig,
        llm: LLMSynthesizer | None = None,
    ) -> None:
        self._stele = stele
        self._memory = memory
        self._extract = extract
        self._recall = recall
        self._config = config
        self._llm = llm
        self._jobs: dict[str, DistillJob] = {}

    async def facts(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.facts import distill_facts

        return await distill_facts(self, scope)

    async def precedents(self, scope: MemoryScope, query: str | None = None) -> DistilledView:
        from stele.distill.precedents import distill_precedents

        return await distill_precedents(self, scope, query)

    async def state(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.state import distill_state

        return await distill_state(self, scope)

    async def skills(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.behavioral import distill_skills

        return await distill_skills(self, scope)

    async def best_practices(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.behavioral import distill_best_practices

        return await distill_best_practices(self, scope)

    async def rules(self, scope: MemoryScope) -> DistilledView:
        from stele.distill.behavioral import distill_rules

        return await distill_rules(self, scope)

    def submit(self, mode: str, scope: MemoryScope, **kwargs: object) -> DistillJob:
        """Kick off a distill run in the background. Returns a handle immediately."""
        method = getattr(self, mode)  # one of the six async methods
        job = submit_job(lambda: method(scope, **kwargs))
        self._jobs[job.id] = job
        return job

    def result(self, job_id: str) -> DistilledView | None:
        """The DistilledView if the job finished, else None (still running).
        Raises KeyError for an unknown job id."""
        job = self._jobs[job_id]
        if not job.future.done():
            return None
        return job.future.result()
