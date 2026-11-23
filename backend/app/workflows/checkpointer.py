"""LangGraph checkpoints in Postgres, through the application's own SQLAlchemy and asyncpg
stack and under row-level security.

`langgraph-checkpoint-postgres` was not used: it needs a second Postgres driver (psycopg) and
its tables have no `organization_id`, so they could not carry the tenant policy every other
table has. This saver follows LangGraph's reference `InMemorySaver` semantics and uses
LangGraph's own serializer. The thread id is the investigation id. Only the async interface
is implemented, because the workflow runs only through `ainvoke`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
    writes_sort_key,
)
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_session
from app.models import InvestigationCheckpoint, InvestigationCheckpointWrite


class SqlCheckpointer(BaseCheckpointSaver[int]):
    def __init__(self, organization_id: uuid.UUID) -> None:
        super().__init__()
        self.organization_id = organization_id

    @staticmethod
    def _thread(config: RunnableConfig) -> uuid.UUID:
        return uuid.UUID(str(config["configurable"]["thread_id"]))

    async def _writes(
        self, s: AsyncSession, thread: uuid.UUID, ns: str, checkpoint_id: str
    ) -> list[tuple[str, str, Any]]:
        rows = list(
            await s.scalars(
                select(InvestigationCheckpointWrite).where(
                    InvestigationCheckpointWrite.organization_id == self.organization_id,
                    InvestigationCheckpointWrite.investigation_id == thread,
                    InvestigationCheckpointWrite.checkpoint_ns == ns,
                    InvestigationCheckpointWrite.checkpoint_id == checkpoint_id,
                )
            )
        )
        rows.sort(key=lambda w: writes_sort_key(w.task_path, w.task_id, w.idx))
        return [
            (w.task_id, w.channel, self.serde.loads_typed((w.value_type, w.value))) for w in rows
        ]

    async def _tuple(self, s: AsyncSession, row: InvestigationCheckpoint) -> CheckpointTuple:
        thread_id = str(row.investigation_id)
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": row.checkpoint_ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint=self.serde.loads_typed((row.checkpoint_type, row.checkpoint)),
            metadata=self.serde.loads_typed((row.metadata_type, row.checkpoint_metadata)),
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": row.checkpoint_ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }
                if row.parent_checkpoint_id
                else None
            ),
            pending_writes=await self._writes(
                s, row.investigation_id, row.checkpoint_ns, row.checkpoint_id
            ),
        )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread = self._thread(config)
        ns = config["configurable"].get("checkpoint_ns", "")
        query = select(InvestigationCheckpoint).where(
            InvestigationCheckpoint.organization_id == self.organization_id,
            InvestigationCheckpoint.investigation_id == thread,
            InvestigationCheckpoint.checkpoint_ns == ns,
        )
        if checkpoint_id := get_checkpoint_id(config):
            query = query.where(InvestigationCheckpoint.checkpoint_id == checkpoint_id)
        else:
            # Checkpoint ids are time-ordered (UUIDv6), as in LangGraph's own savers.
            query = query.order_by(InvestigationCheckpoint.checkpoint_id.desc()).limit(1)
        async with tenant_session(self.organization_id) as s:
            row = await s.scalar(query)
            return await self._tuple(s, row) if row is not None else None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        query = select(InvestigationCheckpoint).where(
            InvestigationCheckpoint.organization_id == self.organization_id
        )
        if config is not None:
            query = query.where(InvestigationCheckpoint.investigation_id == self._thread(config))
            if (ns := config["configurable"].get("checkpoint_ns")) is not None:
                query = query.where(InvestigationCheckpoint.checkpoint_ns == ns)
            if checkpoint_id := get_checkpoint_id(config):
                query = query.where(InvestigationCheckpoint.checkpoint_id == checkpoint_id)
        if before is not None and (before_id := get_checkpoint_id(before)):
            query = query.where(InvestigationCheckpoint.checkpoint_id < before_id)
        query = query.order_by(InvestigationCheckpoint.checkpoint_id.desc())
        async with tenant_session(self.organization_id) as s:
            rows = list(await s.scalars(query))
            out: list[CheckpointTuple] = []
            for row in rows:
                item = await self._tuple(s, row)
                if filter and not all(item.metadata.get(k) == v for k, v in filter.items()):
                    continue
                out.append(item)
                if limit is not None and len(out) >= limit:
                    break
        for item in out:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        thread = self._thread(config)
        ns = config["configurable"].get("checkpoint_ns", "")
        ctype, cbytes = self.serde.dumps_typed(checkpoint)
        mtype, mbytes = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        async with tenant_session(self.organization_id) as s:
            await s.execute(
                insert(InvestigationCheckpoint)
                .values(
                    organization_id=self.organization_id,
                    investigation_id=thread,
                    checkpoint_ns=ns,
                    checkpoint_id=checkpoint["id"],
                    parent_checkpoint_id=config["configurable"].get("checkpoint_id"),
                    checkpoint_type=ctype,
                    checkpoint=cbytes,
                    metadata_type=mtype,
                    checkpoint_metadata=mbytes,
                )
                .on_conflict_do_nothing()
            )
        return {
            "configurable": {
                "thread_id": str(thread),
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread = self._thread(config)
        ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]
        async with tenant_session(self.organization_id) as s:
            for position, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, position)
                vtype, vbytes = self.serde.dumps_typed(value)
                stmt = insert(InvestigationCheckpointWrite).values(
                    organization_id=self.organization_id,
                    investigation_id=thread,
                    checkpoint_ns=ns,
                    checkpoint_id=checkpoint_id,
                    task_id=task_id,
                    idx=idx,
                    channel=channel,
                    value_type=vtype,
                    value=vbytes,
                    task_path=task_path,
                )
                keys = ["investigation_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"]
                if idx >= 0:
                    # Regular writes are kept once (a replayed task must not change them).
                    await s.execute(stmt.on_conflict_do_nothing(index_elements=keys))
                else:
                    # Special channels (errors, interrupts) take the latest value.
                    await s.execute(
                        stmt.on_conflict_do_update(
                            index_elements=keys,
                            set_={"channel": channel, "value_type": vtype, "value": vbytes},
                        )
                    )

    async def adelete_thread(self, thread_id: str) -> None:
        thread = uuid.UUID(str(thread_id))
        async with tenant_session(self.organization_id) as s:
            for model in (InvestigationCheckpointWrite, InvestigationCheckpoint):
                await s.execute(
                    delete(model).where(
                        model.organization_id == self.organization_id,
                        model.investigation_id == thread,
                    )
                )
