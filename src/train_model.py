"""Compare les modeles sur simulations avec validation et test separes."""
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import accuracy_score, confusion_matrix, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

try:
    from .model_features import FEATURE_COLUMNS, alert_categories, prepare_features
except ImportError:
    from model_features import FEATURE_COLUMNS, alert_categories, prepare_features

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def evaluate(target, predictions, reference, urban):
    actual_alert = alert_categories(np.asarray(target) - np.asarray(reference))
    predicted_alert = alert_categories(np.asarray(predictions) - np.asarray(reference))
    result = {
        "rows": len(target),
        "mae_minutes": float(mean_absolute_error(target, predictions)),
        "r2": float(r2_score(target, predictions)),
        "alert_accuracy": float(accuracy_score(actual_alert, predicted_alert)),
        "alert_confusion_matrix": confusion_matrix(actual_alert, predicted_alert, labels=[0, 1, 2]).tolist(),
        "groups": {},
    }
    for label, mask in [("urban", np.asarray(urban) == 1), ("intercity", np.asarray(urban) == 0)]:
        if mask.any():
            result["groups"][label] = {
                "rows": int(mask.sum()),
                "mae_minutes": float(mean_absolute_error(np.asarray(target)[mask], np.asarray(predictions)[mask])),
                "alert_accuracy": float(accuracy_score(actual_alert[mask], predicted_alert[mask])),
            }
    return result


def entrainer_modele():
    dataset_path = PROJECT_ROOT / "data/dataset_maroc.csv"
    df = pd.read_csv(dataset_path)
    X = prepare_features(df)
    y = df["duree_reelle_min"]
    if not np.isfinite(y).all() or (y <= 0).any():
        raise ValueError("Durees cibles invalides")
    # Test reserve a l'evaluation finale, jamais au choix du modele.
    development, test = train_test_split(np.arange(len(df)), test_size=0.2, random_state=42)
    train, validation = train_test_split(development, test_size=0.25, random_state=42)
    models = {
        "linear_regression": LinearRegression(),
        "random_forest": RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1),
    }
    validation_metrics = {}
    for name, model in models.items():
        model.fit(X.iloc[train], y.iloc[train])
        validation_metrics[name] = evaluate(
            y.iloc[validation], model.predict(X.iloc[validation]),
            X.iloc[validation].duree_theorique_min, X.iloc[validation].est_intra_urbain,
        )
    selected = min(models, key=lambda name: validation_metrics[name]["mae_minutes"])
    test_metrics = {}
    for name, model in models.items():
        test_metrics[name] = evaluate(y.iloc[test], model.predict(X.iloc[test]),
                                     X.iloc[test].duree_theorique_min, X.iloc[test].est_intra_urbain)
    # Ablation controlee: meme dataset, memes partitions, meme Random Forest.
    old_columns = [column for column in FEATURE_COLUMNS if column != "duree_theorique_min"]
    without_reference = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    without_reference.fit(X.iloc[train][old_columns], y.iloc[train])
    test_metrics["random_forest_without_reference"] = evaluate(
        y.iloc[test], without_reference.predict(X.iloc[test][old_columns]),
        X.iloc[test].duree_theorique_min, X.iloc[test].est_intra_urbain,
    )
    test_metrics["reference_duration_only"] = evaluate(
        y.iloc[test], X.iloc[test].duree_theorique_min,
        X.iloc[test].duree_theorique_min, X.iloc[test].est_intra_urbain,
    )
    report = {
        "data_kind": "synthetic; reference duration is simulated, not fetched from OSRM",
        "limitation": "Scores do not establish accuracy on observed journeys or OSRM inputs.",
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "seed": 42,
        "split_rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        "versions": {"scikit-learn": sklearn.__version__, "pandas": pd.__version__,
                     "numpy": np.__version__, "joblib": joblib.__version__},
        "target": "duree_reelle_min",
        "feature_columns": FEATURE_COLUMNS,
        "alert_labels": ["fluide (<5 min)", "ralentissements (5-15 min)", "retard (>15 min)"],
        "confusion_matrix_axes": "rows=actual, columns=predicted",
        "selected_model": selected,
        "selection_metric": "validation MAE",
        "validation": validation_metrics,
        "test": test_metrics,
    }
    output = PROJECT_ROOT / "models"
    output.mkdir(exist_ok=True)
    joblib.dump(models[selected], output / "modele_retard_maroc.pkl")
    joblib.dump(FEATURE_COLUMNS, output / "colonnes_modele.pkl")
    (output / "evaluation_modele.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return report


if __name__ == "__main__":
    entrainer_modele()
