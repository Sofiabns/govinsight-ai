from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from govinsight.raw.tables import etl_watermark, raw_api_response

from .procurement import NormalizedProcurement, RejectedProcurement
from .tables import procurement, rejected_record

PIPELINE_NAME = "silver_procurement"
DATASET = "procurements"
STAGE = "silver"


class WriteOutcome(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


class SilverStateError(RuntimeError):
    pass


class BronzeProcurementRepository:
    def pending(
        self,
        connection: Connection,
        after_id: int,
        limit: int,
    ) -> list[Mapping[str, Any]]:
        return list(
            connection.execute(
                sa.select(raw_api_response.c.id, raw_api_response.c.raw_body)
                .where(
                    raw_api_response.c.dataset == DATASET,
                    raw_api_response.c.id > after_id,
                )
                .order_by(raw_api_response.c.id)
                .limit(limit)
            ).mappings()
        )


class ProcurementRepository:
    def upsert(
        self,
        connection: Connection,
        value: NormalizedProcurement,
    ) -> WriteOutcome:
        current = (
            connection.execute(
                sa.select(
                    procurement.c.normalized_sha256,
                    procurement.c.data_atualizacao_global,
                    procurement.c.source_raw_response_id,
                )
                .where(procurement.c.numero_controle_pncp == value.numero_controle_pncp)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        now = datetime.now(UTC)
        values = value.model_dump()
        if current is None:
            connection.execute(
                procurement.insert().values(**values, created_at=now, updated_at=now)
            )
            return WriteOutcome.INSERTED
        if current["normalized_sha256"] == value.normalized_sha256:
            return WriteOutcome.UNCHANGED
        incoming_is_newer = value.data_atualizacao_global > current["data_atualizacao_global"]
        incoming_breaks_tie = (
            value.data_atualizacao_global == current["data_atualizacao_global"]
            and value.source_raw_response_id > current["source_raw_response_id"]
        )
        if not (incoming_is_newer or incoming_breaks_tie):
            return WriteOutcome.UNCHANGED
        connection.execute(
            procurement.update()
            .where(procurement.c.numero_controle_pncp == value.numero_controle_pncp)
            .values(**values, updated_at=now)
        )
        return WriteOutcome.UPDATED


class RejectedRecordRepository:
    def insert(self, connection: Connection, value: RejectedProcurement) -> bool:
        values = value.model_dump()
        values["error_codes"] = list(value.error_codes)
        statement = (
            postgresql.insert(rejected_record)
            .values(
                **values,
                rejected_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="uq_silver_rejected_source_record")
            .returning(rejected_record.c.id)
        )
        return connection.execute(statement).scalar_one_or_none() is not None


class SilverWatermarkRepository:
    @staticmethod
    def _key() -> tuple[sa.ColumnElement[bool], ...]:
        return (
            etl_watermark.c.pipeline_name == PIPELINE_NAME,
            etl_watermark.c.dataset == DATASET,
            etl_watermark.c.stage == STAGE,
        )

    def current(self, connection: Connection, *, lock: bool = False) -> int:
        statement = sa.select(etl_watermark.c.watermark_value).where(*self._key())
        if lock:
            statement = statement.with_for_update()
        value = connection.execute(statement).scalar_one_or_none()
        if value is None:
            return 0
        raw_id = value.get("last_raw_response_id") if isinstance(value, dict) else None
        if not isinstance(raw_id, int) or raw_id < 0:
            raise SilverStateError("invalid Silver watermark")
        return raw_id

    def advance(self, connection: Connection, raw_response_id: int) -> None:
        now = datetime.now(UTC)
        statement = postgresql.insert(etl_watermark).values(
            pipeline_name=PIPELINE_NAME,
            dataset=DATASET,
            stage=STAGE,
            watermark_value={"last_raw_response_id": raw_response_id},
            confirmed_at=now,
        )
        stored_id = sa.cast(
            etl_watermark.c.watermark_value["last_raw_response_id"].astext,
            sa.BigInteger(),
        )
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    etl_watermark.c.pipeline_name,
                    etl_watermark.c.dataset,
                    etl_watermark.c.stage,
                ],
                set_={
                    "watermark_value": statement.excluded.watermark_value,
                    "confirmed_at": statement.excluded.confirmed_at,
                },
                where=stored_id < raw_response_id,
            )
        )
