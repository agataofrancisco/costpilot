"""Autenticação de clientes da API.

Cada chave de API está associada, no servidor, a um principal fixo: (tenant, equipa).
O cliente nunca indica a equipa ou o tenant no pedido; essa identidade vem só da chave.

Só se guarda o SHA-256 de cada chave (`key_sha256`). A chave em claro não fica em disco
nem em logs. Comparação dos digests em tempo constante (`hmac.compare_digest`).

Gerar o digest de uma chave:  python -m app.auth.clients hash <chave>
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from app.catalog.pricing import ConfigError
from app.routing.errors import Unauthorized

NAME_PATTERN = re.compile(r"^[a-z0-9_-]{1,40}$")
TENANT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MAX_TOKEN_CHARS = 512


@dataclass(frozen=True, slots=True)
class Principal:
    name: str
    tenant_id: str
    team: str


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class ClientRegistry:
    def __init__(self, principals: Mapping[str, Principal]) -> None:
        """`principals`: digest SHA-256 (hex) -> principal."""
        self._by_digest = dict(principals)

    @classmethod
    def load(cls, path: Path) -> ClientRegistry:
        if not path.exists():
            raise ConfigError(f"ficheiro de clientes em falta: {path}")
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping) or not isinstance(raw.get("clients"), list):
            raise ConfigError("clients.yaml: raiz tem de ter a lista 'clients'")
        principals: dict[str, Principal] = {}
        for index, entry in enumerate(raw["clients"]):
            where = f"clients[{index}]"
            if not isinstance(entry, Mapping):
                raise ConfigError(f"{where}: tem de ser um mapa")
            name = _pattern(entry, "name", NAME_PATTERN, where)
            tenant = _pattern(entry, "tenant_id", TENANT_PATTERN, where)
            team = _pattern(entry, "team", NAME_PATTERN, where)
            digest = entry.get("key_sha256")
            if not isinstance(digest, str) or not DIGEST_PATTERN.match(digest):
                raise ConfigError(f"{where}: key_sha256 tem de ser SHA-256 hexadecimal minúsculo")
            if digest in principals:
                raise ConfigError(f"{where}: chave duplicada")
            principals[digest] = Principal(name=name, tenant_id=tenant, team=team)
        return cls(principals)

    def authenticate(self, authorization: str | None) -> Principal:
        if not authorization:
            raise Unauthorized("chave de API em falta (cabeçalho Authorization: Bearer)")
        scheme, _, token = authorization.partition(" ")
        token = token.strip()
        if scheme.lower() != "bearer" or not token or len(token) > MAX_TOKEN_CHARS:
            raise Unauthorized("cabeçalho Authorization inválido")
        digest = hash_key(token)
        found: Principal | None = None
        # Percorre todas as entradas para não revelar pela duração qual chave existe.
        for stored, principal in self._by_digest.items():
            if hmac.compare_digest(stored, digest):
                found = principal
        if found is None:
            raise Unauthorized("chave de API inválida")
        return found


def _pattern(entry: Mapping[str, Any], key: str, pattern: re.Pattern[str], where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not pattern.match(value):
        raise ConfigError(f"{where}: '{key}' em falta ou inválido")
    return value


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "hash":
        print(hash_key(argv[2]))
        return 0
    print("uso: python -m app.auth.clients hash <chave>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
