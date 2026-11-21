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

from oracle import actualite, meteo, rendu
from oracle.dossiers import charger as charger_suivi
from oracle.point_matinal import composer, dossiers_classes
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


class EchecEnvoi(Exception):
    """Le mail n'est pas parti ; le message dit par quel port et à quelle étape."""


def envoyer(message: EmailMessage, utilisateur: str, mot_de_passe: str,
            hote: str = "smtp.gmail.com", smtp_ssl=smtplib.SMTP_SSL,
            smtp_clair=smtplib.SMTP) -> str:
    """Envoie par SSL (465), puis par STARTTLS (587) si le premier coupe.
    Renvoie le mode qui a marché. Un refus d'authentification n'est pas retenté :
    l'autre port le refuserait aussi.

    Vu au premier essai réel depuis GitHub : « SMTPServerDisconnected: Connection
    unexpectedly closed » sur le 465, sans dire à quelle étape."""
    contexte = ssl.create_default_context()
    # Google affiche le mot de passe d'application en quatre groupes : les espaces
    # n'en font pas partie.
    utilisateur, mot_de_passe = utilisateur.strip(), mot_de_passe.replace(" ", "").strip()
    essais = [
        ("SSL 465", lambda: smtp_ssl(hote, 465, context=contexte, timeout=60), False),
        ("STARTTLS 587", lambda: smtp_clair(hote, 587, timeout=60), True),
    ]
    erreurs = []
    for nom, ouvrir, starttls in essais:
        etape, serveur = "connexion", None
        try:
            with ouvrir() as serveur:
                if starttls:
                    etape = "chiffrement"
                    serveur.starttls(context=contexte)
                etape = "authentification"
                serveur.login(utilisateur, mot_de_passe)
                etape = "envoi"
                serveur.send_message(message)
            return nom
        except smtplib.SMTPAuthenticationError as e:
            raise EchecEnvoi(f"{nom} : authentification refusée ({e.smtp_code}). Vérifier "
                             "l'adresse et le mot de passe d'application Gmail.") from e
        except (smtplib.SMTPException, OSError) as e:
            detail = f"{nom}, étape « {etape} » : {type(e).__name__}: {e}"
            if etape == "authentification":
                detail += f" [serveur : AUTH {getattr(serveur, 'esmtp_features', {}).get('auth', '?')}]"
            erreurs.append(detail)
    raise EchecEnvoi(" ; ".join(erreurs) + " — " + decrire_identifiants(utilisateur, mot_de_passe))


def decrire_identifiants(utilisateur: str, mot_de_passe: str) -> str:
    """La forme des identifiants, sans aucune de leurs valeurs : de quoi repérer une
    faute de saisie dans un secret qu'on ne peut pas relire."""
    def forme(texte: str) -> str:
        etranges = sum(1 for c in texte if not c.isascii() or not c.isprintable())
        return f"{len(texte)} caractères" + (f", dont {etranges} non ASCII ou invisibles"
                                             if etranges else "")
    adresse = "avec « @ »" if "@" in utilisateur else "SANS « @ »"
    lettres = "16 lettres, attendu" if len(mot_de_passe) == 16 and mot_de_passe.isalpha() \
        else "pas 16 lettres : un mot de passe d'application en a 16"
    return (f"utilisateur : {forme(utilisateur)}, {adresse} ; "
            f"mot de passe : {forme(mot_de_passe)} ({lettres})")


def url_de_la_page() -> str:
    """https://<compte>.github.io/<dépôt>/ sur GitHub, sinon ORACLE_URL_PAGE ou rien."""
    if os.environ.get("ORACLE_URL_PAGE"):
        return os.environ["ORACLE_URL_PAGE"]
    depot = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in depot:
        compte, nom = depot.split("/", 1)
        return f"https://{compte.lower()}.github.io/{nom}/"
    return ""


def _actualite(briefing: dict, maintenant: datetime, collecter, journal) -> dict:
    """Les titres de presse par dossier. GDELT n'est interrogé que pour les 5 dossiers
    du jour : il limite le débit (une requête toutes les 5 s). Une source en panne
    n'empêche rien."""
    suivi = charger_suivi()
    du_jour = dossiers_classes(briefing)[:5]
    par_dossier, erreurs = collecter(suivi, maintenant, du_jour)
    for source, erreur in erreurs.items():
        journal(f"actualité : {source} en panne ({erreur[:120]})")
    total = sum(len(lot) for lot in par_dossier.values())
    journal(f"actualité : {total} titres rattachés à {len(par_dossier)} dossiers")
    return actualite.vers_json(par_dossier, erreurs, maintenant, suivi)


def main(argv: list[str] | None = None, smtp_ssl=smtplib.SMTP_SSL, smtp_clair=smtplib.SMTP,
         collecter_actualite=None, meteo_du_jour=None) -> int:
    from oracle.collecteur import Journal

    p = argparse.ArgumentParser(description="Écrit le point dans le site et l'envoie par mail au bon créneau.")
    p.add_argument("--briefing", default="briefing_oracle.json")
    p.add_argument("--site", default="site")
    p.add_argument("--etat", default="etat/envois.json")
    p.add_argument("--forcer", action="store_true", help="envoyer le mail quelle que soit l'heure")
    p.add_argument("--journal", default=None)
    p.add_argument("--sans-actualite", action="store_true", help="ne pas lire les flux de presse")
    args = p.parse_args(argv)
    journal = Journal(args.journal)

    try:
        briefing = json.loads(Path(args.briefing).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        journal(f"envoi : briefing illisible ({e})")
        return 2

    maintenant = datetime.now(timezone.utc)
    local = a_paris(maintenant)
    site = Path(args.site)
    site.mkdir(parents=True, exist_ok=True)
    actualites = None
    if not args.sans_actualite:
        actualites = _actualite(briefing, maintenant, collecter_actualite or actualite.collecter,
                                journal)
        actualite.ecrire(actualites, site / "actualites.json")

    # Météo : seulement si le secret ORACLE_METEO donne le lieu (jamais dans le dépôt).
    texte_meteo, erreur_meteo = (meteo_du_jour or meteo.du_jour)(maintenant)
    if erreur_meteo:
        journal(f"météo : indisponible ({erreur_meteo})")

    # Le mail : les 5 choses à savoir. La page : les 5 choses et le détail par dossier.
    complet, remarques = composer(briefing, maintenant, actualites=actualites, meteo=texte_meteo)
    court, _ = composer(briefing, maintenant, court=True, actualites=actualites, meteo=texte_meteo)
    for r in remarques:
        journal(f"envoi : {r}")
    url = url_de_la_page()
    titre = f"Oracle — {local:%d/%m} à {local:%H}h{local:%M}"
    pied_page = f'<hr><p><a href="{url}">Ouvrir le tableau de bord</a></p>' if url else ""
    pied_mail = (f'<hr><p><a href="{url}point.html">Le détail par dossier</a> · '
                 f'<a href="{url}">le tableau de bord</a></p>' if url else "")
    mail_html = rendu.page(court, titre, pied_mail)

    (site / "point.md").write_text(complet, encoding="utf-8")
    (site / "point.html").write_text(rendu.page(complet, titre, pied_page), encoding="utf-8")

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
    # Vu en vrai : un identifiant sans « @ » fait couper Gmail sans explication.
    sans_arobase = [v for v in ("ORACLE_SMTP_UTILISATEUR", "ORACLE_DESTINATAIRE")
                    if "@" not in os.environ[v]]
    if sans_arobase:
        journal("envoi : mail non envoyé, adresse incomplète (il manque « @ ») dans : "
                + ", ".join(sans_arobase))
        return 1
    message = construire_mail(titre, court + (f"\n\nLe détail : {url}point.html\n" if url else ""),
                              mail_html, os.environ["ORACLE_SMTP_UTILISATEUR"].strip(),
                              os.environ["ORACLE_DESTINATAIRE"].strip())
    try:
        mode = envoyer(message, os.environ["ORACLE_SMTP_UTILISATEUR"],
                       os.environ["ORACLE_SMTP_MOT_DE_PASSE"],
                       smtp_ssl=smtp_ssl, smtp_clair=smtp_clair)
    except EchecEnvoi as e:
        # Les erreurs SMTP ne contiennent pas le mot de passe.
        journal(f"envoi : échec du mail ({e})")
        return 1
    noter_envoi(etat, deja, cle)
    journal(f"envoi : mail du créneau {cle} envoyé ({mode})")
    return 0
