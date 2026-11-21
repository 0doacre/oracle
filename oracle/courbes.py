"""Mini-courbes en caractères (lisibles dans tout mail, sans image ni script) et
séries pour les courbes de la page."""

BLOCS = "▁▂▃▄▅▆▇█"
AMPLITUDE_MIN_PT = 5.0   # en deçà, une courbe reste presque plate : 0,3 point de bruit ne
                         # doit pas ressembler à un effondrement
POINTS_MIN = 3


def par_heure(points: list[tuple[int, float]], debut: int, fin: int) -> list[tuple[int, float]]:
    """(heure, dernier prix connu à la fin de cette heure) entre debut et fin
    (timestamps en s). Une heure sans relevé reprend le prix précédent ; avant le
    premier relevé, rien."""
    points = sorted(points)
    serie, i, dernier = [], 0, None
    for heure in range(debut, fin, 3600):
        while i < len(points) and points[i][0] < heure + 3600:
            dernier = points[i][1]
            i += 1
        if dernier is not None:
            serie.append((heure, dernier))
    return serie


def mini_courbe(valeurs: list[float]) -> str:
    """« ▁▂▃▅▇ » : une valeur par caractère, de 0 à 100 points de probabilité.
    Vide s'il y a trop peu de points pour dessiner quoi que ce soit."""
    if len(valeurs) < POINTS_MIN:
        return ""
    bas, haut = min(valeurs), max(valeurs)
    amplitude = max(haut - bas, AMPLITUDE_MIN_PT)
    centre = (bas + haut) / 2
    plancher = centre - amplitude / 2
    niveaux = len(BLOCS) - 1
    return "".join(BLOCS[max(0, min(niveaux, round((v - plancher) / amplitude * niveaux)))]
                   for v in valeurs)
