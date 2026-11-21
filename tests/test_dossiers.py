import pytest

from oracle import dossiers
from oracle.marche import Marche
from oracle.selection import choisir, thematiser

SUIVI = dossiers.charger()      # le vrai dossiers.toml du dépôt


@pytest.mark.parametrize("titre, attendu", [
    # Intitulés réels du relevé du 21/11.
    ("US x Iran Effective Ceasefire by November 22?", "Iran"),
    ("Israel x Iran ceasefire continues through November 30?", "Iran"),   # égalité : Iran d'abord
    ("Will the Democratic Progressive Party (DPP) win the most head of local government "
     "elections in the 2026 Taiwan local elections?", "Chine – Taïwan"),
    ("Will Trump speak to Volodymyr Zelenskyy by November 30?", "Ukraine – Russie"),
    ("Will Marine Le Pen win the 2027 French presidential election?", "Présidentielle 2027"),
    ("Will Trump be impeached before his term ends?", "Trump et Washington"),
    ("Will J.D. Vance be the nominee for the Presidency for the Republican party?", "Élections US 2028"),
    ("Will WTI Crude Oil (WTI) hit (LOW) $80 in November?", "Pétrole et énergie"),
    ("AI bubble burst in 2026?", "Bulle IA et labos"),
    ("US recession by end of 2026?", "Récession et marchés"),
    ("Will the Fed increase interest rates by 25 bps after the December 2026 meeting?", None),
])
def test_les_vrais_intitules_vont_dans_le_bon_dossier(titre, attendu):
    assert SUIVI.attribuer(titre) == attendu


@pytest.mark.parametrize("titre", [
    "Will Donald Trump make between 40 and 59 Truth Social posts the week of Nov 15, 2026?",
    "Will AI solve the Riemann Hypothesis in 2026?",
    "Will the Hodge Conjecture be the next Millennium Prize Problem solved by AI?",
])
def test_le_bruit_declare_est_reconnu(titre):
    assert SUIVI.est_du_bruit(titre)


def test_les_mots_sont_entiers():
    # « oil » ne doit pas trouver « turmoil », « afd » ni « dpp » dans un autre mot.
    assert SUIVI.attribuer("Market turmoil before the summit?") is None
    assert SUIVI.attribuer("Will S&P 500 close above 7000?") == "Récession et marchés"


def test_un_fichier_sans_bruit_ni_mots_reste_valide():
    suivi = dossiers.depuis_texte('[[dossier]]\nnom = "Vide"\nmots = []\n')
    assert suivi.dossiers == [] and not suivi.est_du_bruit("n'importe quoi")


def marche(titre, score=1.0, evenement=None):
    m = Marche(source="kalshi", id=titre, evenement=evenement or titre, titre=titre, prob=50,
               volume_total=1e6, volume_24h=1e5, fin="2027-01-01", url="u")
    m.score = score
    return m


def test_thematiser_garde_un_marche_de_dossier_et_ecarte_le_bruit():
    lot = [marche("Will Le Pen win?"), marche("Truth Social posts by Trump?"),
           marche("Who wins the cooking contest?")]
    gardes = thematiser(lot, SUIVI)
    assert [m.titre for m in gardes] == ["Will Le Pen win?"]
    assert gardes[0].dossier == "Présidentielle 2027"


def test_chaque_dossier_a_ses_places_reservees():
    forts = [marche(f"Will Trump sign order {i}?", score=100 - i) for i in range(10)]
    iran = [marche(f"Iran deal {i}?", score=5 - i) for i in range(3)]
    for m in forts + iran:
        m.dossier = SUIVI.attribuer(m.titre)
    choisis = choisir(forts + iran, n=5, par_groupe=2, groupe=lambda m: m.dossier)
    assert sum(m.dossier == "Iran" for m in choisis) == 2
    # Un marché sans dossier n'a pas de réserve.
    sans = marche("Who wins the cooking contest?", score=0)
    assert sans not in choisir(forts + [sans], n=5, par_groupe=2, groupe=lambda m: m.dossier)
