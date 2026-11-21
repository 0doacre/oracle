"""L'actualité reliée aux dossiers : flux RSS de médias français, et GDELT pour
l'international. Seuls le titre, la source, l'heure et le lien sont gardés, jamais
le texte des articles.

Un titre n'est rattaché à un dossier que si ses mots correspondent (mots_fr ou mots
du dossier). Vu au premier essai : GDELT renvoyait, pour « iran ceasefire », un
article sur la femme de Stephen Miller (le mot était dans le corps, pas dans le titre).
"""

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from oracle.dossiers import Suivi
from oracle.http import ErreurReseau, get_json, get_octets

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
PAUSE_GDELT_S = 6            # GDELT : une requête toutes les 5 s, sinon 429 (vu au premier essai)
FENETRE_H = 24
PAR_DOSSIER = 3
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Depeche:
    title: str
    source: str
    url: str
    published: str           # ISO 8601 en UTC


def _xml(octets: bytes) -> ET.Element:
    try:
        return ET.fromstring(octets)
    except ET.ParseError as e:            # n'hérite pas de ValueError : get_octets ne la reprendrait pas
        raise ValueError(f"XML illisible : {e}") from e


def _date(texte: str | None) -> datetime | None:
    if not texte:
        return None
    texte = texte.strip()
    try:
        d = parsedate_to_datetime(texte)                      # RSS : RFC 822
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(texte.replace("Z", "+00:00"))   # Atom : ISO 8601
        except ValueError:
            return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _propre(titre: str) -> str:
    # Certains flux échappent deux fois (« &amp;#039; ») ; les crochets gêneraient les liens.
    titre = " ".join(html.unescape(html.unescape(titre or "")).split())
    return titre.replace("[", "(").replace("]", ")")


def lire_flux(racine: ET.Element, source: str) -> list[tuple[str, str, datetime | None]]:
    """(titre, lien, date) de chaque article d'un flux RSS 2.0 ou Atom."""
    articles = []
    for item in racine.iter("item"):
        articles.append((_propre(item.findtext("title")), (item.findtext("link") or "").strip(),
                         _date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date"))))
    for entree in racine.iter(f"{ATOM}entry"):
        lien = entree.find(f"{ATOM}link")
        articles.append((_propre(entree.findtext(f"{ATOM}title")),
                         lien.get("href", "") if lien is not None else "",
                         _date(entree.findtext(f"{ATOM}published") or entree.findtext(f"{ATOM}updated"))))
    return [a for a in articles if a[0] and a[1].startswith("http")]


def lire_gdelt(reponse: dict) -> list[tuple[str, str, datetime | None, str]]:
    """(titre, lien, date, domaine) des articles GDELT en français ou en anglais."""
    articles = []
    for a in reponse.get("articles", []):
        if a.get("language") not in ("French", "English"):
            continue
        try:
            quand = datetime.strptime(a.get("seendate", ""), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            quand = None
        articles.append((_propre(a.get("title")), a.get("url", ""), quand, a.get("domain", "GDELT")))
    return [a for a in articles if a[0] and a[1].startswith("http")]


def _lien(url: str) -> str:
    # Les liens franceinfo finissent par « #xtor=RSS-3-[lestitres] » : les crochets
    # casseraient le lien Markdown (vu au premier essai réel).
    return url.strip().replace("[", "%5B").replace("]", "%5D").replace(" ", "%20")


def _cle(titre: str) -> str:
    return re.sub(r"\W+", " ", titre.lower()).strip()


def collecter(suivi: Suivi, maintenant: datetime, dossiers_gdelt: list[str] = (),
              get=get_octets, get_gdelt=get_json, pause=time.sleep) -> tuple[dict, dict]:
    """{dossier: [Depeche…]} des dernières 24 h (3 au plus, les plus récentes),
    et {source: erreur} pour les sources en panne."""
    depuis = maintenant - timedelta(hours=FENETRE_H)
    candidats: list[tuple[str, Depeche]] = []      # (dossier, dépêche)
    erreurs: dict[str, str] = {}

    def garder(dossier, titre, lien, quand, source):
        # Le bruit des marchés vaut aussi pour la presse (vu : l'hypothèse de Riemann
        # prenait une place du dossier « Bulle IA »).
        if suivi.est_du_bruit(titre):
            return
        if dossier and quand and depuis <= quand <= maintenant + timedelta(hours=1):
            candidats.append((dossier, Depeche(titre, source, _lien(lien),
                                               quand.isoformat(timespec="minutes"))))

    for flux in suivi.flux:
        try:
            racine = get(flux.url, accepte="application/rss+xml, application/xml, text/xml",
                         decoder=_xml)
        except ErreurReseau as e:
            erreurs[flux.nom] = str(e)[:200]
            continue
        for titre, lien, quand in lire_flux(racine, flux.nom):
            garder(suivi.attribuer_actualite(titre), titre, lien, quand, flux.nom)

    par_nom = {d.nom: d for d in suivi.dossiers}
    requetes = [par_nom[n] for n in dossiers_gdelt if n in par_nom and par_nom[n].gdelt]
    for i, dossier in enumerate(requetes):
        if i:
            pause(PAUSE_GDELT_S)
        try:
            reponse = get_gdelt(GDELT, {"query": dossier.gdelt, "mode": "artlist", "format": "json",
                                        "maxrecords": 15, "timespan": f"{FENETRE_H}h",
                                        "sort": "datedesc"})
        except ErreurReseau as e:
            erreurs[f"GDELT {dossier.nom}"] = str(e)[:200]
            continue
        for titre, lien, quand, domaine in lire_gdelt(reponse):
            # Le titre doit parler du dossier : la recherche GDELT porte aussi sur le corps.
            if dossier.motif_actu and dossier.motif_actu.search(titre):
                garder(dossier.nom, titre, lien, quand, domaine)

    par_dossier: dict[str, list[Depeche]] = {}
    vus: set[str] = set()
    for dossier, d in sorted(candidats, key=lambda c: c[1].published, reverse=True):
        if _cle(d.title) in vus:
            continue
        vus.add(_cle(d.title))
        lot = par_dossier.setdefault(dossier, [])
        if len(lot) < PAR_DOSSIER:
            lot.append(d)
    return par_dossier, erreurs


def vers_json(par_dossier: dict, erreurs: dict, maintenant: datetime,
              suivi: Suivi | None = None) -> dict:
    return {"generated_at": maintenant.isoformat(timespec="seconds"),
            "dossiers": {nom: [asdict(d) for d in lot] for nom, lot in par_dossier.items()},
            # Dans l'ordre de dossiers.toml : ils ont leur rubrique « Aussi suivi ».
            "news_only": [d.nom for d in suivi.dossiers if d.actualite_seule] if suivi else [],
            "errors": erreurs}


def ecrire(donnees: dict, chemin) -> None:
    from pathlib import Path
    Path(chemin).write_text(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
