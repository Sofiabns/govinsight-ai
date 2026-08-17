from govinsight.raw.hashing import request_fingerprint, scope_fingerprint, scope_parameters


def test_canonical_json_is_stable_and_preserves_unicode() -> None:
    from govinsight.raw.hashing import canonical_json

    assert canonical_json({"b": 2, "a": "ação"}) == '{"a":"ação","b":2}'


def test_sha256_text_hashes_the_exact_utf8_text() -> None:
    from govinsight.raw.hashing import sha256_text

    assert (
        sha256_text("GovInsight RAW")
        == "b42000b4e95d43430479235c411e488cec11d733892b9000a2e434887744e2c3"
    )


def test_scope_keeps_page_size_but_removes_page_number() -> None:
    assert scope_parameters({"pagina": 9, "tamanhoPagina": 50, "dataInicial": "20250801"}) == {
        "tamanhoPagina": 50,
        "dataInicial": "20250801",
    }


def test_fingerprints_are_order_independent_and_scope_tracks_page_size() -> None:
    first = {"pagina": 1, "tamanhoPagina": 50, "dataInicial": "20250801"}
    second = {"dataInicial": "20250801", "tamanhoPagina": 50, "pagina": 1}
    assert request_fingerprint("pncp", "procurements", "/v1", first) == request_fingerprint(
        "pncp", "procurements", "/v1", second
    )
    assert scope_fingerprint("pncp", "procurements", "/v1", first) == scope_fingerprint(
        "pncp", "procurements", "/v1", second
    )
    assert scope_fingerprint("pncp", "procurements", "/v1", first) != scope_fingerprint(
        "pncp", "procurements", "/v1", {**first, "tamanhoPagina": 100}
    )
