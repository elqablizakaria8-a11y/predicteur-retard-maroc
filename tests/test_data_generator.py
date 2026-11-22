import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import data_generator


class GeneratorTests(unittest.TestCase):
    def test_reproducible_reference_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            shutil.copyfile(data_generator.PROJECT_ROOT / 'data/villes_maroc.json', root / 'data/villes_maroc.json')
            with patch.object(data_generator, 'PROJECT_ROOT', root), contextlib.redirect_stdout(io.StringIO()):
                first = data_generator.generer_dataset_maroc(100, seed=42)
                second = data_generator.generer_dataset_maroc(100, seed=42)
                different = data_generator.generer_dataset_maroc(100, seed=43)
            pd.testing.assert_frame_equal(first, second)
            self.assertFalse(first.equals(different))
            self.assertTrue((first.duree_theorique_min > 0).all())
            self.assertTrue((first.duree_reelle_min >= 3).all())
            # La reference doit provenir de la vitesse de base, avant perturbations.
            speed = first.distance_km / first.duree_theorique_min * 60
            self.assertTrue(speed[first.est_intra_urbain == 1].between(27.5, 42.5).all())
            self.assertTrue(speed[first.est_intra_urbain == 0].between(74.5, 105.5).all())
