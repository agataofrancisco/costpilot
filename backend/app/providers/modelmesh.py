"""ModelMesh como provider opcional.

O ModelMesh expõe uma API compatível com OpenAI. Aponta-se o `base_url` para ele e usa-se uma
chave virtual. O custo continua a ser contabilizado do lado do CostPilot (ver routing/executor.py).
"""

from __future__ import annotations

from app.providers.openai_compatible import OpenAICompatibleAdapter


def build_modelmesh_adapter(
    base_url: str, virtual_key: str | None, timeout_seconds: float
) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        name="modelmesh",
        base_url=base_url,
        api_key=virtual_key,
        timeout_seconds=timeout_seconds,
    )
