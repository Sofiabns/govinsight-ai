from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa

from govinsight.raw.tables import raw_api_response
from govinsight.transform.tables import procurement

from .models import QualityDimension, RuleSeverity

VALID_UFS = frozenset(
    {
        "AC",
        "AL",
        "AM",
        "AP",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MG",
        "MS",
        "MT",
        "PA",
        "PB",
        "PE",
        "PI",
        "PR",
        "RJ",
        "RN",
        "RO",
        "RR",
        "RS",
        "SC",
        "SE",
        "SP",
        "TO",
    }
)
MAX_MONEY = Decimal("999999999999999.9999")


@dataclass(frozen=True)
class RuleDefinition:
    code: str
    dimension: QualityDimension
    severity: RuleSeverity
    statement: sa.Select


def _counts(
    failed_when: sa.ColumnElement[bool],
    *,
    applicable_when: sa.ColumnElement[bool] | None = None,
) -> sa.Select:
    checked = sa.func.count()
    failed = sa.func.count().filter(failed_when)
    if applicable_when is not None:
        checked = checked.filter(applicable_when)
        failed = sa.func.count().filter(sa.and_(applicable_when, failed_when))
    return sa.select(
        checked.label("checked_count"),
        failed.label("failed_count"),
    ).select_from(procurement)


def procurement_quality_rules() -> tuple[RuleDefinition, ...]:
    required_text_invalid = sa.or_(
        sa.func.btrim(procurement.c.numero_controle_pncp) == "",
        sa.func.btrim(procurement.c.orgao_cnpj) == "",
        sa.func.btrim(procurement.c.orgao_razao_social) == "",
        sa.func.btrim(procurement.c.codigo_unidade) == "",
        sa.func.btrim(procurement.c.nome_unidade) == "",
        sa.func.btrim(procurement.c.modalidade_nome) == "",
        sa.func.btrim(procurement.c.objeto_compra) == "",
    )
    required_date_invalid = sa.or_(
        procurement.c.data_publicacao_pncp.is_(None),
        procurement.c.data_atualizacao_global.is_(None),
    )
    money_applicable = sa.or_(
        procurement.c.valor_total_estimado.is_not(None),
        procurement.c.valor_total_homologado.is_not(None),
    )
    money_invalid = sa.or_(
        procurement.c.valor_total_estimado < 0,
        procurement.c.valor_total_estimado > MAX_MONEY,
        procurement.c.valor_total_homologado < 0,
        procurement.c.valor_total_homologado > MAX_MONEY,
    )
    proposal_applicable = sa.and_(
        procurement.c.data_abertura_proposta.is_not(None),
        procurement.c.data_encerramento_proposta.is_not(None),
    )
    source_duplicates = (
        sa.select(
            procurement.c.source_raw_response_id,
            procurement.c.source_record_index,
            sa.func.count().label("duplicate_count"),
        )
        .group_by(
            procurement.c.source_raw_response_id,
            procurement.c.source_record_index,
        )
        .having(sa.func.count() > 1)
        .subquery()
    )
    source_duplicate_count = sa.select(
        sa.func.coalesce(sa.func.sum(source_duplicates.c.duplicate_count - 1), 0)
    ).scalar_subquery()
    lineage = procurement.outerjoin(
        raw_api_response,
        procurement.c.source_raw_response_id == raw_api_response.c.id,
    )

    return (
        RuleDefinition(
            "DATASET_NOT_EMPTY",
            QualityDimension.COMPLETENESS,
            RuleSeverity.BLOCKING,
            sa.select(
                sa.literal(1).label("checked_count"),
                sa.case((sa.func.count() == 0, 1), else_=0).label("failed_count"),
            ).select_from(procurement),
        ),
        RuleDefinition(
            "REQUIRED_TEXT_PRESENT",
            QualityDimension.COMPLETENESS,
            RuleSeverity.BLOCKING,
            _counts(required_text_invalid),
        ),
        RuleDefinition(
            "REQUIRED_DATE_PRESENT",
            QualityDimension.COMPLETENESS,
            RuleSeverity.BLOCKING,
            _counts(required_date_invalid),
        ),
        RuleDefinition(
            "CNPJ_FORMAT_VALID",
            QualityDimension.VALIDITY,
            RuleSeverity.BLOCKING,
            _counts(sa.not_(procurement.c.orgao_cnpj.op("~")(r"^[0-9]{14}$"))),
        ),
        RuleDefinition(
            "UF_DOMAIN_VALID",
            QualityDimension.VALIDITY,
            RuleSeverity.BLOCKING,
            _counts(
                procurement.c.uf_sigla.not_in(VALID_UFS),
                applicable_when=procurement.c.uf_sigla.is_not(None),
            ),
        ),
        RuleDefinition(
            "IBGE_FORMAT_VALID",
            QualityDimension.VALIDITY,
            RuleSeverity.BLOCKING,
            _counts(
                sa.not_(procurement.c.codigo_ibge.op("~")(r"^[0-9]{7}$")),
                applicable_when=procurement.c.codigo_ibge.is_not(None),
            ),
        ),
        RuleDefinition(
            "MONEY_RANGE_VALID",
            QualityDimension.VALIDITY,
            RuleSeverity.BLOCKING,
            _counts(money_invalid, applicable_when=money_applicable),
        ),
        RuleDefinition(
            "NATURAL_KEY_UNIQUE",
            QualityDimension.UNIQUENESS,
            RuleSeverity.BLOCKING,
            sa.select(
                sa.func.count().label("checked_count"),
                (
                    sa.func.count() - sa.func.count(sa.distinct(procurement.c.numero_controle_pncp))
                ).label("failed_count"),
            ).select_from(procurement),
        ),
        RuleDefinition(
            "SOURCE_POSITION_UNIQUE",
            QualityDimension.UNIQUENESS,
            RuleSeverity.BLOCKING,
            sa.select(
                sa.func.count().label("checked_count"),
                source_duplicate_count.label("failed_count"),
            ).select_from(procurement),
        ),
        RuleDefinition(
            "PROPOSAL_WINDOW_VALID",
            QualityDimension.CONSISTENCY,
            RuleSeverity.BLOCKING,
            _counts(
                procurement.c.data_encerramento_proposta < procurement.c.data_abertura_proposta,
                applicable_when=proposal_applicable,
            ),
        ),
        RuleDefinition(
            "PURCHASE_YEAR_CONSISTENT",
            QualityDimension.CONSISTENCY,
            RuleSeverity.BLOCKING,
            _counts(
                sa.cast(sa.func.right(procurement.c.numero_controle_pncp, 4), sa.Integer())
                != procurement.c.ano_compra
            ),
        ),
        RuleDefinition(
            "BRONZE_LINEAGE_VALID",
            QualityDimension.INTEGRITY,
            RuleSeverity.BLOCKING,
            sa.select(
                sa.func.count().label("checked_count"),
                sa.func.count().filter(raw_api_response.c.id.is_(None)).label("failed_count"),
            ).select_from(lineage),
        ),
    )


__all__ = ["RuleDefinition", "procurement_quality_rules"]
