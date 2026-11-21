import json
from datetime import datetime, timedelta, timezone

from conftest import FauxReseau, charger

from oracle import briefing
from oracle.collecteur import Journal, relever
from oracle.historique import Historique
from oracle.marche import Marche
from oracle.sources.kalshi import Kalshi
from oracle.sources.manifold import Manifold
from oracle.sources.polymarket import Polymarket

MAINTENANT = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)
CLES = {"id", "source", "category", "dossier", "confirmed_moves", "title", "yes_prob", "delta_1h", "delta_6h", "delta_24h",
        "volume_total", "volume_24h", "volume_ratio", "end_date", "days_left",
        "resolution_summary", "url", "score", "trade_alert"}


def test_resume_de_regle_en_quinze_mots_au_plus():
    texte = ("Resolution criteria\n\nThis market will resolve to YES if the Federal Reserve "
             "announces a cut of at least 25 basis points at its December meeting. Else NO.")
    resume = briefing.resumer_regle(texte)
    assert resume.startswith("This market will resolve")
    assert len(resume.rstrip("…").split()) == 15


def test_resume_court_garde_la_phrase_entiere():
    assert briefing.resumer_regle("Resolves YES if it rains. More text.") == "Resolves YES if it rains."


def test_resume_ne_coupe_pas_sur_une_abreviation():
    texte = "If J.D. Vance is the U.S. President on Jan 1, then Yes. Otherwise No."
    assert briefing.resumer_regle(texte) == "If J.D. Vance is the U.S. President on Jan 1, then Yes."


def test_resume_saute_le_contexte_pour_la_condition_de_resolution():
    # Description réelle de Polymarket (fixture), contexte en première phrase.
    texte = ("The 2028 US Presidential Election is scheduled to take place on November 7, "
             "2028. This market will resolve to the person who wins the 2028 US Presidential "
             "Election. The resolution source for this market is the Associated Press.")
    assert briefing.resumer_regle(texte) == (
        "This market will resolve to the person who wins the 2028 US Presidential Election.")


def test_resume_prefere_resolve_a_une_phrase_qui_commence_par_if():
    # Extrait réel de la règle Polymarket « Le Pen 2027 ».
    texte = ("The President of France is elected via a two-round system. If no candidate "
             "achieves this, the top two contenders advance to a runoff. This market will "
             "resolve according to the candidate who wins this election.")
    assert briefing.resumer_regle(texte) == (
        "This market will resolve according to the candidate who wins this election.")


def test_resume_garde_la_premiere_phrase_s_il_n_y_a_pas_de_condition():
    assert briefing.resumer_regle("Contexte général. Autre contexte.") == "Contexte général."


def test_le_json_reste_sous_25_ko():
    m = Marche(source="kalshi", id="x", evenement="x", titre="t" * 140, prob=50,
               volume_total=1, volume_24h=1, fin="2027-01-01", url="u" * 200)
    donnees = briefing.construire([m] * 200, 1000, {}, MAINTENANT)
    texte = briefing.serialiser(donnees)
    assert len(texte.encode("utf-8")) <= briefing.TAILLE_MAX_OCTETS
    lu = json.loads(texte)
    assert 0 < lu["meta"]["selected_count"] == len(lu["markets"]) < 200


def test_ecrire_remplace_le_fichier_sans_laisser_de_provisoire(tmp_path):
    chemin = tmp_path / "briefing.json"
    chemin.write_text("ancien", encoding="utf-8")
    taille = briefing.ecrire(briefing.construire([], 0, {}, MAINTENANT), chemin)
    assert json.loads(chemin.read_text(encoding="utf-8"))["meta"]["selected_count"] == 0
    assert taille == chemin.stat().st_size
    assert [p.name for p in tmp_path.iterdir()] == ["briefing.json"]


def test_le_journal_ecrit_dans_un_fichier_et_tourne(tmp_path, monkeypatch):
    chemin = tmp_path / "oracle.log"
    monkeypatch.setattr(Journal, "TAILLE_MAX", 50)
    journal = Journal(str(chemin))
    journal("premier relevé")
    assert "premier relevé" in chemin.read_text(encoding="utf-8")
    journal("x" * 60)
    journal("après rotation")
    assert chemin.read_text(encoding="utf-8").count("\n") == 1
    assert (tmp_path / "oracle.log.1").exists()


def test_main_journalise_un_echec_sans_lever(tmp_path, monkeypatch):
    import oracle.collecteur as collecteur

    def panne(*a, **k):
        raise RuntimeError("base illisible")

    monkeypatch.setattr(collecteur, "Historique", panne)
    chemin = tmp_path / "oracle.log"
    assert collecteur.main(["--journal", str(chemin), "--base", str(tmp_path / "b.db"),
                            "--sortie", str(tmp_path / "s.json")]) == 2
    assert "base illisible" in chemin.read_text(encoding="utf-8")


def sources(reseau):
    return [Kalshi(get=reseau, pause=lambda s: None),
            Polymarket(get=reseau, pause=lambda s: None), Manifold(get=reseau)]


def test_releve_complet_sur_les_vraies_fixtures(reseau):
    donnees = relever(sources(reseau), Historique(), MAINTENANT, journal=lambda t: None)
    marches = donnees["markets"]
    assert marches, "aucun marché retenu sur les fixtures réelles"
    assert donnees["meta"]["errors"] == {}
    assert donnees["meta"]["total_scanned"] > len(marches)
    for m in marches:
        assert set(m) == CLES
        assert m["category"] is not None
        assert m["delta_24h"] is None              # premier relevé
        assert len(m["resolution_summary"].rstrip("…").split()) <= 15
    titres = " ".join(m["title"] for m in marches).lower()
    assert "fifa" not in titres and "film" not in titres
    assert len(briefing.serialiser(donnees).encode()) <= briefing.TAILLE_MAX_OCTETS


def test_deux_releves_a_24h_donnent_la_variation(reseau):
    historique = Historique()
    relever(sources(reseau), historique, MAINTENANT - timedelta(hours=24), journal=lambda t: None)

    # Le lendemain, un marché Kalshi retenu a pris 10 points.
    premier = relever(sources(FauxReseau()), Historique(), MAINTENANT, journal=lambda t: None)
    cible = next(m for m in premier["markets"] if m["source"] == "kalshi")
    evenements = charger("kalshi_events.json")
    for e in evenements["events"]:
        for mk in e["markets"]:
            if mk["ticker"] == cible["id"]:
                mk["yes_bid_dollars"] = mk["yes_ask_dollars"] = "0.00"
                mk["last_price_dollars"] = f"{(cible['yes_prob'] + 10) / 100:.4f}"
    reseau2 = FauxReseau()
    reseau2.reponses["kalshi.com/trade-api/v2/events"] = evenements

    donnees = relever(sources(reseau2), historique, MAINTENANT, journal=lambda t: None)
    apres = {m["id"]: m for m in donnees["markets"]}
    assert apres[cible["id"]]["delta_24h"] == 10.0


def test_une_source_en_panne_donne_quand_meme_un_briefing(reseau):
    def panne(url, params=None):
        if "kalshi" in url:
            raise TimeoutError("coupure")
        return reseau(url, params)

    donnees = relever(sources(panne), Historique(), MAINTENANT, journal=lambda t: None)
    assert "kalshi" in donnees["meta"]["errors"]
    assert donnees["markets"]
    assert all(m["source"] != "kalshi" for m in donnees["markets"])


def test_les_trois_sources_alimentent_le_briefing(reseau):
    donnees = relever(sources(reseau), Historique(), MAINTENANT, journal=lambda t: None)
    assert {m["source"] for m in donnees["markets"]} >= {"kalshi", "polymarket"}
    assert "polymarket" in donnees["meta"]["volume_units"]


def test_les_alertes_ne_visent_que_les_candidats(reseau):
    relever(sources(reseau), Historique(), MAINTENANT, journal=lambda t: None)
    appels_trades = [a for a in reseau.appels if "/markets/trades" in a[0]]
    assert 0 < len(appels_trades) <= 60
