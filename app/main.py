import asyncio

from app.core.logging import configure_logging
from app.messaging.orchestrator import RetryOrchestrator

configure_logging()


async def main() -> None:
    orchestrator = RetryOrchestrator()
    await orchestrator.run()


if __name__ == "__main__":
    asyncio.run(main())
