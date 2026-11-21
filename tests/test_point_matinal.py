import json
from datetime import datetime, timezone

from oracle import point_matinal as pm

MAINTENANT = datetime(2026, 11, 22, 6, 10, tzinfo=timezone.utc)


def briefing(genere="2026-11-22T06:00:00+00:00"):
    return {
        "meta": {"generated_at": genere, "total_scanned": 1000, "errors": {}},
        "markets": [
            {"title": "Will Marine Le Pen win the 2027 French presidential election?",
             "category": "Droites radicales & mouvements identitaires", "source": "polymarket",
             "yes_prob": 46.4, "delta_24h": -2.5, "end_date": "2027-04-19", "score": 50,
             "resolution_summary": "This market will resolve to \"Yes\" if Marine Le Pen wins.",
             "trade_alert": None},
            {"title": "Will Marine Le Pen win the 2027  French presidential election?",
             "category": "Droites radicales & mouvements identitaires", "source": "kalshi",
             "yes_prob": 50.5, "delta_24h": None, "end_date": "2028-05-30", "score": 45,
             "resolution_summary": "", "trade_alert": None},
            {"title": "US-Iran Final Nuclear Deal by December 31, 2026?",
             "category": "Géopolitique & Risques", "source": "polymarket",
             "yes_prob": 5.0, "delta_24h": None, "end_date": "2026-12-31", "score": 60,
             "resolution_summary": "",
             "trade_alert": {"amount_usd": 13647.43, "side": "YES", "share_24h": 0.516,
                             "wallet_profile": "Wallet concentré"}},
        ],
    }


def test_l_essentiel_donne_le_bon_cote_du_pari():
    texte = pm.essentiel(briefing())
    assert ("**Gros ordre** : 13 647 $ misés sur le OUI — « US-Iran Final Nuclear Deal by "
            "December 31, 2026? » (polymarket). Le marché donne 5 % au OUI ; cet ordre pèse "
            "51,6 % du volume du jour, wallet concentré.") in texte
    b = briefing()
    b["markets"][2]["trade_alert"]["side"] = "NO"
    assert "misés sur le NON" in pm.essentiel(b)


def test_l_essentiel_liste_les_fortes_variations_et_ignore_les_petites():
    b = briefing()
    b["markets"][0]["delta_24h"] = -6.5
    assert "**−6,5 pt en 24 h** — « Will Marine Le Pen" in pm.essentiel(b)
    b["markets"][0]["delta_24h"] = 3.9
    texte = pm.essentiel(b)
    assert "3,9" not in texte
    assert "Rien n'a bougé de 2 points en 1 h, 3 en 6 h ou 4 en 24 h." in texte


def test_l_essentiel_dit_quand_l_historique_manque():
    b = briefing()
    b["markets"][0]["delta_24h"] = None
    assert "(pas encore d'historique)." in pm.essentiel(b)


def test_un_mouvement_dans_l_heure_passe_devant_et_cite_les_autres_horizons():
    b = briefing()
    b["markets"][0].update(delta_1h=3.0, delta_6h=2.0, delta_24h=-1.0)   # 1 h : 1,5 × son seuil
    b["markets"][2].update(delta_24h=5.0)                                # 24 h : 1,25 × son seuil
    texte = pm.essentiel(b)
    ligne_le_pen = "- **+3 pt en 1 h** (+2 en 6 h, −1 en 24 h) — « Will Marine Le Pen"
    assert ligne_le_pen in texte
    assert texte.index(ligne_le_pen) < texte.index("- **+5 pt en 24 h**")


def test_les_pics_de_volume_sont_listes():
    b = briefing()
    b["markets"][2]["volume_ratio"] = 4.5
    b["markets"][0]["volume_ratio"] = 2.9
    texte = pm.essentiel(b)
    assert "- **Volume × 4,5** par rapport aux jours précédents — « US-Iran" in texte
    assert "× 2,9" not in texte


def test_les_echeances_proches_sont_listees_par_date():
    b = briefing()
    b["markets"][0]["days_left"] = 3
    b["markets"][2]["days_left"] = 0
    b["markets"][1]["days_left"] = 40
    texte = pm.essentiel(b)
    assert texte.index("**Aujourd'hui** — « US-Iran") < texte.index("**Dans 3 jours** — « Will Marine")
    assert "Dans 40 jours" not in texte


def test_une_echeance_passee_n_est_pas_listee():
    b = briefing()
    b["markets"][0]["days_left"] = -1
    assert "Se décide bientôt" not in pm.essentiel(b)


def test_l_essentiel_signale_les_sources_en_panne_et_l_absence_d_alerte():
    b = briefing()
    b["meta"]["errors"] = {"polymarket": "503"}
    b["markets"][2]["trade_alert"] = None
    texte = pm.essentiel(b)
    assert "Sources en panne pendant le relevé : polymarket." in texte
    assert "Aucun gros ordre atypique." in texte


def test_par_theme_suit_l_ordre_des_categories_et_donne_chaque_prix():
    texte = pm.par_theme(briefing())
    # Ordre de oracle.themes.CATEGORIES : Droites radicales avant Géopolitique.
    assert texte.index("### Droites radicales") < texte.index("### Géopolitique")
    assert ("- « US-Iran Final Nuclear Deal by December 31, 2026? » — le marché donne au OUI "
            "5 % sur polymarket. Échéance 2026-12-31.") in texte


def test_une_meme_question_sur_deux_sources_tient_en_une_ligne():
    texte = pm.par_theme(briefing())
    assert texte.count("« Will Marine Le Pen") == 1
    assert ("le marché donne au OUI 46,4 % sur polymarket (−2,5 pt en 24 h) ; "
            "50,5 % sur kalshi") in texte


def test_par_theme_joint_le_resume_de_la_regle():
    assert "*This market will resolve to \"Yes\" if Marine Le Pen wins.*" in pm.par_theme(briefing())


def test_le_point_contient_les_deux_parties_dans_l_ordre():
    texte, remarques = pm.composer(briefing(), MAINTENANT)
    assert remarques == []
    assert texte.index("## L'essentiel") < texte.index("## Par thème")
    assert "ni un sondage, ni une prévision" in texte
    assert "⚠" not in texte


def test_un_briefing_ancien_est_signale():
    texte, remarques = pm.composer(briefing("2026-11-21T20:00:00+00:00"), MAINTENANT)
    assert "Briefing ancien" in texte and remarques
    texte, _ = pm.composer(briefing("2026-11-22T05:00:00+00:00"), MAINTENANT)
    assert "Briefing ancien" not in texte


def test_main_ecrit_le_point_du_jour(tmp_path):
    source = tmp_path / "b.json"
    source.write_text(json.dumps(briefing()), encoding="utf-8")
    assert pm.main(["--briefing", str(source), "--dossier", str(tmp_path / "points"),
                    "--journal", str(tmp_path / "j.log")]) == 0
    fichiers = list((tmp_path / "points").glob("*.md"))
    assert len(fichiers) == 1 and "## Par thème" in fichiers[0].read_text(encoding="utf-8")
    assert "point matinal" in (tmp_path / "j.log").read_text(encoding="utf-8")


def test_main_sans_briefing_echoue_proprement(tmp_path):
    assert pm.main(["--briefing", str(tmp_path / "absent.json"),
                    "--journal", str(tmp_path / "j.log")]) == 2
    assert "briefing illisible" in (tmp_path / "j.log").read_text(encoding="utf-8")
