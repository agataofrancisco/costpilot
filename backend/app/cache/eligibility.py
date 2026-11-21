"""Elegibilidade estrita para cache. Verificada ANTES de ler, não só antes de gravar."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheEligibility:
    eligible: bool
    reason: str


def cache_eligibility(
    *, requested: bool, temperature: float, requires_tools: bool, sensitivity: str
) -> CacheEligibility:
    if not requested:
        return CacheEligibility(False, "cache_not_requested")
    if temperature != 0:
        return CacheEligibility(False, "temperature_not_zero")
    if requires_tools:
        return CacheEligibility(False, "has_tools")
    if sensitivity == "high":
        return CacheEligibility(False, "sensitive")
    return CacheEligibility(True, "eligible")
