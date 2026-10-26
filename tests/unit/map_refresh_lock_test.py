import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import web_config


class MapRefreshLockTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lock_path = Path(self.temp_dir.name) / "map-refresh.lock"
        self.patches = (
            patch.object(web_config, "_MAPA_REFRESH_LOCK_FILE", self.lock_path),
            patch.object(web_config, "_MAPA_REFRESH_LOCK_STALE_SECONDS", 30),
        )
        for active_patch in self.patches:
            active_patch.start()
        web_config._mapa_cache_refresh_em_andamento = False
        web_config._mapa_cache_refresh_token = None

    def tearDown(self):
        web_config._mapa_cache_refresh_em_andamento = False
        web_config._mapa_cache_refresh_token = None
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temp_dir.cleanup()

    def test_only_one_refresh_can_hold_the_lock(self):
        self.assertTrue(web_config._mapa_marcar_refresh_iniciado())
        self.assertTrue(self.lock_path.exists())
        self.assertFalse(web_config._mapa_marcar_refresh_iniciado())

        web_config._mapa_marcar_refresh_finalizado()

        self.assertFalse(self.lock_path.exists())
        self.assertFalse(web_config._mapa_refresh_esta_em_andamento())

    def test_stale_lock_is_replaced(self):
        self.lock_path.write_text("abandoned", encoding="ascii")
        stale_time = time.time() - 60
        os.utime(self.lock_path, (stale_time, stale_time))

        self.assertTrue(web_config._mapa_marcar_refresh_iniciado())
        self.assertNotEqual(self.lock_path.read_text(encoding="ascii"), "abandoned")

        web_config._mapa_marcar_refresh_finalizado()


if __name__ == "__main__":
    unittest.main()
