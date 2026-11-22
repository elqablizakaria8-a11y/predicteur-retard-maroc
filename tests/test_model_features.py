import unittest

import pandas as pd

from src.model_features import FEATURE_COLUMNS, WEATHER, WEATHER_LEVELS, alert_categories, prepare_features


class FeatureTests(unittest.TestCase):
    def sample(self, weather):
        return dict(distance_km=10, duree_theorique_min=20, heure_depart=8,
                    jour_semaine=0, est_weekend=0, est_heure_pointe=1,
                    est_intra_urbain=1, meteo=weather)

    def test_weather_is_identical_alone_and_in_batch(self):
        batch = prepare_features(pd.DataFrame([self.sample(w) for w in WEATHER]))
        for index, weather in enumerate(WEATHER):
            single = prepare_features(pd.DataFrame([self.sample(weather)]))
            self.assertEqual(list(single.columns), FEATURE_COLUMNS)
            self.assertEqual(single.iloc[0].tolist(), batch.iloc[index].tolist())
            self.assertEqual(int(single.iloc[0]['intensite_meteo']), WEATHER_LEVELS[weather])

    def test_unsupported_weather_is_rejected(self):
        with self.assertRaises(ValueError):
            prepare_features(pd.DataFrame([self.sample('Brouillard')]))

    def test_invalid_reference_is_rejected(self):
        for value in [0, -1, float('nan'), float('inf')]:
            row = self.sample('Soleil')
            row['duree_theorique_min'] = value
            with self.assertRaises(ValueError):
                prepare_features(pd.DataFrame([row]))

    def test_alert_boundaries(self):
        self.assertEqual(alert_categories([-2, 4.99, 5, 15, 15.01]).tolist(), [0, 0, 1, 1, 2])


if __name__ == '__main__':
    unittest.main()
