"""ClickHouse adapter for ``RecordRepo`` (REQ-D-2).

The ``records`` table is a ``ReplacingMergeTree`` keyed by
``record_hash`` so writing the same record twice is idempotent. DDL
lives in ``src/cce_service/migrations/clickhouse/0001_records.sql``.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from cce_service.retry import retry_on_transient_error
from cce_service.storage.models import ScoreRecord


def _require_clickhouse():  # pragma: no cover - import shim
    try:
        import clickhouse_connect  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "cce_service.storage.clickhouse requires the 'cce-service' extras. "
            "Install with: pip install '.[cce-service]'"
        ) from exc
    return clickhouse_connect


class ClickHouseRecordRepo:
    """RecordRepo backed by clickhouse-connect."""

    _TABLE = "records"
    _COLUMNS = (
        "record_hash",
        "commit_sha",
        "repo_url",
        "spec_hash",
        "score",
        "metrics_json",
        "tool_digests_json",
        "tenant",
        "created_at",
    )

    def __init__(
        self,
        host: str,
        port: int = 8123,
        username: str = "default",
        password: str = "",
        database: str = "cce",
        *,
        connect_timeout: int | None = None,
        send_receive_timeout: int | None = None,
    ) -> None:
        cc = _require_clickhouse()
        client_kwargs: dict = {}
        _ct = (
            connect_timeout
            if connect_timeout is not None
            else int(os.environ.get("CCE_CH_CONNECT_TIMEOUT", "10"))
        )
        _srt = (
            send_receive_timeout
            if send_receive_timeout is not None
            else int(os.environ.get("CCE_CH_SEND_RECEIVE_TIMEOUT", "30"))
        )
        client_kwargs["connect_timeout"] = _ct
        client_kwargs["send_receive_timeout"] = _srt
        self._client = cc.get_client(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            **client_kwargs,
        )

    @retry_on_transient_error(
        max_attempts=3, retryable_exceptions=(Exception,), component="clickhouse.upsert"
    )
    def upsert(self, record: ScoreRecord) -> None:
        # ReplacingMergeTree dedupes by ORDER BY key (record_hash) on background merge.
        row = (
            record.record_hash,
            record.commit_sha,
            record.repo_url,
            record.spec_hash,
            record.score,
            json.dumps(record.metrics, separators=(",", ":"), sort_keys=True),
            json.dumps(record.tool_digests, separators=(",", ":"), sort_keys=True),
            record.tenant,
            record.created_at,
        )
        self._client.insert(self._TABLE, [row], column_names=self._COLUMNS)

    def get(self, record_hash: str) -> ScoreRecord | None:
        # FINAL forces merge of the latest version per record_hash so reads
        # are consistent immediately after upsert.
        rows = self._client.query(
            f"SELECT {', '.join(self._COLUMNS)} FROM {self._TABLE} FINAL "
            "WHERE record_hash = {record_hash:String} LIMIT 1",
            parameters={"record_hash": record_hash},
        ).result_rows
        if not rows:
            return None
        (
            rh,
            commit_sha,
            repo_url,
            spec_hash,
            score,
            metrics_json,
            tool_digests_json,
            tenant,
            created_at,
        ) = rows[0]
        if isinstance(created_at, datetime) and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return ScoreRecord(
            record_hash=rh,
            commit_sha=commit_sha,
            repo_url=repo_url,
            spec_hash=spec_hash,
            score=score,
            metrics=json.loads(metrics_json or "{}"),
            tool_digests=json.loads(tool_digests_json or "{}"),
            tenant=tenant if isinstance(tenant, str) else "default",
            created_at=created_at,
        )


__all__ = ["ClickHouseRecordRepo"]
