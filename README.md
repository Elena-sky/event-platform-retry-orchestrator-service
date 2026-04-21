# event-platform-retry-orchestrator-service

Centralized **retry policy** for the event platform: consumes failure messages from `retry.exchange`, applies backoff (per-message TTL into a delay queue with DLX back to `events.topic`), tracks `x-retry-count`, and routes exhausted messages to the **DLQ**.

Work together with **[event-platform-notification-service](../event-platform-notification-service/README.md)** — it forwards temporary failures here (`retry.exchange`, headers `x-retry-count`, `x-original-routing-key`, `x-last-error`). That README describes consumer behaviour, boot order with this service, and DLQ semantics.

## Flow

```mermaid
flowchart TD
    NS(["notification-service\nTemporaryNotificationError"])
    NS -->|"x-retry-count, x-original-routing-key"| RX["retry.exchange"]
    RX --> RI["retry.ingress queue"]

    RI --> CHK{"x-retry-count\n<= MAX_RETRIES?"}

    CHK -->|yes — increment count\ncalculate tier| DQ

    subgraph DQ["Delay queues  (x-message-ttl + DLX → events.topic)"]
        D1["delay-5s\nattempt 1"]
        D2["delay-30s\nattempt 2"]
        D3["delay-120s\nattempt 3"]
        D4["delay-600s\nattempt 4"]
    end

    DQ -->|TTL expired\ndead-letter exchange| ET(["events.topic"])
    ET -->|re-routed via x-original-routing-key| NS2(["notification-service\nnext attempt"])

    CHK -->|no — retries exhausted| DLQ(["events.dlq"])
```

```mermaid
flowchart LR
    subgraph "Backoff tiers"
        T1["Attempt 1 →  5 s"]
        T2["Attempt 2 →  30 s"]
        T3["Attempt 3 →  2 min"]
        T4["Attempt 4 →  10 min"]
        TX["Attempt 5+ →  DLQ"]
    end
    T1 --> T2 --> T3 --> T4 --> TX
```

## Repositories

[GitHub: Elena-sky](https://github.com/Elena-sky)

- [event-platform-gateway-api](https://github.com/Elena-sky/event-platform-gateway-api)
- [event-platform-notification-service](https://github.com/Elena-sky/event-platform-notification-service)
- [event-platform-analytics-audit-service](https://github.com/Elena-sky/event-platform-analytics-audit-service)
- [event-platform-retry-orchestrator-service](https://github.com/Elena-sky/event-platform-retry-orchestrator-service)
- [event-platform-infra](https://github.com/Elena-sky/event-platform-infra)

## Requirements

- **Python 3.12 or 3.13**
- RabbitMQ (e.g. [event-platform-infra](https://github.com/Elena-sky/event-platform-infra))

## Boot order

1. Start RabbitMQ (`event-platform-infra`: `docker compose up -d`).
2. Start this service so exchanges/queues/bindings exist **before** producers send retry traffic (notification only declares the retry exchange; this service owns the ingress queue, delay topology, and DLQ bindings).
3. Start **event-platform-notification-service** and **event-platform-gateway-api** as needed.

## Configuration

```bash
cp .env.example .env
```

Align `EVENTS_EXCHANGE`, `DLQ_*`, and broker credentials with the gateway and notification services. `MAX_RETRIES=4` matches the four delay tiers (5s → 30s → 2m → 10m).

## Run locally

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

## Run with Docker

```bash
docker compose up --build
```

Requires `EVENT_PLATFORM_NETWORK_NAME` in `.env` to match `event-platform-infra`, and broker hostname `rabbitmq` is set by Compose.

## Development

```bash
pip install -r requirements-dev.txt
ruff check app tests
ruff format app tests
pytest
```
