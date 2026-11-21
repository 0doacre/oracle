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
    connexions: list = []
    coupe_au_login: set = set()     # ports où le serveur coupe pendant l'authentification

    def __init__(self, hote, port, context=None, timeout=None):
        self.hote, self.port = hote, port
        FauxSMTP.connexions.append(port)

    def starttls(self, context):
        self.chiffre = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, utilisateur, mot_de_passe):
        import smtplib
        if self.port in FauxSMTP.coupe_au_login:
            raise smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        if self.port == 587 and not getattr(self, "chiffre", False):
            raise AssertionError("login en clair sur le 587")
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
                             "dossier": "Trump et Washington",
                             "source": "kalshi", "yes_prob": 40.0, "end_date": "2027-01-01",
                             "score": 1, "trade_alert": None}]}
    (tmp_path / "b.json").write_text(json.dumps(briefing), encoding="utf-8")
    for v, val in [("ORACLE_SMTP_UTILISATEUR", "moi@exemple.org"), ("ORACLE_SMTP_MOT_DE_PASSE", "bon"),
                   ("ORACLE_DESTINATAIRE", "moi@exemple.org"), ("GITHUB_REPOSITORY", "Compte/oracle")]:
        monkeypatch.setenv(v, val)
    monkeypatch.delenv("ORACLE_URL_PAGE", raising=False)
    FauxSMTP.envoyes, FauxSMTP.connexions, FauxSMTP.coupe_au_login = [], [], set()
    return tmp_path


def lancer(dossier, monkeypatch, moment, *options):
    monkeypatch.setattr(envoi, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: moment)}))
    return envoi.main(["--briefing", str(dossier / "b.json"), "--site", str(dossier / "site"),
                       "--etat", str(dossier / "etat" / "envois.json"),
                       "--journal", str(dossier / "j.log"), *options],
                      smtp_ssl=FauxSMTP, smtp_clair=FauxSMTP,
                      collecter_actualite=fausse_actualite)


def fausse_actualite(suivi, maintenant, dossiers_gdelt):
    from oracle.actualite import Depeche
    return ({"Trump et Washington": [Depeche("Le Sénat bloque <un> candidat", "franceinfo",
                                             "https://exemple.org/a?x=1&y=2",
                                             "2026-12-01T05:30+00:00")]},
            {"RFI": "503"})


def test_au_creneau_le_mail_part_une_seule_fois(dossier, monkeypatch):
    assert lancer(dossier, monkeypatch, HIVER) == 0
    assert len(FauxSMTP.envoyes) == 1
    mail = FauxSMTP.envoyes[0]
    assert mail["Subject"] == "Oracle — 01/12 à 07h10" and mail["To"] == "moi@exemple.org"
    corps_html = mail.get_body(("html",)).get_content()
    assert "&lt;X&gt;" in corps_html and "https://compte.github.io/oracle/point.html" in corps_html
    assert "Par dossier" not in corps_html                     # le mail est court
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
    assert "authentification refusée" in journal and "mauvais-secret" not in journal
    assert not (dossier / "etat" / "envois.json").exists()


def test_si_le_465_coupe_le_587_prend_le_relais(dossier, monkeypatch):
    # Cas réel du premier essai depuis GitHub.
    FauxSMTP.coupe_au_login = {465}
    assert lancer(dossier, monkeypatch, HIVER) == 0
    assert FauxSMTP.connexions == [465, 587] and len(FauxSMTP.envoyes) == 1
    assert "envoyé (STARTTLS 587)" in (dossier / "j.log").read_text(encoding="utf-8")


def test_si_les_deux_ports_coupent_le_journal_dit_ou(dossier, monkeypatch):
    FauxSMTP.coupe_au_login = {465, 587}
    assert lancer(dossier, monkeypatch, HIVER) == 1
    journal = (dossier / "j.log").read_text(encoding="utf-8")
    assert "SSL 465, étape « authentification »" in journal
    assert "STARTTLS 587, étape « authentification »" in journal


def test_un_refus_d_authentification_n_essaie_pas_l_autre_port(dossier, monkeypatch):
    monkeypatch.setenv("ORACLE_SMTP_MOT_DE_PASSE", "mauvais")
    assert lancer(dossier, monkeypatch, HIVER) == 1
    assert FauxSMTP.connexions == [465]
    assert "authentification refusée (535)" in (dossier / "j.log").read_text(encoding="utf-8")


def test_les_espaces_du_mot_de_passe_d_application_sont_retires(dossier, monkeypatch):
    monkeypatch.setenv("ORACLE_SMTP_MOT_DE_PASSE", " b o n ")
    assert lancer(dossier, monkeypatch, HIVER) == 0


def test_le_diagnostic_decrit_les_identifiants_sans_les_montrer():
    texte = envoi.decrire_identifiants("moi@exemple.org", "abcdefghijklmnop")
    assert "moi" not in texte and "abcd" not in texte
    assert "15 caractères, avec « @ »" in texte and "16 lettres, attendu" in texte
    texte = envoi.decrire_identifiants("moi​", "mot-de-passe-du-compte")
    assert "1 non ASCII ou invisibles" in texte and "SANS « @ »" in texte
    assert "pas 16 lettres" in texte


def test_l_echec_journalise_le_diagnostic(dossier, monkeypatch):
    FauxSMTP.coupe_au_login = {465, 587}
    lancer(dossier, monkeypatch, HIVER)
    journal = (dossier / "j.log").read_text(encoding="utf-8")
    assert "utilisateur : 15 caractères, avec « @ »" in journal
    assert "bon" not in journal.split("—")[-1].replace("non ASCII", "")


def test_une_adresse_sans_arobase_est_refusee_avant_toute_connexion(dossier, monkeypatch):
    monkeypatch.setenv("ORACLE_SMTP_UTILISATEUR", "moi.exemple.org")
    assert lancer(dossier, monkeypatch, HIVER) == 1
    assert FauxSMTP.connexions == []
    assert "adresse incomplète" in (dossier / "j.log").read_text(encoding="utf-8")
    assert "ORACLE_SMTP_UTILISATEUR" in (dossier / "j.log").read_text(encoding="utf-8")
