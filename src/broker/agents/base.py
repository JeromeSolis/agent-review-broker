from abc import ABC, abstractmethod

from broker.platform.base import PlatformClient
from broker.scheduler.state_machine import PaperTask


class Agent(ABC):
    agent_id: str

    @abstractmethod
    async def on_discussion_tick(self, task: PaperTask, platform: PlatformClient) -> None:
        """Called during the 0-48h discussion phase."""

    @abstractmethod
    async def on_verdict_tick(
        self, task: PaperTask, platform: PlatformClient, *, urgent: bool = False
    ) -> None:
        """Called during the 48-72h verdict phase. If urgent, must submit before returning."""
