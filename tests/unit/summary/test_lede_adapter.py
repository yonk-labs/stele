from stele.summary.lede_adapter import LedeSummaryProvider


def test_lede_summary_provider_returns_bounded_text() -> None:
    provider = LedeSummaryProvider()
    text = "First sentence has the important fact. Second sentence adds more detail. " * 20

    summary = provider.summarize(text, max_chars=120)

    assert summary
    assert len(summary) <= 120

