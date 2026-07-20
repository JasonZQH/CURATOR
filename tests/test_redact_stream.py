"""Streaming redaction must catch secrets split across provider output chunks.

The ledger persists provider stdout one OUTPUT_CHUNK event at a time. redact_secrets
scrubs each chunk in isolation, so a credential straddling two chunk boundaries slips
through. StreamRedactor holds back a small tail across feeds so the whole secret is
seen together before any of it is emitted.
"""

from curator.providers.redact import StreamRedactor


def test_stream_redactor_scrubs_secret_split_across_two_chunks() -> None:
    """A single sk- key split over two feeds is never emitted in cleartext."""
    secret = "sk-ABCDEF0123456789GHIJKL"  # sk- + 21 chars, satisfies {16,}
    head, tail = secret[:10], secret[10:]  # "sk-ABCDEF0" | "123456789GHIJKL"

    redactor = StreamRedactor()
    out = redactor.scrub(f"using key {head}")
    out += redactor.scrub(f"{tail} then continued")
    out += redactor.flush()

    assert secret not in out
    assert "sk-ABCDEF0" not in out  # not even the leading fragment leaks
    assert "[REDACTED]" in out


def test_stream_redactor_scrubs_key_value_split_across_chunks() -> None:
    """A token=value pair whose value is split across feeds is fully redacted."""
    redactor = StreamRedactor()
    out = redactor.scrub("auth token=abcd")
    out += redactor.scrub("efghijklmnop stop")
    out += redactor.flush()

    assert "abcdefghijklmnop" not in out
    assert "[REDACTED]" in out


def test_stream_redactor_redacts_whole_secret_in_one_chunk() -> None:
    """A secret fully inside one chunk is still redacted (defense in depth)."""
    redactor = StreamRedactor()
    out = redactor.scrub("token=supersecretvalue") + redactor.flush()

    assert "supersecretvalue" not in out
    assert "[REDACTED]" in out


def test_stream_redactor_emits_leading_text_then_redacts_boundary_secret() -> None:
    """Long clean lead-in is emitted incrementally; a later boundary secret is scrubbed."""
    lead = "x" * 100
    redactor = StreamRedactor()
    out = redactor.scrub(lead + " sk-ABCDEF012345")
    out += redactor.scrub("6789GHIJKLMN more")
    out += redactor.flush()

    assert out.count("x") == 100
    assert "sk-ABCDEF0123456789GHIJKLMN" not in out
    assert "[REDACTED]" in out


def test_stream_redactor_passes_clean_text_through_without_corruption() -> None:
    """Clean streamed text round-trips exactly: no dropped, duplicated, or reordered text."""
    redactor = StreamRedactor()
    out = redactor.scrub("hello ")
    out += redactor.scrub("wonderful ")
    out += redactor.scrub("world")
    out += redactor.flush()

    assert out == "hello wonderful world"
