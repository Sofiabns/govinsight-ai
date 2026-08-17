from datetime import date

import pytest

from govinsight.config import Settings
from govinsight.extract.pncp.client import PNCPClient
from govinsight.extract.pncp.models import ProcurementQuery


@pytest.mark.integration
@pytest.mark.live_api
def test_official_pncp_procurement_contract_is_compatible() -> None:
    query = ProcurementQuery(
        start_date=date(2025, 8, 1),
        end_date=date(2025, 8, 1),
        modality_code=6,
        page=1,
        page_size=10,
    )

    with PNCPClient.from_settings(Settings()) as client:
        page = client.list_procurements(query)

    assert page.page_number == 1
    assert page.empty is False
    assert page.total_records > 0
    assert len(page.data) == 10
    for record in page.data:
        assert record["numeroControlePNCP"]
        assert record["orgaoEntidade"]
        assert record["unidadeOrgao"]
        assert record["objetoCompra"]
        assert record["dataAtualizacaoGlobal"]
