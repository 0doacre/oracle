"""Le point, écrit entièrement en Python à partir du briefing.

Deux formes :
- courte (le mail) : « Les 5 choses à savoir », une ligne par dossier suivi, les
  dossiers qui bougent ou se décident le plus ;
- complète (la page, et le point local) : les 5 choses, puis chaque dossier avec
  tous ses marchés, puis les marchés hors dossier.

Pas de LLM, décidé après trois vrais essais avec Ministral 8B (Ollama, local) :
il recopiait bien les chiffres, mais il a inversé le côté d'un pari (« sur le
non » pour un ordre sur OUI), fait « succéder Schumer à Schumer », et présenté les
prix comme des avis ou des certitudes (« 12,5 % des sondés », « la Fed
augmentera »). Ici, chaque phrase vient d'un modèle fixe : aucune erreur de sens
n'est possible, au prix d'intitulés de marchés laissés en anglais (les noms des
dossiers, eux, sont en français : c'est l'utilisateur qui les choisit).
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from oracle.temps import a_paris

BRIEFING_VIEUX_H = 3
NB_CHOSES = 5
# Un mouvement (confirmé, voir selection.horizons_confirmes) est cité à partir de
# ces seuils, en points.
SEUILS_MOUVEMENT = {"delta_1h": 2.0, "delta_6h": 3.0, "delta_24h": 4.0}
LIBELLES_HORIZON = {"delta_1h": "1 h", "delta_6h": "6 h", "delta_24h": "24 h"}
PIC_VOLUME = 3.0
ECHEANCE_IMMINENTE_J = 2
NB_TITRES_MAIL = 2
NB_TITRES_PAGE = 3
# Ce qui rend un dossier important aujourd'hui, en plus du score de son marché phare.
BONUS = {"alerte": 20, "mouvement": 15, "echeance": 15}


# ---------- Ce qu'un marché a de notable ----------

def _horizon_marquant(m: dict) -> tuple[str, float] | None:
    """L'horizon confirmé dont le mouvement dépasse le plus son seuil, et ce rapport."""
    meilleur = None
    for champ in m.get("confirmed_moves") or []:
        seuil = SEUILS_MOUVEMENT.get(champ)
        if seuil and m.get(champ) is not None and abs(m[champ]) >= seuil:
            rapport = abs(m[champ]) / seuil
            if meilleur is None or rapport > meilleur[1]:
                meilleur = (champ, rapport)
    return meilleur


def _imminent(m: dict) -> bool:
    return m.get("days_left") is not None and 0 <= m["days_left"] <= ECHEANCE_IMMINENTE_J


def _notable(m: dict) -> list[str]:
    """Les raisons d'en parler, de la plus forte à la plus faible."""
    raisons = []
    a = m.get("trade_alert")
    if a:
        cote = "le OUI" if a["side"] == "YES" else "le NON"
        texte = (f"gros ordre de {_montant(a['amount_usd'])} $ sur {cote}, "
                 f"{_nombre(a['share_24h'] * 100)} % du volume du jour")
        if a.get("wallet_profile"):
            texte += f", {a['wallet_profile'].lower()}"
        raisons.append(texte)
    marquant = _horizon_marquant(m)
    if marquant:
        champ = marquant[0]
        raisons.append(f"**{_signe(m[champ])} pt en {LIBELLES_HORIZON[champ]}**")
    if (m.get("volume_ratio") or 0) >= PIC_VOLUME:
        raisons.append(f"volume × {_nombre(m['volume_ratio'])} par rapport aux jours précédents")
    if _imminent(m):
        raisons.append(f"se décide {_quand(m['days_left']).lower()}")
    return raisons


def _importance(m: dict) -> float:
    return ((m.get("score") or 0)
            + (BONUS["alerte"] if m.get("trade_alert") else 0)
            + (BONUS["mouvement"] if _horizon_marquant(m) else 0)
            + (BONUS["echeance"] if _imminent(m) else 0))


def _phrase(m: dict) -> str:
    # La mini-courbe (24 h, une case par heure) suit le prix : elle montre d'où il vient.
    courbe = f" {m['sparkline_24h']}" if m.get("sparkline_24h") else ""
    texte = f"« {m['title']} » : {_nombre(m['yes_prob'])} % au OUI{courbe} ({m['source']})"
    raisons = _notable(m)
    return texte + (" — " + " ; ".join(raisons) if raisons else "") + "."


# ---------- Les 5 choses à savoir ----------

def _par_dossier(marches: list[dict]) -> dict[str, list[dict]]:
    groupes: dict[str, list[dict]] = {}
    for m in marches:
        if m.get("dossier"):
            groupes.setdefault(m["dossier"], []).append(m)
    for lot in groupes.values():
        lot.sort(key=_importance, reverse=True)
    return groupes


def dossiers_classes(briefing: dict) -> list[str]:
    """Les dossiers de marchés, du plus important au moins important aujourd'hui."""
    groupes = _par_dossier(briefing["markets"])
    return sorted(groupes, key=lambda nom: _importance(groupes[nom][0]), reverse=True)


def _titres(actualites: dict | None, nom: str, n: int) -> list[str]:
    """Les n titres de presse les plus récents du dossier, en puces avec lien."""
    lot = ((actualites or {}).get("dossiers") or {}).get(nom, [])[:n]
    return [f"- [{d['title']}]({d['url']}) — {d['source']}, {_heure(d['published'])}" for d in lot]


def _heure(iso: str) -> str:
    try:
        return f"{a_paris(datetime.fromisoformat(iso)):%Hh%M}"
    except ValueError:
        return ""


def cinq_choses(briefing: dict, n: int = NB_CHOSES, actualites: dict | None = None) -> str:
    """Une ligne par dossier, pour les n dossiers les plus importants aujourd'hui,
    avec ses deux titres de presse les plus récents."""
    lignes = ["## Les 5 choses à savoir", ""]
    erreurs = briefing["meta"].get("errors") or {}
    groupes = _par_dossier(briefing["markets"])
    classes = sorted(groupes.items(), key=lambda g: _importance(g[1][0]), reverse=True)[:n]
    for rang, (nom, lot) in enumerate(classes, 1):
        reste = len(lot) - 1
        suite = f" *(+ {reste} autre{'s' if reste > 1 else ''} sur la page)*" if reste else ""
        lignes.append(f"{rang}. **{nom}** — {_phrase(lot[0])}{suite}")
        titres = _titres(actualites, nom, NB_TITRES_MAIL)
        if titres:
            lignes += titres + [""]
    if not classes:
        lignes.append("Aucun dossier suivi n'a de marché actif dans ce relevé.")
    if erreurs:
        lignes += ["", f"> ⚠ Sources en panne pendant le relevé : {', '.join(sorted(erreurs))}."]
    return "\n".join(lignes)


def aussi_suivi(actualites: dict | None) -> str:
    """Les dossiers d'actualité seule (aucun marché n'en parle), avec leurs titres."""
    noms = (actualites or {}).get("news_only") or []
    if not noms:
        return ""
    lignes = ["## Aussi suivi"]
    for nom in noms:
        titres = _titres(actualites, nom, NB_TITRES_PAGE)
        lignes += ["", f"**{nom}**", ""] + (titres or ["Rien de neuf dans les flux suivis."])
    return "\n".join(lignes)


# ---------- Le détail (page) ----------

def detail(briefing: dict, actualites: dict | None = None) -> str:
    """Chaque dossier avec tous ses marchés et ses titres, puis les marchés hors dossier."""
    lignes = ["## Par dossier"]
    groupes = _par_dossier(briefing["markets"])
    for nom, lot in sorted(groupes.items(), key=lambda g: _importance(g[1][0]), reverse=True):
        lignes += ["", f"### {nom}", ""]
        lignes += ["- " + _ligne(m) for m in lot]
        titres = _titres(actualites, nom, NB_TITRES_PAGE)
        if titres:
            lignes += ["", "*Dans l'actualité :*", ""] + titres
    hors = sorted((m for m in briefing["markets"] if not m.get("dossier")),
                  key=_importance, reverse=True)
    if hors:
        lignes += ["", "## Hors dossiers", ""]
        lignes += ["- " + _ligne(m) for m in hors]
    return "\n".join(lignes)


def _ligne(m: dict) -> str:
    variations = [f"{_signe(m[c])} pt en {LIBELLES_HORIZON[c]}"
                  for c in m.get("confirmed_moves") or [] if m.get(c) is not None]
    texte = _phrase(m)
    if variations:
        texte += f" Variations : {', '.join(variations)}."
    if m.get("end_date"):
        texte += f" Échéance {m['end_date']}."
    if m.get("resolution_summary"):
        texte += f" *{m['resolution_summary']}*"
    return texte


# ---------- Mise en forme ----------

def _montant(x: float) -> str:
    return f"{round(x):,}".replace(",", " ")


def _nombre(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _signe(x: float) -> str:
    return ("+" if x > 0 else "−" if x < 0 else "±") + _nombre(abs(x))


def _quand(jours: int) -> str:
    return {0: "Aujourd'hui", 1: "Demain"}.get(jours, f"Dans {jours} jours")


def composer(briefing: dict, maintenant: datetime, court: bool = False,
             actualites: dict | None = None, meteo: str | None = None) -> tuple[str, list[str]]:
    """Le point en Markdown (court : le mail ; sinon : la page), et les remarques
    à journaliser. `actualites` : sortie de actualite.vers_json, facultative."""
    remarques = []
    lignes = [f"# Oracle — {a_paris(maintenant):%d/%m/%Y à %Hh%M}", ""]
    meta = briefing["meta"]
    genere = _date(meta.get("generated_at"))
    if genere and (maintenant - genere).total_seconds() > BRIEFING_VIEUX_H * 3600:
        remarques.append(f"briefing vieux de plus de {BRIEFING_VIEUX_H} h ({genere:%d/%m %H:%M})")
        lignes += [f"> ⚠ Briefing ancien : relevé du {a_paris(genere):%d/%m/%Y à %H:%M}.", ""]
    if meteo:
        lignes += [meteo, ""]
    lignes.append(cinq_choses(briefing, actualites=actualites))
    suivi_seul = aussi_suivi(actualites)
    if suivi_seul:
        lignes += ["", suivi_seul]
    if not court:
        lignes += ["", detail(briefing, actualites)]
    lignes += ["", "---", "",
               f"*{len(briefing['markets'])} marchés retenus sur {meta.get('total_scanned', 0)} "
               f"lus. Chaque pourcentage est le prix du OUI sur un marché de prédiction : ni un "
               f"sondage, ni une prévision. Information, pas conseil.*", ""]
    return "\n".join(lignes), remarques


def _date(iso: str | None) -> datetime | None:
    try:
        d = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    from oracle.collecteur import Journal

    p = argparse.ArgumentParser(description="Écrit le point (complet) à partir du briefing.")
    p.add_argument("--briefing", default="briefing_oracle.json")
    p.add_argument("--dossier", default="points")
    p.add_argument("--journal", default=None)
    args = p.parse_args(argv)
    journal = Journal(args.journal)

    try:
        briefing = json.loads(Path(args.briefing).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        journal(f"point matinal : briefing illisible ({e})")
        return 2
    maintenant = datetime.now(timezone.utc)
    texte, remarques = composer(briefing, maintenant)
    dossier = Path(args.dossier)
    dossier.mkdir(exist_ok=True)
    chemin = dossier / f"{a_paris(maintenant):%Y-%m-%d}.md"
    chemin.write_text(texte, encoding="utf-8")
    for r in remarques:
        journal(f"point matinal : {r}")
    journal(f"point matinal : {chemin} ({len(texte)} caractères)")
    return 0
