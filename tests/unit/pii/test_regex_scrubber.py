from stele.pii.regex import RegexPIIScrubber


def test_regex_scrubber_removes_known_fixtures() -> None:
    text = (
        "Email alice@example.com, phone 212-555-0199, ssn 123-45-6789, "
        "card 4111 1111 1111 1111, token sk_test_abcdefghijklmnop, "
        "hyphen token sk-test-1234567890abcdef."
    )

    result = RegexPIIScrubber().scrub(text)

    assert "alice@example.com" not in result.text
    assert "212-555-0199" not in result.text
    assert "123-45-6789" not in result.text
    assert "4111 1111 1111 1111" not in result.text
    assert "sk_test_abcdefghijklmnop" not in result.text
    assert "sk-test-1234567890abcdef" not in result.text
    assert result.summary.detection_count >= 6


def test_regex_scrubber_leaves_clean_text() -> None:
    text = "This is a clean operational status update."

    result = RegexPIIScrubber().scrub(text)

    assert result.text == text
    assert result.detections == []
