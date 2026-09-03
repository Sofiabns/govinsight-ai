from govinsight.importers.pncp_csv import to_pncp_record
from govinsight.transform.procurement import parse_procurement


def test_official_csv_row_maps_to_valid_silver_record() -> None:
    row = {
        "numero_controle_PNCP": "37115342000167-1-000095/2025",
        "srp": "False",
        "orgao_entidade_cnpj": "37115342000167",
        "orgao_entidade_razao_social": "MINISTERIO DA INFRAESTRUTURA",
        "unidade_orgao_codigo_unidade": "390004",
        "unidade_orgao_nome_unidade": "COORD.GERAL DE RECURSOS LOGÍSTICOS",
        "unidade_orgao_codigo_ibge": "5300108",
        "unidade_orgao_uf_sigla": "DF",
        "modalidade_id_pncp": "4",
        "modalidade_nome": "Concorrência - Eletrônica",
        "ano_compra_pncp": "2025",
        "sequencial_compra_pncp": "95",
        "data_publicacao_pncp": "2025-10-13 07:09:42",
        "data_atualizacao_pncp": "2025-10-13 07:09:42",
        "objeto_compra": "Contratação de serviços de engenharia.",
        "valor_total_estimado": "1672579.36",
    }

    converted = to_pncp_record(row)
    result = parse_procurement(converted, raw_response_id=1, record_index=0)

    assert result.procurement is not None
    assert result.procurement.uf_sigla == "DF"
