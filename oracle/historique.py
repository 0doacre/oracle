"""Historique léger des relevés en SQLite : variations sur 1 h, 6 h et 24 h, et
pics de volume. Le collecteur tourne toutes les heures ; chaque horizon prend
pour référence le relevé le plus récent qui a au moins l'âge voulu, dans une
fenêtre bornée (un relevé trop vieux ne compte pas)."""

import sqlite3
import statistics
from pathlib import Path

from oracle.marche import Marche

H = 3600
# horizon → (âge minimal, âge maximal) du relevé de référence, en heures.
# 1 h : relevés horaires, avec une marge pour une exécution GitHub en retard.
HORIZONS = {"1h": (0.75, 2), "6h": (5, 8), "24h": (24, 48)}
CONSERVATION_J = 7

# Pic de volume : volume des dernières 24 h comparé à sa médiane des jours
# précédents. Il faut quelques relevés de plus de 20 h pour juger.
VOLUME_AGE_MIN_H = 20
VOLUME_RELEVES_MIN = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS releves (
    source     TEXT    NOT NULL,
    market_id  TEXT    NOT NULL,
    timestamp  INTEGER NOT NULL,
    yes_price  REAL    NOT NULL,
    volume_24h REAL    NOT NULL,
    PRIMARY KEY (source, market_id, timestamp)
);
"""


class Historique:
    def __init__(self, chemin: str | Path = ":memory:"):
        self.base = sqlite3.connect(str(chemin))
        self.base.executescript(SCHEMA)

    def fermer(self) -> None:
        self.base.close()

    def enregistrer(self, marches: list[Marche], maintenant: int) -> None:
        with self.base:
            self.base.executemany(
                "INSERT OR REPLACE INTO releves VALUES (?, ?, ?, ?, ?)",
                [(m.source, m.id, maintenant, m.prob, m.volume_24h) for m in marches],
            )
            self.base.execute("DELETE FROM releves WHERE timestamp < ?",
                              (maintenant - CONSERVATION_J * 24 * H,))

    def variation(self, marche: Marche, maintenant: int, horizon: str) -> float | None:
        """Variation en points depuis le relevé de référence de cet horizon, ou None."""
        age_min, age_max = HORIZONS[horizon]
        ligne = self.base.execute(
            "SELECT yes_price FROM releves WHERE source = ? AND market_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT 1",
            (marche.source, marche.id,
             maintenant - int(age_max * H), maintenant - int(age_min * H)),
        ).fetchone()
        return None if ligne is None else round(marche.prob - ligne[0], 1)

    def delta_24h(self, marche: Marche, maintenant: int) -> float | None:
        return self.variation(marche, maintenant, "24h")

    def ratio_volume(self, marche: Marche, maintenant: int) -> float | None:
        """Volume 24 h actuel ÷ médiane des volumes 24 h relevés il y a plus de 20 h.
        None si l'historique est trop court ou la médiane nulle."""
        volumes = [v for (v,) in self.base.execute(
            "SELECT volume_24h FROM releves WHERE source = ? AND market_id = ? "
            "AND timestamp <= ?",
            (marche.source, marche.id, maintenant - VOLUME_AGE_MIN_H * H))]
        if len(volumes) < VOLUME_RELEVES_MIN:
            return None
        mediane = statistics.median(volumes)
        return round(marche.volume_24h / mediane, 2) if mediane > 0 else None

    def serie(self, source: str, market_id: str, depuis: int) -> list[tuple[int, float]]:
        """(timestamp, prix du OUI) de chaque relevé depuis `depuis`, dans l'ordre."""
        return list(self.base.execute(
            "SELECT timestamp, yes_price FROM releves WHERE source = ? AND market_id = ? "
            "AND timestamp >= ? ORDER BY timestamp", (source, market_id, depuis)))

    def annoter(self, marche: Marche, maintenant: int) -> None:
        """Remplit les trois variations et le ratio de volume du marché."""
        marche.delta_1h = self.variation(marche, maintenant, "1h")
        marche.delta_6h = self.variation(marche, maintenant, "6h")
        marche.delta_24h = self.variation(marche, maintenant, "24h")
        marche.ratio_volume = self.ratio_volume(marche, maintenant)
