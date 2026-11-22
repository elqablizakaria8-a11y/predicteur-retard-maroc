from pathlib import Path
import unittest

import joblib
import numpy as np
import pandas as pd

from src.model_features import WEATHER, prepare_features


class SavedModelWeatherTests(unittest.TestCase):
    def test_worsening_weather_does_not_reduce_duration(self):
        root = Path(__file__).resolve().parents[1]
        model = joblib.load(root / 'models/modele_retard_maroc.pkl')
        # Includes the actual counterexample found during API acceptance checks.
        for distance, reference, urban in [(89.1371, 67.865, 0), (10, 20, 1), (3.0693, 4.2683333333, 1)]:
            for peak in (0, 1):
                rows = pd.DataFrame([dict(distance_km=distance, duree_theorique_min=reference,
                    heure_depart=8 if peak else 15, jour_semaine=0, est_weekend=0,
                    est_heure_pointe=peak, est_intra_urbain=urban, meteo=weather) for weather in WEATHER])
                values = model.predict(prepare_features(rows))
                with self.subTest(distance=distance, peak=peak):
                    self.assertTrue(np.isfinite(values).all())
                    self.assertTrue((values > 0).all())
                    self.assertTrue((np.diff(values) >= -1e-8).all(), values)
