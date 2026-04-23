import os

from broker.config import settings
from broker.platform.base import PlatformClient


def get_platform_client() -> PlatformClient:
    """Return the appropriate platform client based on env.

    PLATFORM_MODE=mock selects the in-memory mock (pre-launch + tests).
    Anything else defaults to the real Koala client.
    """
    mode = os.getenv("PLATFORM_MODE", "mock").lower()
    if mode == "mock":
        from broker.platform.mock import MockPlatformClient, make_sample_papers

        return MockPlatformClient(
            agent_id=settings.agent_id or "mock-agent",
            seed_papers=make_sample_papers(5),
        )

    from broker.platform.koala import KoalaPlatformClient

    return KoalaPlatformClient(agent_id=settings.agent_id)
