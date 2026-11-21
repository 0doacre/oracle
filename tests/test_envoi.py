import json
from datetime import datetime, timezone

import pytest

from oracle import envoi, rendu

ETE = datetime(2026, 7, 1, 5, 10, tzinfo=timezone.utc)      # 7 h 10 à Paris (UTC+2)
HIVER = datetime(2026, 12, 1, 6, 10, tzinfo=timezone.utc)   # 7 h 10 à Paris (UTC+1)


def utc(mois, jour, heure, minute=5):
    return datetime(2026, mois, jour, heure, minute, tzinfo=timezone.utc)


# ---------- Créneaux ----------

def test_le_creneau_suit_l_heure_de_paris_ete_comme_hiver():
    assert envoi.creneau_a_envoyer(ETE, set()) == "2026-07-01 07h"
    assert envoi.creneau_a_envoyer(HIVER, set()) == "2026-12-01 07h"
    assert envoi.creneau_a_envoyer(utc(12, 1, 5), set()) is None       # 6 h à Paris


@pytest.mark.parametrize("heure_utc, attendu", [
    (11, "2026-12-01 12h"), (12, "2026-12-01 12h"), (13, None),       # 12 h, 13 h, 14 h Paris
    (18, "2026-12-01 19h"), (19, "2026-12-01 19h"), (20, None),
])
def test_rattrapage_pendant_deux_heures_seulement(heure_utc, attendu):
    assert envoi.creneau_a_envoyer(utc(12, 1, heure_utc), set()) == attendu


def test_un_creneau_deja_envoye_ne_repart_pas():
    assert envoi.creneau_a_envoyer(utc(12, 1, 7), {"2026-12-01 07h"}) is None   # 8 h Paris


def test_l_etat_ne_garde_que_les_trente_derniers(tmp_path):
    chemin = tmp_path / "etat" / "envois.json"
    deja = {f"2026-11-{j:02d} 07h" for j in range(1, 31)}
    envoi.noter_envoi(chemin, deja, "2026-12-01 07h")
    garde = envoi.lire_etat(chemin)
    assert len(garde) == 30 and "2026-12-01 07h" in garde and "2026-11-01 07h" not in garde


def test_un_etat_illisible_vaut_un_etat_vide(tmp_path):
    chemin = tmp_path / "envois.json"
    chemin.write_text("pas du json", encoding="utf-8")
    assert envoi.lire_etat(chemin) == set()


# ---------- Rendu ----------

def test_le_markdown_du_point_devient_du_html():
    html = rendu.markdown_vers_html(
        "# Titre\n\n## L'essentiel\n\n- **Gros ordre** : 10 $ — *règle*\n- deux\n\n"
        "> ⚠ attention\n\n---\n\ntexte")
    assert "<h1>Titre</h1>" in html and "<h2>L'essentiel</h2>" in html
    assert "<ul>\n<li><strong>Gros ordre</strong> : 10 $ — <em>règle</em></li>\n<li>deux</li>\n</ul>" in html
    assert "<blockquote>⚠ attention</blockquote>" in html and "<hr>" in html
    assert "<p>texte</p>" in html


def test_un_intitule_ne_peut_pas_injecter_de_html():
    html = rendu.markdown_vers_html('- « <script>alert(1)</script> » & <b>gras</b>')
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp;" in html


def test_l_etoile_d_un_calcul_n_ouvre_pas_d_italique():
    assert "<em>" not in rendu.markdown_vers_html("- volume × 4 et 2 * 3 = 6")


# ---------- Envoi complet ----------

class FauxSMTP:
    envoyes: list = []

    def __init__(self, hote, port, context, timeout):
        self.hote, self.port = hote, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, utilisateur, mot_de_passe):
        if mot_de_passe != "bon":
            import smtplib
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")
        self.utilisateur = utilisateur

    def send_message(self, message):
        FauxSMTP.envoyes.append(message)


@pytest.fixture
def dossier(tmp_path, monkeypatch):
    briefing = {"meta": {"generated_at": "2026-12-01T06:00:00+00:00", "total_scanned": 9,
                         "errors": {}},
                "markets": [{"title": "Will <X> happen?", "category": "Politique USA",
                             "source": "kalshi", "yes_prob": 40.0, "end_date": "2027-01-01",
                             "score": 1, "trade_alert": None}]}
    (tmp_path / "b.json").write_text(json.dumps(briefing), encoding="utf-8")
    for v, val in [("ORACLE_SMTP_UTILISATEUR", "moi@exemple.org"), ("ORACLE_SMTP_MOT_DE_PASSE", "bon"),
                   ("ORACLE_DESTINATAIRE", "moi@exemple.org"), ("GITHUB_REPOSITORY", "Compte/oracle")]:
        monkeypatch.setenv(v, val)
    monkeypatch.delenv("ORACLE_URL_PAGE", raising=False)
    FauxSMTP.envoyes = []
    return tmp_path


def lancer(dossier, monkeypatch, moment, *options):
    monkeypatch.setattr(envoi, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: moment)}))
    return envoi.main(["--briefing", str(dossier / "b.json"), "--site", str(dossier / "site"),
                       "--etat", str(dossier / "etat" / "envois.json"),
                       "--journal", str(dossier / "j.log"), *options], smtp=FauxSMTP)


def test_au_creneau_le_mail_part_une_seule_fois(dossier, monkeypatch):
    assert lancer(dossier, monkeypatch, HIVER) == 0
    assert len(FauxSMTP.envoyes) == 1
    mail = FauxSMTP.envoyes[0]
    assert mail["Subject"] == "Oracle — 01/12 à 07h10" and mail["To"] == "moi@exemple.org"
    corps_html = mail.get_body(("html",)).get_content()
    assert "&lt;X&gt;" in corps_html and "https://compte.github.io/oracle/" in corps_html
    assert lancer(dossier, monkeypatch, utc(12, 1, 7)) == 0            # 8 h : déjà envoyé
    assert len(FauxSMTP.envoyes) == 1


def test_hors_creneau_le_point_est_ecrit_sans_mail(dossier, monkeypatch):
    assert lancer(dossier, monkeypatch, utc(12, 1, 9)) == 0            # 10 h Paris
    assert FauxSMTP.envoyes == []
    assert (dossier / "site" / "point.html").exists() and (dossier / "site" / "point.md").exists()
    assert "pas de créneau" in (dossier / "j.log").read_text(encoding="utf-8")


def test_forcer_envoie_a_toute_heure(dossier, monkeypatch):
    assert lancer(dossier, monkeypatch, utc(12, 1, 9), "--forcer") == 0
    assert len(FauxSMTP.envoyes) == 1


def test_sans_secrets_pas_d_envoi_et_on_le_dit(dossier, monkeypatch):
    monkeypatch.delenv("ORACLE_SMTP_MOT_DE_PASSE")
    assert lancer(dossier, monkeypatch, HIVER) == 1
    assert "ORACLE_SMTP_MOT_DE_PASSE" in (dossier / "j.log").read_text(encoding="utf-8")
    assert not (dossier / "etat" / "envois.json").exists()      # pas noté : sera retenté


def test_un_echec_smtp_est_journalise_sans_le_mot_de_passe(dossier, monkeypatch):
    monkeypatch.setenv("ORACLE_SMTP_MOT_DE_PASSE", "mauvais-secret")
    assert lancer(dossier, monkeypatch, HIVER) == 1
    journal = (dossier / "j.log").read_text(encoding="utf-8")
    assert "SMTPAuthenticationError" in journal and "mauvais-secret" not in journal
    assert not (dossier / "etat" / "envois.json").exists()
