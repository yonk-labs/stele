from pathlib import Path

from stele import Stele


def test_jsonl_export_import_preserves_reference_and_content(tmp_path: Path) -> None:
    source = Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )
    stored = source.store(
        "Quarterly migration plan: move analytics to ClickHouse.",
        namespace="migration",
        session_id="s1",
        metadata={"priority": "high"},
    )
    export_path = tmp_path / "artifacts.jsonl"

    exported = source.export_jsonl(export_path, namespace="migration")
    target = Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )
    imported = target.import_jsonl(export_path)

    fetched = target.fetch(stored.reference, raw=True)
    assert exported.exported_count == 1
    assert imported.imported_count == 1
    assert fetched.content == "Quarterly migration plan: move analytics to ClickHouse."
    assert fetched.metadata == {"priority": "high"}


def test_jsonl_export_import_preserves_bytes(tmp_path: Path) -> None:
    source = Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )
    stored = source.store(b"\x00\x01\x02", namespace="bytes")
    export_path = tmp_path / "bytes.jsonl"

    source.export_jsonl(export_path)
    target = Stele.from_config(
        {"backend": {"type": "memory"}, "pii": {"raw_fetch_enabled": True}}
    )
    target.import_jsonl(export_path)

    assert target.fetch(stored.reference, raw=True).content == b"\x00\x01\x02"
