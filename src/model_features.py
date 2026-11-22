"""Contrat d'entree partage entre entrainement et futures predictions API."""
import numpy as np
import pandas as pd

NUMERIC_FEATURES = [
    "distance_km", "duree_theorique_min", "heure_depart", "jour_semaine",
    "est_weekend", "est_heure_pointe", "est_intra_urbain",
]
WEATHER = ["Forte pluie", "Nuageux", "Pluie", "Soleil"]
FEATURE_COLUMNS = NUMERIC_FEATURES + [f"meteo_{value}" for value in WEATHER[1:]]


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
    # Encodage explicite: identique pour une ligne et pour un lot complet.
    for weather in WEATHER[1:]:
        values[f"meteo_{weather}"] = (frame["meteo"] == weather).astype(int)
    return values.reindex(columns=FEATURE_COLUMNS)


def alert_categories(delay):
    """0: fluide (<5), 1: ralentissements (5 a 15 inclus), 2: retard (>15)."""
    return np.where(np.asarray(delay) < 5, 0, np.where(np.asarray(delay) <= 15, 1, 2))
