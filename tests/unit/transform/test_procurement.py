import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from govinsight.transform.procurement import parse_procurement

FIXTURE = Path(__file__).parents[2] / "fixtures" / "pncp" / "contratacoes_publicacao_page_1.json"


def _record() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]


def test_real_procurement_is_typed_and_hashed_deterministically() -> None:
    first = parse_procurement(_record(), raw_response_id=41, record_index=0)
    second = parse_procurement(_record(), raw_response_id=99, record_index=7)

    assert first.rejection is None
    assert first.procurement is not None
    assert first.procurement.numero_controle_pncp == "13183513000127-1-000146/2025"
    assert first.procurement.valor_total_estimado == Decimal("0.0")
    assert first.procurement.valor_total_homologado is None
    assert first.procurement.data_publicacao_pncp.tzinfo is None
    assert first.procurement.source_raw_response_id == 41
    assert first.procurement.source_record_index == 0
    assert len(first.procurement.normalized_sha256) == 64
    assert second.procurement is not None
    assert second.procurement.normalized_sha256 == first.procurement.normalized_sha256


def test_invalid_record_returns_only_safe_deterministic_codes() -> None:
    invalid = deepcopy(_record())
    invalid["orgaoEntidade"]["cnpj"] = "SENSITIVE-CNPJ"
    invalid["dataAberturaProposta"] = "2025-09-02T10:00:00"
    invalid["dataEncerramentoProposta"] = "2025-09-01T09:00:00"

    result = parse_procurement(invalid, raw_response_id=41, record_index=1)

    assert result.procurement is None
    assert result.rejection is not None
    assert result.rejection.error_codes == ("INCONSISTENT_DATE_RANGE", "INVALID_CNPJ")
    assert result.rejection.natural_key == "13183513000127-1-000146/2025"
    assert "SENSITIVE-CNPJ" not in repr(result.rejection)


def test_schema_incompatible_values_are_safely_rejected() -> None:
    invalid = deepcopy(_record())
    invalid["numeroControlePNCP"] = "SENSITIVE-NATURAL-KEY"
    invalid["modalidadeId"] = 1.5
    invalid["sequencialCompra"] = 2_147_483_648
    invalid["valorTotalEstimado"] = "1000000000000000"

    result = parse_procurement(invalid, raw_response_id=41, record_index=2)

    assert result.procurement is None
    assert result.rejection is not None
    assert result.rejection.natural_key is None
    assert result.rejection.error_codes == (
        "INVALID_DECIMAL",
        "INVALID_ID",
        "INVALID_NATURAL_KEY",
    )
    assert "SENSITIVE-NATURAL-KEY" not in repr(result.rejection)
