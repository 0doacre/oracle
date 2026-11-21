"""Le point par mail, à 7 h, 12 h et 19 h (heure de Paris), et la page web.

Appelé après chaque relevé (toutes les heures sur GitHub). Il écrit toujours le
point dans le dossier du site, et n'envoie le mail qu'au premier relevé d'un
créneau. GitHub démarre parfois une tâche planifiée avec du retard : un créneau
manqué est rattrapé pendant RATTRAPAGE_H heures. Les envois faits sont notés dans
un petit fichier d'état (conservé entre deux exécutions, comme la base).

Identifiants SMTP : variables d'environnement seulement (secrets GitHub), jamais
dans le dépôt ni dans le journal.
"""

import argparse
import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from oracle import rendu
from oracle.point_matinal import composer
from oracle.temps import a_paris

CRENEAUX_H = (7, 12, 19)
RATTRAPAGE_H = 2
VARIABLES = ("ORACLE_SMTP_UTILISATEUR", "ORACLE_SMTP_MOT_DE_PASSE", "ORACLE_DESTINATAIRE")


def creneau_a_envoyer(moment: datetime, deja: set[str]) -> str | None:
    """La clé « AAAA-MM-JJ HHh » du créneau à envoyer maintenant, ou None."""
    local = a_paris(moment)
    for h in CRENEAUX_H:
        cle = f"{local:%Y-%m-%d} {h:02d}h"
        if h <= local.hour < h + RATTRAPAGE_H and cle not in deja:
            return cle
    return None


def lire_etat(chemin: Path) -> set[str]:
    try:
        return set(json.loads(chemin.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def noter_envoi(chemin: Path, deja: set[str], cle: str) -> None:
    # On ne garde que les 30 derniers créneaux : le fichier reste minuscule.
    garde = sorted(deja | {cle})[-30:]
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(garde), encoding="utf-8")


def construire_mail(sujet: str, texte: str, page_html: str, expediteur: str,
                    destinataire: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = expediteur
    message["To"] = destinataire
    message.set_content(texte)                       # version texte (Markdown lisible)
    message.add_alternative(page_html, subtype="html")
    return message


def envoyer(message: EmailMessage, utilisateur: str, mot_de_passe: str,
            hote: str = "smtp.gmail.com", port: int = 465, smtp=smtplib.SMTP_SSL) -> None:
    with smtp(hote, port, context=ssl.create_default_context(), timeout=60) as serveur:
        serveur.login(utilisateur, mot_de_passe)
        serveur.send_message(message)


def url_de_la_page() -> str:
    """https://<compte>.github.io/<dépôt>/ sur GitHub, sinon ORACLE_URL_PAGE ou rien."""
    if os.environ.get("ORACLE_URL_PAGE"):
        return os.environ["ORACLE_URL_PAGE"]
    depot = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in depot:
        compte, nom = depot.split("/", 1)
        return f"https://{compte.lower()}.github.io/{nom}/"
    return ""


def main(argv: list[str] | None = None, smtp=smtplib.SMTP_SSL) -> int:
    from oracle.collecteur import Journal

    p = argparse.ArgumentParser(description="Écrit le point dans le site et l'envoie par mail au bon créneau.")
    p.add_argument("--briefing", default="briefing_oracle.json")
    p.add_argument("--site", default="site")
    p.add_argument("--etat", default="etat/envois.json")
    p.add_argument("--forcer", action="store_true", help="envoyer le mail quelle que soit l'heure")
    p.add_argument("--journal", default=None)
    args = p.parse_args(argv)
    journal = Journal(args.journal)

    try:
        briefing = json.loads(Path(args.briefing).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        journal(f"envoi : briefing illisible ({e})")
        return 2

    maintenant = datetime.now(timezone.utc)
    local = a_paris(maintenant)
    texte, remarques = composer(briefing, maintenant)
    for r in remarques:
        journal(f"envoi : {r}")
    url = url_de_la_page()
    pied = (f'<hr><p><a href="{url}">Ouvrir le tableau de bord</a></p>' if url else "")
    titre = f"Oracle — {local:%d/%m} à {local:%H}h{local:%M}"
    page_html = rendu.page(texte, titre, pied)

    site = Path(args.site)
    site.mkdir(parents=True, exist_ok=True)
    (site / "point.md").write_text(texte, encoding="utf-8")
    (site / "point.html").write_text(page_html, encoding="utf-8")

    etat = Path(args.etat)
    deja = lire_etat(etat)
    cle = f"{local:%Y-%m-%d %H}h-forcé" if args.forcer else creneau_a_envoyer(maintenant, deja)
    if not cle:
        journal(f"envoi : pas de créneau à {local:%H:%M} (Paris), point écrit sans mail")
        return 0

    manquantes = [v for v in VARIABLES if not os.environ.get(v)]
    if manquantes:
        journal("envoi : mail non envoyé, secrets absents : " + ", ".join(manquantes))
        return 1
    message = construire_mail(titre, texte + (f"\n\nTableau de bord : {url}\n" if url else ""),
                              page_html, os.environ["ORACLE_SMTP_UTILISATEUR"],
                              os.environ["ORACLE_DESTINATAIRE"])
    try:
        envoyer(message, os.environ["ORACLE_SMTP_UTILISATEUR"],
                os.environ["ORACLE_SMTP_MOT_DE_PASSE"], smtp=smtp)
    except (smtplib.SMTPException, OSError) as e:
        # Le message d'erreur SMTP ne contient pas le mot de passe.
        journal(f"envoi : échec du mail ({type(e).__name__}: {e})")
        return 1
    noter_envoi(etat, deja, cle)
    journal(f"envoi : mail du créneau {cle} envoyé")
    return 0
