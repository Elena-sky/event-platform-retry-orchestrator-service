"""Boot-time helper: retry AMQP until RabbitMQ accepts the connection."""

from __future__ import annotations

import asyncio
import logging

import aio_pika


async def connect_robust_when_ready(
    url: str,
    *,
    logger: logging.Logger,
    attempts: int = 90,
    delay_seconds: float = 2.0,
) -> aio_pika.RobustConnection:
    last_exc: BaseException | None = None
    for n in range(1, attempts + 1):
        try:
            return await aio_pika.connect_robust(url)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "RabbitMQ not reachable yet (%s/%s): %s",
                n,
                attempts,
                exc,
            )
            await asyncio.sleep(delay_seconds)
    assert last_exc is not None
    raise last_exc
