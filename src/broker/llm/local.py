from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from broker.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=settings.local_llm_base_url,
            api_key=settings.local_llm_api_key,
        )
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
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    client = _get_client()
    resp = await client.chat.completions.create(
        model=settings.local_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        **kwargs,
    )
    return resp.choices[0].message.content or ""
