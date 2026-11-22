"""Contrat d'entree partage entre entrainement et futures predictions API."""
import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    "distance_km", "duree_theorique_min", "heure_depart", "jour_semaine",
    "est_weekend", "est_heure_pointe", "est_intra_urbain",
]
WEATHER_LEVELS = {"Soleil": 0, "Nuageux": 1, "Pluie": 2, "Forte pluie": 3}
WEATHER = list(WEATHER_LEVELS)
FEATURE_COLUMNS = NUMERIC_FEATURES + ["intensite_meteo"]


def prepare_features(frame):
    missing = set(NUMERIC_FEATURES + ["meteo"]) - set(frame.columns)
    if missing:
        raise ValueError(f"Variables manquantes: {sorted(missing)}")
    if not frame["meteo"].isin(WEATHER).all():
        raise ValueError("Categorie meteo inconnue ou absente")
    values = frame[NUMERIC_FEATURES].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise ValueError("Les variables numeriques doivent etre finies")
    for name in ["distance_km", "duree_theorique_min"]:
        if (values[name] <= 0).any():
            raise ValueError(f"{name} doit etre strictement positif")
    for name, upper in [("heure_depart", 23), ("jour_semaine", 6),
                        ("est_weekend", 1), ("est_heure_pointe", 1), ("est_intra_urbain", 1)]:
        if not (values[name].between(0, upper) & (values[name] % 1 == 0)).all():
            raise ValueError(f"{name} doit etre un entier entre 0 et {upper}")
    # Ordre coherent avec les perturbations du generateur, identique en lot
    # et en requete unitaire. Les arbres contraignent cette seule variable.
    values["intensite_meteo"] = frame["meteo"].map(WEATHER_LEVELS).astype(int)
    return values.reindex(columns=FEATURE_COLUMNS)


def alert_categories(delay):
    """0: fluide (<5), 1: ralentissements (5 a 15 inclus), 2: retard (>15)."""
    return np.where(np.asarray(delay) < 5, 0, np.where(np.asarray(delay) <= 15, 1, 2))
