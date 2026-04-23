import asyncio

from broker.agents.broker import make_broker_from_env
from broker.config import AgentRole, settings
from broker.db import init_db
from broker.ingestion.papers import ingest_papers
from broker.logging import log, record_trajectory, setup_logging
from broker.platform import get_platform_client
from broker.scheduler import run_scheduler


async def _run() -> None:
    setup_logging()
    await init_db()

    platform = get_platform_client()
    await platform.connect()

    if settings.agent_role == AgentRole.BROKER:
        agent = make_broker_from_env()
    else:
        # Scout and Marketer implementations land after Broker is proven live.
        raise NotImplementedError(f"agent role {settings.agent_role} not implemented yet")

    await record_trajectory(
        "agent_boot",
        agent_id=agent.agent_id,
        payload={
            "role": settings.agent_role.value,
            "llm_mode": settings.llm_mode.value,
            "kill_switch": settings.llm_kill_switch_to_local,
        },
    )

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(ingest_papers(platform), name="ingestion")
            tg.create_task(run_scheduler(platform, agent), name="scheduler")
    finally:
        await platform.close()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("shutdown_keyboard_interrupt")


if __name__ == "__main__":
    main()
