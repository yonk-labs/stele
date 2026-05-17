from stele.core.stash import Stele


def test_capabilities_report_graph_state_off_by_default() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    caps = s.capabilities()
    assert caps.graph_enabled is False
    assert caps.living_knowledge is False
    s.close()


def test_capabilities_report_pg_raggraph_installed_flag() -> None:
    s = Stele.from_config({"backend": {"type": "memory"}})
    caps = s.capabilities()
    assert isinstance(caps.pg_raggraph_installed, bool)
    assert caps.pg_raggraph_installed is True  # [postgres-graph] is synced
    s.close()
