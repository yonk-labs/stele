from stele.core.stash import Stele
from stele.revisor.base import NoOpRevisor


def test_revisor_noop_when_graph_disabled() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    assert isinstance(s.revisor, NoOpRevisor)
    assert s.revisor.active is False
    s.close()


def test_revisor_noop_when_enabled_but_not_postgres() -> None:
    s = Stele.from_config(
        {
            "backend": {"type": "sqlite", "path": ".stele/_t_rev.db"},
            "graph": {"enabled": True},
        }
    )
    assert s.revisor.active is False  # capability honesty: graph needs Postgres
    s.close()


def test_memory_property_receives_revisor() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    assert s.memory._revisor is s.revisor
    s.close()
