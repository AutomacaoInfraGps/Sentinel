import importlib
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_REQUIREMENTS = PROJECT_ROOT / "requirements-sentinel.txt"
REQUIRED_IMPORTS = {
    "bs4": "beautifulsoup4",
    "filelock": "filelock",
}


def _declared_runtime_packages():
    packages = set()
    for raw_line in RUNTIME_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        package = line.split("==", 1)[0].strip().lower().replace("_", "-")
        packages.add(package)
    return packages


class RuntimeDependenciesTests(unittest.TestCase):
    def test_new_feature_dependencies_are_declared_for_rigel(self):
        declared = _declared_runtime_packages()
        self.assertTrue(set(REQUIRED_IMPORTS.values()).issubset(declared))

    def test_new_feature_dependencies_are_importable(self):
        for module_name in REQUIRED_IMPORTS:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
