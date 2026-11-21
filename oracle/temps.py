"""L'heure de Paris : les envois et « aujourd'hui » se comptent en heure française,
été comme hiver, que le code tourne sur ce PC ou sur un serveur GitHub (UTC)."""

from datetime import datetime
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def a_paris(moment: datetime) -> datetime:
    return moment.astimezone(PARIS)
