"""Storage abstraction. Agent logic depends on Tracker, never on Sheets directly."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Application:
    company: str
    role: str
    date_applied: str   # ISO date, e.g. "2026-06-03"
    source: str
    status: str
    last_updated: str   # ISO datetime
    notes: str = ""


class Tracker(ABC):
    """Backend-agnostic interface for the application store."""

    @abstractmethod
    def add_application(self, company: str, role: str, source: str,
                        date_applied: str | None = None, notes: str = "") -> Application: ...

    @abstractmethod
    def update_status(self, company: str, role: str, status: str,
                      note: str | None = None) -> Application: ...

    @abstractmethod
    def get_applications(self, since: datetime | None = None,
                         status: str | None = None) -> list[Application]: ...

    @abstractmethod
    def find_application(self, company: str, role: str) -> Application | None: ...
