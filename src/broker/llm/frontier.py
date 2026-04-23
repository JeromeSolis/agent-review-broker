from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from broker.config import settings

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
async def complete(
    messages: list[dict],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
) -> str:
    system_content = ""
    user_messages = []
    for m in messages:
        if m["role"] == "system":
            system_content += m["content"] + "\n"
        else:
            user_messages.append({"role": m["role"], "content": m["content"]})

    if json_mode:
        system_content += "\nRespond with valid JSON only. No prose, no markdown code fences."

    client = _get_client()
    resp = await client.messages.create(
        model=settings.frontier_model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_content.strip() or None,
        messages=user_messages,
    )
    return resp.content[0].text
