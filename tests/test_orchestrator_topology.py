"""Topology tests: retry / delay / DLQ queues are declared as quorum.

These tests pin three invariants:
1. ``QUORUM_QUEUE_ARGS`` matches the canonical ``{"x-queue-type": "quorum"}``
   literal — keeps this service's DLQ declare byte-equivalent with the one
   in event-platform-notification-service. RabbitMQ rejects a second
   ``queue.declare`` with ``inequivalent arg`` if the dicts diverge.
2. ``RetryOrchestrator.run`` declares ``retry.orchestrator``, ``retry.delay.buffer``
   and the DLQ as quorum.
3. ``retry.delay.buffer`` keeps its ``x-dead-letter-exchange`` argument
   alongside the new ``x-queue-type`` — quorum + TTL+DLX must coexist.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.messaging.orchestrator import QUORUM_QUEUE_ARGS, RetryOrchestrator


def test_quorum_queue_args_is_canonical_literal() -> None:
    """Catch drift with notification-service's DLQ declare."""
    assert QUORUM_QUEUE_ARGS == {"x-queue-type": "quorum"}


def test_run_declares_retry_delay_and_dlq_queues() -> None:
    asyncio.run(_run_declares_retry_delay_and_dlq_queues())


async def _run_declares_retry_delay_and_dlq_queues() -> None:
    channel = AsyncMock()
    channel.declare_exchange = AsyncMock(return_value=AsyncMock())

    declared_queue = AsyncMock()
    declared_queue.bind = AsyncMock()
    declared_queue.consume = AsyncMock()
    channel.declare_queue = AsyncMock(return_value=declared_queue)

    connection = AsyncMock()
    connection.channel = AsyncMock(return_value=channel)

    orch = RetryOrchestrator()

    with patch(
        "app.messaging.orchestrator.connect_robust_when_ready",
        AsyncMock(return_value=connection),
    ):
        # ``run()`` ends with ``await asyncio.Future()`` — break out via a
        # short timeout once topology is declared.
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(orch.run(), timeout=0.1)

    queue_calls = channel.declare_queue.call_args_list
    assert len(queue_calls) == 3, (
        "Expected three declare_queue calls (retry, delay, dlq), got "
        f"{len(queue_calls)}: {queue_calls}"
    )

    # Order in run(): retry_queue, delay_queue, dlq_queue.
    retry_call, delay_call, dlq_call = queue_calls

    assert retry_call.kwargs["arguments"] == QUORUM_QUEUE_ARGS

    # Delay queue must keep its DLX *and* be quorum — both arguments must
    # be present, since dropping either silently breaks retry semantics
    # (no DLX → messages stuck) or HA (no quorum → classic queue).
    assert delay_call.kwargs["arguments"] == {
        "x-dead-letter-exchange": settings.events_exchange,
        "x-queue-type": "quorum",
    }

    assert dlq_call.kwargs["arguments"] == QUORUM_QUEUE_ARGS
