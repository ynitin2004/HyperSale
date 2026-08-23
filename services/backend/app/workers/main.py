"""Worker entrypoint. M0 establishes the separate process before adding job handlers."""
import asyncio
import logging

logging.basicConfig(level=logging.INFO)


async def run() -> None:
    logging.info("HyperSale worker started; no M0 jobs registered")
    while True:
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(run())

