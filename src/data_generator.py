import json
import math
import random
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

def haversine(lat1, lon1, lat2, lon2):
    """Calcule la distance à vol d'oiseau en km entre deux coordonnées GPS."""
    R = 6371.0  # Rayon de la Terre en km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def generer_dataset_maroc(nb_trajets=10000, seed=42):
    """Genere des simulations reproductibles; les durees ne sont pas observees."""
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    # Charger les villes du Maroc
    with open(PROJECT_ROOT / "data/villes_maroc.json", "r", encoding="utf-8") as f:
        villes = json.load(f)
    noms_villes = list(villes.keys())

    donnees = []
    meteos_possibles = ["Soleil", "Nuageux", "Pluie", "Forte pluie"]
    poids_meteo = [0.65, 0.20, 0.11, 0.04]  # Climat réaliste au Maroc

    for _ in range(nb_trajets):
        # 50% trajets intra-urbains (livraison en ville), 50% trajets inter-urbains
        est_intra_urbain = rng.random() < 0.5

        if est_intra_urbain:
            ville = rng.choice(noms_villes)
            # Simulation de deux points proches dans la même ville (écart ~0.01 à 0.12 degré)
            lat1, lon1 = villes[ville]["lat"], villes[ville]["lon"]
            lat2 = lat1 + rng.uniform(-0.10, 0.10)
            lon2 = lon1 + rng.uniform(-0.10, 0.10)
            distance_km = max(1.5, haversine(lat1, lon1, lat2, lon2) * 1.25)
            vitesse_base_kmh = rng.uniform(28, 42)  # Vitesse moyenne en ville
        else:
            v1, v2 = rng.sample(noms_villes, 2)
            dist_vol = haversine(villes[v1]["lat"], villes[v1]["lon"],
                                 villes[v2]["lat"], villes[v2]["lon"])
            distance_km = dist_vol * 1.25  # Facteur de détour routier
            vitesse_base_kmh = rng.uniform(75, 105) # Vitesse route nationale / autoroute

        heure_depart = rng.randint(0, 23)
        jour_semaine = rng.randint(0, 6)  # 0 = Lundi, 6 = Dimanche
        meteo = rng.choices(meteos_possibles, weights=poids_meteo, k=1)[0]

        # Feature Engineering : Heures de pointe au Maroc (8h-9h, 12h-14h, 18h-20h)
        est_weekend = 1 if jour_semaine in [5, 6] else 0
        est_heure_pointe = 1 if (est_weekend == 0 and heure_depart in [8, 9, 12, 13, 18, 19, 20]) else 0

        # Calcul du temps théorique sans perturbation (en minutes)
        temps_theorique = (distance_km / vitesse_base_kmh) * 60

        # Application des facteurs de ralentissement réels
        multiplicateur = 1.0

        if est_heure_pointe == 1:
            # Impact plus fort en ville que sur autoroute
            multiplicateur += rng.uniform(0.25, 0.45) if est_intra_urbain else rng.uniform(0.08, 0.18)

        if meteo == "Nuageux":
            multiplicateur += 0.03
        elif meteo == "Pluie":
            multiplicateur += rng.uniform(0.15, 0.25)
        elif meteo == "Forte pluie":
            multiplicateur += rng.uniform(0.30, 0.50)

        # Interaction critique : Pluie + Heure de pointe = embouteillages majeurs
        if est_heure_pointe == 1 and meteo in ["Pluie", "Forte pluie"]:
            multiplicateur += 0.20

        # Ajout d'un bruit aléatoire réaliste (feux rouges, travaux, péages)
        bruit_minutes = np_rng.normal(0, 2.5)
        duree_reelle_min = max(3.0, (temps_theorique * multiplicateur) + bruit_minutes)

        donnees.append({
            "distance_km": round(distance_km, 2),
            "duree_theorique_min": round(temps_theorique, 2),
            "heure_depart": heure_depart,
            "jour_semaine": jour_semaine,
            "est_weekend": est_weekend,
            "est_heure_pointe": est_heure_pointe,
            "est_intra_urbain": 1 if est_intra_urbain else 0,
            "meteo": meteo,
            "duree_reelle_min": round(duree_reelle_min, 1)
        })

    df = pd.DataFrame(donnees)
    (PROJECT_ROOT / "data").mkdir(exist_ok=True)
    df.to_csv(PROJECT_ROOT / "data/dataset_maroc.csv", index=False)
    print(f"Dataset généré avec succès : {len(df)} trajets sauvegardés dans data/dataset_maroc.csv")
    print(df.head())
    return df

if __name__ == "__main__":
    generer_dataset_maroc(10000)
