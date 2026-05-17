from stele.core.config import StashConfig


def test_graph_config_defaults_off_and_safe() -> None:
    c = StashConfig()
    assert c.graph.enabled is False
    assert c.graph.namespace == "stele"
    assert c.graph.evolution_tier == "structural"
    assert c.graph.retracted_behavior == "surface_both"
    assert c.graph.supersession_behavior == "prefer_new"


def test_graph_config_from_dict() -> None:
    c = StashConfig.load({"graph": {"enabled": True, "namespace": "kb"}})
    assert c.graph.enabled is True and c.graph.namespace == "kb"
