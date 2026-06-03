from stele.distill.models import DistilledItem, DistilledView, Rule


def test_rule_carries_dont_and_do_instead_and_evidence():
    r = Rule(dont="use gpt-4o", do_instead="use gpt-5-mini", domain="config",
             confidence=0.9, source_refs=["stele://default/abc"])
    assert r.dont and r.do_instead
    assert r.source_refs  # evidence is mandatory


def test_view_is_json_serializable_and_typed():
    v = DistilledView(mode="rules", items=[
        DistilledItem(summary="gpt-4o is outdated", source_refs=["stele://default/abc"])
    ])
    blob = v.model_dump_json()
    assert '"mode":"rules"' in blob.replace(" ", "")
    assert v.items[0].source_refs == ["stele://default/abc"]
