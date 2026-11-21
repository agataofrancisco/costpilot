"""Interruptor do autopilot por equipa. Sem linha na BD, vale o default de `config/teams.yaml`."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.accounting.repository import utc_now_naive
from app.accounting.tables import TeamSetting


class TeamSettingsRepository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def autopilot_enabled(self, team: str, default: bool) -> bool:
        with self._sessions() as session:
            row = session.get(TeamSetting, team)
            return default if row is None else bool(row.autopilot_enabled)

    def set_autopilot(self, team: str, enabled: bool) -> None:
        with self._sessions() as session, session.begin():
            row = session.get(TeamSetting, team)
            if row is None:
                session.add(
                    TeamSetting(team=team, autopilot_enabled=enabled, updated_at=utc_now_naive())
                )
            else:
                row.autopilot_enabled = enabled
                row.updated_at = utc_now_naive()

    def overrides(self) -> dict[str, bool]:
        with self._sessions() as session:
            rows = session.execute(select(TeamSetting.team, TeamSetting.autopilot_enabled)).all()
        return {team: bool(enabled) for team, enabled in rows}
