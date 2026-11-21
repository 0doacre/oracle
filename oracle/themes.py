"""Classement thématique par mots-clés, et exclusion du bruit.

Les titres des marchés sont en anglais : les mots-clés le sont surtout, avec
quelques formes françaises. Tout est insensible à la casse et borné aux mots
(« eu » ne doit pas trouver « Europe », « ai » ne doit pas trouver « Taiwan »).
"""

import re

# L'ordre départage les égalités : la catégorie la plus spécifique d'abord.
CATEGORIES: dict[str, list[str]] = {
    "Droites radicales & mouvements identitaires": [
        r"far[- ]right", r"nationalis[tm]\w*", r"populis[tm]\w*", r"afd",
        r"rassemblement national", r"le pen", r"bardella", r"reform uk", r"farage",
        r"culture war", r"manosphere", r"masculinis[tm]\w*", r"orb[aá]n", r"fidesz",
        r"wilders", r"pvv", r"fp[öo]", r"chega", r"sweden democrats", r"identitari\w*",
    ],
    "Politique France & G7": [
        r"france", r"french", r"macron", r"assembl[ée]e nationale", r"national assembly",
        r"germany", r"german", r"bundestag", r"merz", r"uk", r"united kingdom", r"britain",
        r"british", r"starmer", r"tor(y|ies)",  # pas « labour » : aussi en Nouvelle-Zélande, en Australie
 r"italy", r"italian", r"meloni",
        r"japan", r"japanese", r"canada", r"canadian", r"carney", r"eu", r"european union",
        r"european parliament", r"european commission", r"von der leyen", r"g7",
    ],
    "Politique USA": [
        r"trump", r"congress\w*", r"senate", r"senator", r"house of representatives",
        r"supreme court", r"scotus", r"white house", r"presiden(t|tial)", r"governor",
        r"midterms?", r"democrats?", r"republicans?",
        # Pas « democratic » seul : « Democratic Progressive Party » est taïwanais (vu le 21/11).
        r"democratic (party|nominee|nomination|primary|presidential|leader|senator)", r"gop", r"vance",
        r"newsom", r"impeach\w*", r"executive order", r"speaker", r"filibuster",
        r"government shutdown", r"shutdown",
    ],
    "Géopolitique & Risques": [
        r"wars?", r"ukrain\w*", r"russia\w*", r"putin", r"zelensk[yi]\w*", r"china",
        r"chinese", r"xi jinping", r"taiwan", r"middle east", r"iran\w*", r"israel\w*",
        r"gaza", r"hamas", r"hezbollah", r"nato", r"otan", r"terror\w*", r"ceasefire",
        r"invasion", r"invade", r"military", r"missiles?", r"nuclear weapons?",
        r"north korea", r"syria", r"conflict", r"climate", r"hurricane", r"earthquake",
        r"pandemic", r"disaster", r"guerre",
    ],
    "Macro-finance, Énergie & IA": [
        r"oil", r"crude", r"brent", r"wti", r"natural gas", r"opec", r"energy",
        r"nuclear (power|plant|energy)", r"recession", r"gdp", r"inflation", r"cpi",
        r"unemployment", r"fed", r"federal reserve", r"rate (cut|hike)s?",
        r"interest rates?", r"ecb", r"bce", r"powell", r"lagarde", r"s&p", r"nasdaq",
        r"stock market", r"bank failure", r"tariffs?", r"ai", r"a\.i\.",
        r"artificial intelligence", r"openai", r"chatgpt", r"gpt-?\d", r"anthropic",
        r"nvidia", r"semiconductors?", r"tsmc", r"agi", r"ai bubble",
    ],
    "Gouvernance publique, Espace & Cyber": [
        r"education", r"schools?", r"pensions?", r"social reform", r"minimum wage",
        r"cyber\w*", r"hack(ed|ers?)?", r"ransomware", r"data breach", r"nasa",
        r"spacex", r"starship", r"artemis", r"moon", r"lunar", r"mars", r"esa",
    ],
}

# Catégories Kalshi rejetées d'office (« Mentions » : « dira-t-il tel mot »).
CATEGORIES_SOURCE_EXCLUES = {"Sports", "Entertainment", "Crypto", "Mentions"}

EXCLUSIONS = [
    # Sport
    r"nba", r"nfl", r"mlb", r"nhl", r"ncaa", r"ufc", r"fifa", r"world cup",
    r"premier league", r"champions league", r"la liga", r"serie a", r"super bowl",
    r"tennis", r"wimbledon", r"golf", r"pga", r"f1", r"formula 1", r"grand prix",
    r"olympics?", r"boxing", r"match", r"touchdowns?", r"playoffs?", r"mvp",
    # Crypto court terme
    r"bitcoin", r"btc", r"ethereum", r"eth", r"solana", r"sol", r"dogecoin", r"xrp",
    r"crypto(currency)? price",
    # Pop culture, cinéma, musique
    r"oscars?", r"grammys?", r"emmys?", r"golden globes?", r"box office", r"movies?",
    r"films?", r"albums?", r"songs?", r"spotify", r"billboard", r"taylor swift",
    r"eurovision", r"celebrit\w*", r"youtubers?", r"mrbeast", r"rotten tomatoes",
    # Esport
    r"esports?", r"league of legends", r"dota", r"cs2", r"valorant",
]


def _motif(mots: list[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(mots) + r")\b", re.IGNORECASE)


_CATEGORIES = {nom: _motif(mots) for nom, mots in CATEGORIES.items()}
_EXCLUSIONS = _motif(EXCLUSIONS)


def est_exclu(titre: str, categorie_source: str = "") -> bool:
    return categorie_source in CATEGORIES_SOURCE_EXCLUES or bool(_EXCLUSIONS.search(titre))


def classer(titre: str) -> str | None:
    """La catégorie qui a le plus de mots-clés dans le titre, ou None."""
    meilleure, max_touches = None, 0
    for nom, motif in _CATEGORIES.items():
        touches = len(motif.findall(titre))
        if touches > max_touches:
            meilleure, max_touches = nom, touches
    return meilleure
