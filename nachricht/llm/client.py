import logging
from typing import Optional
from asyncio import to_thread
from openai import OpenAI


logger = logging.getLogger(__name__)

_client = None
_default_model = None


def init_llm_client(host: str, api_key: str, default_model: str) -> OpenAI:
    global _client
    global _default_model
    _client = OpenAI(base_url=host, api_key=api_key)
    _default_model = default_model
    return _client


async def query_llm(
    instructions: str,
    input: str,
    model: Optional[str] = None,
    client: Optional[OpenAI] = None,
) -> str:
    global _default_model
    global _client

    if client is None:
        client = _client

    assert client is not None

    if model is None:
        model = _default_model

    assert model is not None

    response = await to_thread(
        client.chat.completions.create,
        model=model,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": input},
        ],
    )
    result = response.choices[0].message.content.strip()
    return result
