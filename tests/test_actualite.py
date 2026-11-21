from datetime import datetime, timezone
from pathlib import Path

import pytest

from oracle import actualite, dossiers, point_matinal as pm
from oracle.http import ErreurReseau

FIXTURES = Path(__file__).parent / "fixtures"
SUIVI = dossiers.charger()


def racine(nom):
    return actualite._xml((FIXTURES / nom).read_bytes())


def test_les_vrais_flux_rss_se_lisent():
    for nom in ("rss_lemonde_international.xml", "rss_cafepedagogique.xml"):
        articles = actualite.lire_flux(racine(nom), nom)
        assert len(articles) >= 5
        for titre, lien, quand in articles:
            assert titre and lien.startswith("http") and quand and quand.tzinfo


def test_un_flux_atom_se_lit():
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Rentr\xc3\xa9e : les
      enseignants &amp;amp; la r\xc3\xa9forme</title><link href="https://ex.org/1"/>
      <updated>2026-11-21T08:00:00Z</updated></entry></feed>"""
    [(titre, lien, quand)] = actualite.lire_flux(actualite._xml(xml), "x")
    assert titre == "Rentrée : les enseignants & la réforme"      # double échappement défait
    assert lien == "https://ex.org/1" and quand.hour == 8


def test_un_xml_illisible_est_une_valueerror_pour_les_reprises():
    with pytest.raises(ValueError):
        actualite._xml(b"<rss><item>")


def flux_faux(contenus: dict[str, bytes]):
    def get(url, accepte=None, decoder=None):
        if url not in contenus:
            raise ErreurReseau("403")
        return decoder(contenus[url])
    return get


def rss(*items):
    corps = "".join(f"<item><title>{t}</title><link>https://ex.org/{i}</link>"
                    f"<pubDate>{d}</pubDate></item>" for i, (t, d) in enumerate(items))
    return f"<rss><channel>{corps}</channel></rss>".encode()


MAINTENANT = datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)


def suivi_avec(urls):
    s = dossiers.charger()
    s.flux = [dossiers.Flux(f"Flux {i}", u) for i, u in enumerate(urls)]
    return s


def test_rattachement_fenetre_bruit_et_limite():
    suivi = suivi_avec(["https://a"])
    get = flux_faux({"https://a": rss(
        ("Tankers hit in Strait of Hormuz as Iran tightens grip", "Sat, 21 Nov 2026 15:01:18 +0000"),
        ("Iran : deuxième titre", "Sat, 21 Nov 2026 14:00:00 +0000"),
        ("Iran : troisième titre", "Sat, 21 Nov 2026 13:00:00 +0000"),
        ("Iran : quatrième titre", "Sat, 21 Nov 2026 12:00:00 +0000"),   # au-delà de 3
        ("Présidentielle 2027 : titre d'avant-hier", "Thu, 19 Nov 2026 12:00:00 +0000"),  # hors 24 h
        ("Un mathématicien résout l'hypothèse de Riemann grâce à l'IA", "Sat, 21 Nov 2026 15:00:00 +0000"),
        ("Recette de la tarte aux pommes", "Sat, 21 Nov 2026 15:00:00 +0000"),
    )})
    par, erreurs = actualite.collecter(suivi, MAINTENANT, get=get)
    assert erreurs == {}
    assert [d.title for d in par["Iran"]] == [
        "Tankers hit in Strait of Hormuz as Iran tightens grip", "Iran : deuxième titre",
        "Iran : troisième titre"]
    assert "Bulle IA et labos" not in par                     # Riemann : bruit déclaré
    assert "Présidentielle 2027" not in par                   # plus de 24 h
    assert sum(len(v) for v in par.values()) == 3             # la tarte n'a pas de dossier


def test_un_meme_titre_sur_deux_flux_n_apparait_qu_une_fois():
    suivi = suivi_avec(["https://a", "https://b"])
    titre = ("Présidentielle 2027 : Zemmour lance sa campagne", "Sat, 21 Nov 2026 10:00:00 +0100")
    par, _ = actualite.collecter(suivi, MAINTENANT,
                                 get=flux_faux({"https://a": rss(titre), "https://b": rss(titre)}))
    assert len(par["Présidentielle 2027"]) == 1


def test_un_flux_en_panne_n_empeche_pas_les_autres():
    suivi = suivi_avec(["https://panne", "https://a"])
    par, erreurs = actualite.collecter(suivi, MAINTENANT, get=flux_faux(
        {"https://a": rss(("Iran : un titre", "Sat, 21 Nov 2026 15:00:00 +0000"))}))
    assert "Flux 0" in erreurs and len(par["Iran"]) == 1


def gdelt(*titres):
    return {"articles": [{"title": t, "url": f"https://ex.org/{i}", "language": langue,
                          "seendate": "20261121T133000Z", "domain": "ex.org"}
                         for i, (t, langue) in enumerate(titres)]}


def test_gdelt_seulement_pour_les_dossiers_demandes_avec_pause_et_titre_pertinent():
    suivi = suivi_avec([])
    appels, pauses = [], []

    def get_gdelt(url, params):
        appels.append(params["query"])
        return gdelt(("Stephen Miller wife sparks frenzy", "English"),   # hors sujet (vu en vrai)
                     ("US and Qatar intensify mediation to end Iran conflict", "English"),
                     ("Iran-Krise: neue Sanktionen", "German"))   # pertinent, mais en allemand
    par, _ = actualite.collecter(suivi, MAINTENANT, ["Iran", "Trump et Washington", "Ukraine – Russie"],
                                 get_gdelt=get_gdelt, pause=pauses.append)
    # « Trump et Washington » n'a pas de requête GDELT ; deux requêtes, une pause entre elles.
    assert len(appels) == 2 and pauses == [actualite.PAUSE_GDELT_S]
    assert [d.title for d in par["Iran"]] == ["US and Qatar intensify mediation to end Iran conflict"]


def test_gdelt_en_panne_est_note_sans_rien_casser():
    def get_gdelt(url, params):
        raise ErreurReseau("429")
    par, erreurs = actualite.collecter(suivi_avec([]), MAINTENANT, ["Iran"], get_gdelt=get_gdelt,
                                       pause=lambda s: None)
    assert par == {} and "GDELT Iran" in erreurs


# ---------- Dans le point ----------

ACTU = {"dossiers": {"Iran": [{"title": "Tankers hit in Strait of Hormuz", "source": "Al Jazeera",
                                "url": "https://ex.org/1", "published": "2026-11-21T15:01+00:00"}],
                     "Éducation nationale": [{"title": "Mobilisation lycéenne", "source": "Le Monde",
                                              "url": "https://ex.org/2",
                                              "published": "2026-11-21T05:00+00:00"}]},
        "news_only": ["Éducation nationale", "Administration et fonction publique"]}


def briefing():
    return {"meta": {"generated_at": "2026-11-21T15:50:00+00:00", "total_scanned": 1, "errors": {}},
            "markets": [{"title": "US x Iran Effective Ceasefire?", "dossier": "Iran", "source": "polymarket",
                         "yes_prob": 35.5, "score": 50, "confirmed_moves": [], "end_date": "",
                         "trade_alert": None}]}


def test_les_titres_suivent_leur_dossier_dans_le_mail():
    texte, _ = pm.composer(briefing(), MAINTENANT, court=True, actualites=ACTU)
    ligne_iran = texte.index("1. **Iran**")
    assert texte.index("- [Tankers hit in Strait of Hormuz](https://ex.org/1) — Al Jazeera, 16h01") > ligne_iran
    assert "## Aussi suivi" in texte and "Mobilisation lycéenne" in texte
    assert "**Administration et fonction publique**\n\nRien de neuf dans les flux suivis." in texte


def test_sans_actualite_le_point_reste_complet():
    texte, _ = pm.composer(briefing(), MAINTENANT, court=True)
    assert "1. **Iran**" in texte and "Aussi suivi" not in texte


def test_le_lien_devient_cliquable_et_sur():
    from oracle import rendu
    html = rendu.markdown_vers_html('- [Titre "x"](https://ex.org/a?b=1&c=2) et [piège](javascript:alert(1))')
    assert '<a href="https://ex.org/a?b=1&amp;c=2">Titre &quot;x&quot;</a>' in html
    assert "javascript" in html and 'href="javascript' not in html


def test_un_lien_avec_crochets_reste_un_lien_markdown_valide():
    # Lien réel de franceinfo.
    suivi = suivi_avec(["https://a"])
    xml = (b"<rss><channel><item><title>Iran : un titre</title>"
           b"<link>https://www.franceinfo.fr/a_8293667.html#xtor=RSS-3-[lestitres]</link>"
           b"<pubDate>Sat, 21 Nov 2026 15:00:00 +0000</pubDate></item></channel></rss>")
    par, _ = actualite.collecter(suivi, MAINTENANT, get=flux_faux({"https://a": xml}))
    lien = par["Iran"][0].url
    assert lien == "https://www.franceinfo.fr/a_8293667.html#xtor=RSS-3-%5Blestitres%5D"
    from oracle import rendu
    assert f'href="{lien}"' in rendu.markdown_vers_html(f"- [Iran : un titre]({lien})")
