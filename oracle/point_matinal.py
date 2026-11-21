"""Le point matinal, écrit entièrement en Python à partir du briefing.

Pas de LLM, décidé après trois vrais essais avec Ministral 8B (Ollama, local) :
il recopiait bien les chiffres, mais il a inversé le côté d'un pari (« sur le
non » pour un ordre sur OUI), fait « succéder Schumer à Schumer », et présenté les
prix comme des avis ou des certitudes (« 12,5 % des sondés », « la Fed
augmentera », « Schumer sera le prochain leader »). Un contrôle par liste de mots
en attrapait une partie seulement. Ici, chaque phrase vient d'un modèle fixe :
aucune erreur de sens n'est possible, au prix d'intitulés laissés en anglais.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from oracle.temps import a_paris
from oracle.themes import CATEGORIES

BRIEFING_VIEUX_H = 3
# Un mouvement mérite d'être cité à partir de ces seuils, en points.
SEUILS_MOUVEMENT = {"delta_1h": 2.0, "delta_6h": 3.0, "delta_24h": 4.0}
LIBELLES_HORIZON = {"delta_1h": "1 h", "delta_6h": "6 h", "delta_24h": "24 h"}
NB_MOUVEMENTS = 5
PIC_VOLUME = 3.0
ECHEANCE_PROCHE_J = 7


def essentiel(briefing: dict) -> str:
    """Ce qui se joue aujourd'hui : gros ordres, mouvements, pics de volume,
    échéances proches, sources en panne."""
    marches = briefing["markets"]
    lignes = ["## L'essentiel", ""]
    erreurs = briefing["meta"].get("errors") or {}
    if erreurs:
        lignes.append(f"- Sources en panne pendant le relevé : {', '.join(sorted(erreurs))}.")

    alertes = [m for m in marches if m.get("trade_alert")]
    for m in alertes:
        a = m["trade_alert"]
        cote = "le OUI" if a["side"] == "YES" else "le NON"
        texte = (f"- **Gros ordre** : {_montant(a['amount_usd'])} $ misés sur {cote} — "
                 f"« {m['title']} » ({m['source']}). Le marché donne {_nombre(m['yes_prob'])} % "
                 f"au OUI ; cet ordre pèse {_nombre(a['share_24h'] * 100)} % du volume du jour")
        if a.get("wallet_profile"):
            texte += f", {a['wallet_profile'].lower()}"
        lignes.append(texte + ".")
    if not alertes:
        lignes.append("- Aucun gros ordre atypique.")

    lignes += ["", "### Ce qui bouge", ""]
    bougent = sorted((m for m in marches if _horizon_marquant(m)),
                     key=lambda m: _horizon_marquant(m)[1], reverse=True)[:NB_MOUVEMENTS]
    for m in bougent:
        champ, _ = _horizon_marquant(m)
        autres = [f"{_signe(m[c])} en {LIBELLES_HORIZON[c]}" for c in SEUILS_MOUVEMENT
                  if c != champ and m.get(c) is not None]
        lignes.append(f"- **{_signe(m[champ])} pt en {LIBELLES_HORIZON[champ]}**"
                      + (f" ({', '.join(autres)})" if autres else "")
                      + f" — « {m['title']} » : {_nombre(m['yes_prob'])} % au OUI ({m['source']}).")
    if not bougent:
        sans_historique = all(m.get(c) is None for m in marches for c in SEUILS_MOUVEMENT)
        lignes.append("- Rien n'a bougé de 2 points en 1 h, 3 en 6 h ou 4 en 24 h"
                      + (" (pas encore d'historique)." if sans_historique else "."))

    pics = sorted((m for m in marches if (m.get("volume_ratio") or 0) >= PIC_VOLUME),
                  key=lambda m: m["volume_ratio"], reverse=True)
    if pics:
        lignes += ["", "### S'échange plus que d'habitude", ""]
        for m in pics:
            lignes.append(f"- **Volume × {_nombre(m['volume_ratio'])}** par rapport aux jours "
                          f"précédents — « {m['title']} » : {_nombre(m['yes_prob'])} % au OUI "
                          f"({m['source']}).")

    proches = sorted((m for m in marches
                      if m.get("days_left") is not None and 0 <= m["days_left"] <= ECHEANCE_PROCHE_J),
                     key=lambda m: m["days_left"])
    if proches:
        lignes += ["", "### Se décide bientôt", ""]
        for m in proches:
            lignes.append(f"- **{_quand(m['days_left'])}** — « {m['title']} » : "
                          f"{_nombre(m['yes_prob'])} % au OUI ({m['source']}).")
    return "\n".join(lignes)


def _horizon_marquant(m: dict) -> tuple[str, float] | None:
    """L'horizon dont le mouvement dépasse le plus son seuil, et ce rapport."""
    meilleur = None
    for champ, seuil in SEUILS_MOUVEMENT.items():
        if m.get(champ) is not None and abs(m[champ]) >= seuil:
            rapport = abs(m[champ]) / seuil
            if meilleur is None or rapport > meilleur[1]:
                meilleur = (champ, rapport)
    return meilleur


def _quand(jours: int) -> str:
    return {0: "Aujourd'hui", 1: "Demain"}.get(jours, f"Dans {jours} jours")


def par_theme(briefing: dict) -> str:
    """Chaque thème, ses marchés par score décroissant. Une même question posée sur
    deux sources tient en une ligne, avec le prix de chacune."""
    lignes = ["## Par thème"]
    groupes: dict[str, dict[str, list[dict]]] = {}
    for m in sorted(briefing["markets"], key=lambda m: m.get("score") or 0, reverse=True):
        theme = groupes.setdefault(m.get("category") or "Autre", {})
        theme.setdefault(" ".join(m["title"].lower().split()), []).append(m)
    ordre = [c for c in CATEGORIES if c in groupes] + [c for c in groupes if c not in CATEGORIES]
    for nom in ordre:
        lignes += ["", f"### {nom}", ""]
        for memes in groupes[nom].values():
            lignes.append("- " + _ligne(memes))
    return "\n".join(lignes)


def _ligne(memes: list[dict]) -> str:
    m = memes[0]
    def variations(x):
        v = [f"{_signe(x[c])} pt en {LIBELLES_HORIZON[c]}" for c in SEUILS_MOUVEMENT
             if x.get(c) is not None]
        return f" ({', '.join(v)})" if v else ""

    prix = " ; ".join(f"{_nombre(x['yes_prob'])} % sur {x['source']}{variations(x)}"
                      for x in memes)
    texte = f"« {m['title']} » — le marché donne au OUI {prix}"
    if m.get("end_date"):
        texte += f". Échéance {m['end_date']}"
    texte += "."
    if m.get("resolution_summary"):
        texte += f" *{m['resolution_summary']}*"
    return texte


def _montant(x: float) -> str:
    return f"{round(x):,}".replace(",", " ")


def _nombre(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _signe(x: float) -> str:
    return ("+" if x > 0 else "−" if x < 0 else "±") + _nombre(abs(x))


def composer(briefing: dict, maintenant: datetime) -> tuple[str, list[str]]:
    """Le point en Markdown, et les remarques à journaliser."""
    remarques = []
    lignes = [f"# Oracle — point du {a_paris(maintenant):%d/%m/%Y à %Hh%M}", ""]
    meta = briefing["meta"]
    genere = _date(meta.get("generated_at"))
    if genere and (maintenant - genere).total_seconds() > BRIEFING_VIEUX_H * 3600:
        remarques.append(f"briefing vieux de plus de {BRIEFING_VIEUX_H} h ({genere:%d/%m %H:%M})")
        lignes += [f"> ⚠ Briefing ancien : relevé du {a_paris(genere):%d/%m/%Y à %H:%M}.", ""]
    lignes += [essentiel(briefing), "", par_theme(briefing), "", "---", "",
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

    p = argparse.ArgumentParser(description="Écrit le point matinal à partir du briefing.")
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
