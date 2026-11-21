"""Chave de cache: sha256 sobre (tenant, equipa, modelo, parâmetros, mensagens) canónicos.

Tenant e equipa estão sempre na chave: duas equipas com o mesmo pedido nunca partilham resposta.
A separação entre campos usa um separador que não aparece no JSON canónico (U+001F), para que
"a|b" + "c" e "a" + "b|c" não colidam.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

_SEP = "\x1f"


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_key(
    *,
    tenant_id: str,
    team: str,
    model: str,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    messages: Sequence[Mapping[str, str]],
) -> str:
    parts = [
        tenant_id,
        team,
        model,
        _canonical({"temperature": temperature, "max_tokens": max_tokens, "json_mode": json_mode}),
        _canonical([dict(m) for m in messages]),
    ]
    digest = hashlib.sha256(_SEP.join(parts).encode("utf-8")).hexdigest()
    return f"costpilot:cache:{digest}"
