import asyncio
import hashlib
import json
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, IncomingMessage, Message
from aio_pika.abc import AbstractRobustChannel, AbstractRobustExchange

from app.core.config import settings
from app.core.logging import get_logger
from app.messaging.amqp_retry import connect_robust_when_ready
from app.services.retry_logic import calculate_delay_ms

logger = get_logger(__name__)

QUORUM_QUEUE_ARGS: dict[str, str] = {"x-queue-type": "quorum"}


def _exchange_type_from_settings(name: str) -> ExchangeType:
    key = name.lower().strip()
    mapping: dict[str, ExchangeType] = {
        "topic": ExchangeType.TOPIC,
        "direct": ExchangeType.DIRECT,
        "fanout": ExchangeType.FANOUT,
        "headers": ExchangeType.HEADERS,
    }
    if key not in mapping:
        raise ValueError(
            f"Unsupported exchange type {name!r}; "
            f"expected one of: {', '.join(sorted(mapping))}"
        )
    return mapping[key]


def _retry_count_from_headers(headers: dict[str, Any]) -> int:
    raw = headers.get("x-retry-count", 0)
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


class RetryOrchestrator:
    """Consumes retry ingress, applies centralized policy, delays via TTL + DLX."""

    def __init__(self) -> None:
        self._connection: aio_pika.RobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._retry_exchange: AbstractRobustExchange | None = None
        self._delay_exchange: AbstractRobustExchange | None = None
        self._dlq_exchange: AbstractRobustExchange | None = None

    async def run(self) -> None:
        self._connection = await connect_robust_when_ready(
            settings.rabbitmq_url,
            logger=logger,
        )
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=settings.rabbitmq_prefetch)

        await self._channel.declare_exchange(
            settings.events_exchange,
            _exchange_type_from_settings("topic"),
            durable=True,
        )

        self._retry_exchange = await self._channel.declare_exchange(
            settings.retry_exchange,
            _exchange_type_from_settings(settings.retry_exchange_type),
            durable=True,
        )

        retry_queue = await self._channel.declare_queue(
            settings.retry_queue,
            durable=True,
            arguments=QUORUM_QUEUE_ARGS,
        )
        await retry_queue.bind(
            self._retry_exchange,
            routing_key=settings.retry_queue_binding_key,
        )

        self._delay_exchange = await self._channel.declare_exchange(
            settings.retry_delay_exchange,
            _exchange_type_from_settings("topic"),
            durable=True,
        )

        delay_queue = await self._channel.declare_queue(
            settings.retry_delay_queue,
            durable=True,
            arguments={
                "x-dead-letter-exchange": settings.events_exchange,
                **QUORUM_QUEUE_ARGS,
            },
        )
        await delay_queue.bind(self._delay_exchange, routing_key="#")

        self._dlq_exchange = await self._channel.declare_exchange(
            settings.dlq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )

        dlq_queue = await self._channel.declare_queue(
            settings.dlq_queue,
            durable=True,
            arguments=QUORUM_QUEUE_ARGS,
        )
        await dlq_queue.bind(
            self._dlq_exchange,
            routing_key=settings.dlq_routing_key,
        )

        logger.info(
            "Retry orchestrator started",
            extra={
                "retry_queue": settings.retry_queue,
                "retry_binding": settings.retry_queue_binding_key,
                "delay_queue": settings.retry_delay_queue,
                "events_exchange": settings.events_exchange,
                "dlq_queue": settings.dlq_queue,
                "max_retries": settings.max_retries,
            },
        )

        await retry_queue.consume(self._on_message)

        await asyncio.Future()

    async def _on_message(self, message: IncomingMessage) -> None:
        try:
            await self._process(message)
        except Exception:
            logger.exception("Orchestrator processing error")
            await message.nack(requeue=False)

    async def _process(self, message: IncomingMessage) -> None:
        try:
            payload = json.loads(message.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            await self._publish_invalid_to_dlq(message, str(exc))
            await message.ack()
            return

        if not isinstance(payload, dict):
            await self._publish_invalid_to_dlq(
                message, "Message body must be a JSON object"
            )
            await message.ack()
            return

        headers = dict(message.headers or {})
        prior_retry = _retry_count_from_headers(headers)
        retry_count = prior_retry + 1

        original_rk = headers.get("x-original-routing-key")
        if not original_rk or not isinstance(original_rk, str):
            await self._publish_to_dlq(
                payload=payload,
                retry_count=prior_retry,
                error_reason="Missing or invalid x-original-routing-key header",
            )
            await message.ack()
            return

        if retry_count > settings.max_retries:
            last_err = headers.get("x-last-error", "")
            await self._publish_to_dlq(
                payload=payload,
                retry_count=prior_retry,
                error_reason=f"Max retries exceeded ({settings.max_retries}): {last_err}",
            )
            await message.ack()
            return

        delay_ms = calculate_delay_ms(retry_count)
        last_error = headers.get("x-last-error")
        await self._publish_delayed_retry(
            payload=payload,
            retry_count=retry_count,
            routing_key=original_rk,
            delay_ms=delay_ms,
            last_error=str(last_error) if last_error is not None else "",
        )

        logger.info(
            "Scheduled retry with delay",
            extra={
                "event_id": payload.get("event_id"),
                "retry_count": retry_count,
                "delay_ms": delay_ms,
                "routing_key": original_rk,
            },
        )

        await message.ack()

    async def _publish_delayed_retry(
        self,
        payload: dict[str, Any],
        retry_count: int,
        routing_key: str,
        delay_ms: int,
        last_error: str,
    ) -> None:
        if not self._delay_exchange:
            raise RuntimeError("Delay exchange is not initialized")

        body = json.dumps(payload, default=str).encode("utf-8")
        out_headers: dict[str, Any] = {"x-retry-count": retry_count}
        if last_error:
            out_headers["x-last-error"] = last_error

        msg = Message(
            body=body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(payload.get("event_id")),
            type=str(payload.get("event_type")) if payload.get("event_type") else None,
            headers=out_headers,
            expiration=delay_ms,
        )

        await self._delay_exchange.publish(msg, routing_key=routing_key)

    async def _publish_to_dlq(
        self,
        payload: dict[str, Any],
        retry_count: int,
        error_reason: str,
    ) -> None:
        if not self._dlq_exchange:
            raise RuntimeError("DLQ exchange is not initialized")

        body = json.dumps(payload, default=str).encode("utf-8")
        dlq_message = Message(
            body=body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(payload.get("event_id")),
            type=payload.get("event_type"),
            headers={
                "x-retry-count": retry_count,
                "x-death-reason": error_reason,
            },
        )

        await self._dlq_exchange.publish(
            dlq_message,
            routing_key=settings.dlq_routing_key,
        )

        logger.info(
            "Message published to DLQ",
            extra={
                "event_id": payload.get("event_id"),
                "retry_count": retry_count,
                "dlq_queue": settings.dlq_queue,
            },
        )

    async def _publish_invalid_to_dlq(
        self,
        message: IncomingMessage,
        decode_error: str,
    ) -> None:
        digest = hashlib.sha256(message.body).hexdigest()[:24]
        payload: dict[str, Any] = {
            "event_id": f"invalid-body-{digest}",
            "event_type": "__invalid_body__",
            "raw_body": message.body.decode("utf-8", errors="replace"),
            "decode_error": decode_error,
            "source": "retry-orchestrator",
        }
        await self._publish_to_dlq(
            payload=payload,
            retry_count=0,
            error_reason=decode_error,
        )
