import os
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

def entrainer_modele():
    # 1. Charger le dataset généré
    chemin_data = "data/dataset_maroc.csv"
    if not os.path.exists(chemin_data):
        print("Erreur : Le fichier data/dataset_maroc.csv est introuvable.")
        return

    df = pd.read_csv(chemin_data)
    print(f"Dataset chargé : {len(df)} trajets.")

    # 2. Encodage de la colonne météo (texte -> colonnes numériques 0/1)
    df_encoded = pd.get_dummies(df, columns=["meteo"], drop_first=True)

    # Séparer les variables d'entrée (X) et la cible à prédire (y = duree_reelle_min)
    X = df_encoded.drop(columns=["duree_reelle_min"])
    y = df_encoded["duree_reelle_min"]

    # 3. Séparation : 80% pour l'entraînement, 20% pour le test
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    # 4. Comparaison de deux algorithmes de Régression
    modeles = {
        "Régression Linéaire (Baseline)": LinearRegression(),
        "Random Forest Regressor": RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    }

    meilleur_modele = None
    meilleure_mae = float("inf")
    nom_meilleur = ""

    print("\n--- ÉVALUATION DES MODÈLES ---")
    for nom, modele in modeles.items():
        # Entraînement
        modele.fit(X_train, y_train)
        
        # Prédictions sur les données de test (20%)
        predictions = modele.predict(X_test)
        
        # Calcul des scores
        mae = mean_absolute_error(y_test, predictions)
        r2 = r2_score(y_test, predictions)
        
        print(f"\nModèle : {nom}")
        print(f"  -> Erreur moyenne (MAE) : {mae:.2f} minutes")
        print(f"  -> Précision (Score R²)  : {r2:.2%}")

        # Garder le modèle le plus précis (MAE la plus faible)
        if mae < meilleure_mae:
            meilleure_mae = mae
            meilleur_modele = modele
            nom_meilleur = nom

    # 5. Sauvegarde du meilleur modèle et des colonnes exactes
    os.makedirs("models", exist_ok=True)
    joblib.dump(meilleur_modele, "models/modele_retard_maroc.pkl")
    joblib.dump(list(X.columns), "models/colonnes_modele.pkl")

    print(f"\nSuccès ! Le modèle '{nom_meilleur}' (MAE = {meilleure_mae:.2f} min) a été sauvegardé dans 'models/'.")

if __name__ == "__main__":
    entrainer_modele()