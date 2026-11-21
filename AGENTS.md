# oracle

À lire en entier avant toute action. Les règles générales sont dans `~/.agents/REGLES.md` ;
celles de ce fichier priment pour ce projet.

## Le projet

Un oracle personnel : il collecte de l'information publique selon les goûts de son
utilisateur, la filtre et la résume dans un briefing compact, puis dans un point
matinal lisible.

Deux étages, sans LLM ni coût :

1. **Collecte** : des *sources* interrogent des API publiques, filtrent le bruit,
   gardent un historique en SQLite et exportent un JSON de moins de 25 Ko.
2. **Point** : des phrases modèles. Le mail donne « Les 5 choses à savoir » : une
   ligne par **dossier suivi** (`dossiers.toml`, que l'utilisateur modifie), les plus
   importants d'abord (gros ordre, mouvement confirmé, échéance proche), chacun
   avec ses deux titres de presse les plus récents, puis « Aussi suivi » (dossiers
   d'actualité seule : Éducation nationale, Administration). La page ajoute le
   détail par dossier. Intitulés de marchés en anglais ; aucun LLM.

Deux façons de le faire tourner :
- **GitHub Actions** (`.github/workflows/oracle.yml`) : un relevé chaque heure, le
  point par mail à 7 h, 12 h et 19 h (Paris), la page (lecteur + briefing + point)
  sur GitHub Pages. Dépôt public : aucun secret ni donnée personnelle dans le dépôt,
  identifiants Gmail dans les secrets GitHub. Historique gardé par le cache d'Actions.
- **Ce PC** (tâches planifiées Windows) : relevé horaire, point à 7 h 10 dans `points/`.

Sources : **Kalshi** (marché régulé, volumes en contrats ≈ USD), **Polymarket**
(USDC, alertes avec profil du portefeuille) et **Manifold** (monnaie fictive, signal
pondéré à 0,7). Toute source respecte l'interface `Source`.

**Polymarket est bloqué en France** par le DNS des fournisseurs d'accès (redirection
vers l'ANJ). Le poste de l'utilisateur utilise un autre résolveur DNS (1.1.1.1 en
DNS-over-HTTPS), réglé à la main dans Windows. Ne **jamais** contourner le blocage dans
le code (pas de DNS forcé, pas de `verify=False`) : sans ce réglage, la source est
simplement notée en panne. Ne jamais parier : l'oracle ne fait que lire.

**Où en est le travail** : étape 1 (ce qui se joue aujourd'hui), dossiers et actualité
graphiques (mini-courbe 24 h dans le mail, courbes 7 jours sur la page) et météo
faits. Suivantes : alertes en direct, puis mesure de la valeur des signaux une fois
les marchés résolus.

**Météo** : Open-Meteo, en tête du point (le jour même ; le lendemain à partir de
17 h). Le lieu vient du secret GitHub `ORACLE_METEO` (« lat,lon,nom ») : il n'entre
jamais dans le dépôt, ni dans le code, ni dans les tests, ni dans ce fichier.

**Actualité** : flux RSS (médias français, éducation, BBC, Al Jazeera, Guardian) et
GDELT. Titre, source, heure et lien seulement, jamais le texte (droits d'auteur).
GDELT répond souvent 429 : il complète, on n'en dépend jamais. AEF info et La Lettre A
sont payants et sans flux libre ; education.gouv.fr refuse les robots (403).

**Pourquoi pas de LLM dans le point** : trois essais avec Ministral 8B (Ollama, local)
le 21/11/2026. Il a inversé le côté d'un pari, fait « succéder Schumer à Schumer » et
présenté des prix comme des avis ou des certitudes (« 12,5 % des sondés », « la Fed
augmentera »). Un contrôle par mots-clés n'en attrapait qu'une partie. Ne pas le
réintroduire sans un contrôle qui vérifie le sens, pas seulement les mots.

## Règles du projet

- Bibliothèque standard Python uniquement (`urllib`, `sqlite3`, `json`…). Aucune clé d'API.
- pytest **n'appelle jamais le réseau** : les tests tournent sur des réponses réelles
  enregistrées dans `tests/fixtures/`.
- Vérifier un endpoint par un vrai appel avant d'écrire du code dessus.
- Les variations (`delta_1h`, `delta_6h`, `delta_24h`) valent `null` tant que
  l'historique est trop court ; jamais 0 par défaut. Une variation sur 1 h ou 6 h ne
  compte que sur un marché qui a échangé au moins 20 000 $ en 24 h
  (`confirmed_moves` dans le JSON ; mesures dans `oracle/selection.py`).
- `dossiers.toml` appartient à l'utilisateur : ne pas changer ses dossiers sans lui
  demander. Le bruit déclaré (`[bruit]`) n'est jamais retenu.
- « Aujourd'hui » et les créneaux de mail se comptent en heure de Paris (`oracle/temps.py`).
- Fixtures anonymisées à l'enregistrement (dépôt public) : pas de pseudonyme, de
  biographie, d'avatar ni de vrai portefeuille.
- Deux tâches planifiées Windows (`pythonw`, compte courant, session ouverte
  seulement) : relevé toutes les heures, point à 7 h 10. Compte rendu dans `oracle.log`.
- Toute phrase d'un texte destiné à l'utilisateur vient d'un modèle fixe en Python :
  un pourcentage est « le prix du OUI », jamais un avis ni une prévision.
- Le briefing s'écrit de façon atomique (fichier provisoire, puis remplacement).
- Code et noms en français ; les clés du JSON de sortie restent en anglais (contrat fixe).
- Aucun conseil d'investissement : l'oracle informe, il ne recommande pas de pari.

## Carte des fichiers

| Fichier ou dossier | Rôle |
|---|---|
| `collecteur.py` | Point d'entrée : un relevé → `briefing_oracle.json` + `oracle_state.db` (+ `--historique` : courbes 7 jours) |
| `point_matinal.py` | Point d'entrée : briefing → `points/AAAA-MM-JJ.md` |
| `diffuser.py` | Point d'entrée GitHub : point dans `site/`, mail aux créneaux (`--forcer`) |
| `.github/workflows/oracle.yml` | Relevé horaire, mail, cache de l'historique, GitHub Pages |
| `dossiers.toml` | Dossiers suivis et bruit, modifiables par l'utilisateur |
| `oracle/dossiers.py` | Lecture de `dossiers.toml`, attribution d'un marché ou d'un titre à un dossier |
| `oracle/actualite.py` | Flux RSS/Atom et GDELT → titres par dossier (24 h, 3 au plus) |
| `oracle/meteo.py` | Open-Meteo, lieu depuis `ORACLE_METEO`, phrase en français |
| `oracle/courbes.py` | Prix heure par heure, mini-courbe ▁▂▃▅▇ (amplitude minimale 5 pt) |
| `oracle/point_matinal.py` | « Les 5 choses à savoir » (mail) et détail par dossier (page) |
| `oracle/envoi.py` | Créneaux 7/12/19 h avec rattrapage, état des envois, Gmail (SMTP SSL) |
| `oracle/rendu.py` | Markdown restreint du point → HTML échappé (mail et page) |
| `oracle/temps.py` | Heure de Paris |
| `lecteur.html` | Tableau de bord autonome (JS pur + Chart.js 4.4.1) ; mode démo intégré |
| `oracle/collecteur.py` | Enchaînement du relevé (`relever`) et options en ligne de commande |
| `oracle/source.py` | Interface `Source` ; une source en panne n'arrête pas les autres |
| `oracle/http.py` | `get_json` : gzip, délai, reprises sur 429/5xx |
| `oracle/marche.py` | `Marche`, la forme commune d'un marché |
| `oracle/sources/kalshi.py` | Lecture des événements, probabilité, gros ordres des 24 h |
| `oracle/sources/polymarket.py` | Événements (keyset), gros ordres, profil du portefeuille ; ses pièges en tête |
| `oracle/sources/manifold.py` | Recherche (deux tris), règle de résolution à la demande |
| `oracle/themes.py` | Six catégories et exclusions, par mots-clés bornés |
| `oracle/historique.py` | SQLite sur 7 jours : variations 1 h/6 h/24 h, ratio de volume |
| `oracle/selection.py` | Liquidité, bruit, mouvements confirmés, score, 25 retenus (2 places par dossier) |
| `oracle/briefing.py` | JSON de sortie (< 25 Ko), clés en anglais = contrat |
| `outils/enregistrer_fixtures.py` | Rafraîchit `tests/fixtures/` depuis les vraies API, anonymisées |
| `outils/planifier.ps1` | Les deux tâches : `etat` (défaut), `installer`, `lancer [releve\|point]`, `retirer` |
| `tests/` | Tests pytest (sans réseau, sur fixtures réelles) |
| `pyproject.toml` | Métadonnées et configuration pytest |

## Vérifier son travail

```powershell
python -m pytest
```

Attendu : tous les tests verts, aucun accès réseau (un garde-fou dans `conftest.py`
fait échouer tout appel réel ; une valeur par défaut figée y avait échappé une fois). Une suite verte ne suffit pas :
après un test neuf, casser le code visé et vérifier qu'il échoue.

Un vrai relevé (environ 2 min, réseau) : `python collecteur.py`. Pour un essai rapide :
`python collecteur.py --pages-kalshi 5`.

La tâche planifiée : `powershell -File outils\planifier.ps1` donne son état, le
dernier code de sortie et la fin de `oracle.log`. Le fichier doit rester en UTF-8
avec BOM (PowerShell 5.1).

Le lecteur : `python -m http.server 8765 --bind 127.0.0.1` dans le dossier, puis
`http://127.0.0.1:8765/lecteur.html`. Ouvert en `file://`, il demande le fichier
(le navigateur y interdit `fetch`).
