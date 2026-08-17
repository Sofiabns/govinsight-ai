import pytest

from govinsight.extract.pncp.models import QueryMode
from govinsight.raw.models import RawDataset
from govinsight.raw.service import RawIngestionService


@pytest.mark.parametrize(
    ("dataset", "mode", "expected"),
    [
        (RawDataset.PROCUREMENTS, QueryMode.PUBLICATION, "/v1/contratacoes/publicacao"),
        (RawDataset.PROCUREMENTS, QueryMode.UPDATE, "/v1/contratacoes/atualizacao"),
        (RawDataset.CONTRACTS, QueryMode.PUBLICATION, "/v1/contratos"),
        (RawDataset.CONTRACTS, QueryMode.UPDATE, "/v1/contratos/atualizacao"),
    ],
)
def test_raw_service_routes_each_dataset_and_mode(
    dataset: RawDataset,
    mode: QueryMode,
    expected: str,
) -> None:
    assert RawIngestionService._endpoint(dataset, mode) == expected
