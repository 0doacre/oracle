import json
from datetime import datetime, timezone

from oracle import point_matinal as pm

MAINTENANT = datetime(2026, 11, 22, 6, 10, tzinfo=timezone.utc)


def m(titre, dossier, prob=50.0, score=10.0, source="polymarket", **autres):
    base = {"title": titre, "dossier": dossier, "category": "x", "source": source,
            "yes_prob": prob, "score": score, "end_date": "2027-04-19", "days_left": 150,
            "delta_1h": None, "delta_6h": None, "delta_24h": None, "confirmed_moves": [],
            "volume_ratio": None, "resolution_summary": "", "trade_alert": None}
    base.update(autres)
    return base


def briefing(*marches, genere="2026-11-22T06:00:00+00:00", erreurs=None):
    return {"meta": {"generated_at": genere, "total_scanned": 1000, "errors": erreurs or {}},
            "markets": list(marches)}


ALERTE = {"amount_usd": 13647.43, "side": "YES", "share_24h": 0.516,
          "wallet_profile": "Wallet concentré"}


def test_une_ligne_par_dossier_avec_le_bon_cote_du_pari():
    texte = pm.cinq_choses(briefing(
        m("US-Iran Final Nuclear Deal?", "Iran", prob=5.0, trade_alert=ALERTE),
        m("Will the U.S. invade Iran?", "Iran", prob=7.5)))
    assert ("1. **Iran** — « US-Iran Final Nuclear Deal? » : 5 % au OUI (polymarket) — gros "
            "ordre de 13 647 $ sur le OUI, 51,6 % du volume du jour, wallet concentré. "
            "*(+ 1 autre sur la page)*") in texte
    alerte_non = dict(ALERTE, side="NO")
    assert "sur le NON" in pm.cinq_choses(briefing(m("Deal?", "Iran", trade_alert=alerte_non)))


def test_cinq_dossiers_au_plus_les_plus_importants_d_abord():
    marches = [m(f"Q{i}", f"Dossier {i}", score=i) for i in range(8)]
    marches[1]["trade_alert"] = ALERTE                          # score 1 + 20
    texte = pm.cinq_choses(briefing(*marches))
    assert texte.count("**Dossier") == 5
    assert texte.index("**Dossier 1**") < texte.index("**Dossier 7**")
    assert "**Dossier 0**" not in texte and "**Dossier 2**" not in texte


def test_seul_un_mouvement_confirme_est_cite():
    confirme = m("AI bubble burst in 2026?", "Bulle IA", delta_1h=-6.3,
                 confirmed_moves=["delta_1h"])
    douteux = m("Jerome Powell out?", "Fed", delta_1h=-4.0, confirmed_moves=[])
    texte = pm.cinq_choses(briefing(confirme, douteux))
    assert "**−6,3 pt en 1 h**" in texte
    assert "−4" not in texte


def test_un_mouvement_sous_le_seuil_n_est_pas_cite():
    texte = pm.cinq_choses(briefing(m("Q", "D", delta_1h=1.9, confirmed_moves=["delta_1h"])))
    assert "1,9" not in texte


def test_echeance_et_pic_de_volume():
    texte = pm.cinq_choses(briefing(
        m("US x Iran Effective Ceasefire by November 22?", "Iran", days_left=1, volume_ratio=4.5)))
    assert "volume × 4,5 par rapport aux jours précédents ; se décide demain." in texte
    assert "se décide" not in pm.cinq_choses(briefing(m("Q", "D", days_left=-1)))


def test_un_marche_hors_dossier_n_est_pas_dans_les_cinq_choses():
    texte = pm.cinq_choses(briefing(m("Fed hike?", None, trade_alert=ALERTE)))
    assert "Aucun dossier suivi n'a de marché actif" in texte


def test_les_sources_en_panne_sont_signalees():
    texte = pm.cinq_choses(briefing(m("Q", "D"), erreurs={"polymarket": "503"}))
    assert "Sources en panne pendant le relevé : polymarket." in texte


def test_le_detail_range_par_dossier_puis_hors_dossiers():
    texte = pm.detail(briefing(
        m("Will Marine Le Pen win the 2027 French presidential election?", "Présidentielle 2027",
          delta_24h=1.5, confirmed_moves=["delta_24h"],
          resolution_summary="This market will resolve according to the candidate who wins."),
        m("Fed hike?", None)))
    assert texte.index("### Présidentielle 2027") < texte.index("## Hors dossiers")
    assert "Variations : +1,5 pt en 24 h. Échéance 2027-04-19." in texte
    assert "*This market will resolve according to the candidate who wins.*" in texte


def test_le_mail_court_n_a_pas_le_detail():
    b = briefing(m("Q", "D"))
    court, _ = pm.composer(b, MAINTENANT, court=True)
    complet, _ = pm.composer(b, MAINTENANT)
    assert "## Les 5 choses à savoir" in court and "## Par dossier" not in court
    assert complet.index("## Les 5 choses à savoir") < complet.index("## Par dossier")
    assert court.startswith("# Oracle — 22/11/2026 à 07h10")     # heure de Paris
    assert "ni un sondage, ni une prévision" in court


def test_un_briefing_ancien_est_signale():
    texte, remarques = pm.composer(briefing(genere="2026-11-21T20:00:00+00:00"), MAINTENANT)
    assert "Briefing ancien" in texte and remarques
    texte, _ = pm.composer(briefing(genere="2026-11-22T05:00:00+00:00"), MAINTENANT)
    assert "Briefing ancien" not in texte


def test_main_ecrit_le_point_du_jour(tmp_path):
    source = tmp_path / "b.json"
    source.write_text(json.dumps(briefing(m("Q", "D"))), encoding="utf-8")
    assert pm.main(["--briefing", str(source), "--dossier", str(tmp_path / "points"),
                    "--journal", str(tmp_path / "j.log")]) == 0
    fichiers = list((tmp_path / "points").glob("*.md"))
    assert len(fichiers) == 1 and "## Par dossier" in fichiers[0].read_text(encoding="utf-8")


def test_main_sans_briefing_echoue_proprement(tmp_path):
    assert pm.main(["--briefing", str(tmp_path / "absent.json"),
                    "--journal", str(tmp_path / "j.log")]) == 2
    assert "briefing illisible" in (tmp_path / "j.log").read_text(encoding="utf-8")
