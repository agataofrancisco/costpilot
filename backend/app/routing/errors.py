"""Erros de domínio do routing. A API traduz cada um para um código HTTP e um `code` estável."""

from __future__ import annotations

from typing import Any


class RoutingError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class TeamNotConfigured(RoutingError):
    status_code = 403
    code = "team_not_configured"


class PolicyOverrideDisabled(RoutingError):
    status_code = 403
    code = "policy_override_disabled"


class ToolsNotSupported(RoutingError):
    status_code = 422
    code = "tools_not_supported"


class NoEligibleModel(RoutingError):
    status_code = 422
    code = "no_eligible_model"


class BudgetExceeded(RoutingError):
    status_code = 402
    code = "budget_exceeded"


class UpstreamUnavailable(RoutingError):
    status_code = 503
    code = "upstream_unavailable"
