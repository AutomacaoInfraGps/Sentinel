"""Cria a estrutura local sem sobrescrever arquivos ja preenchidos."""

import shutil
from .settings import DATA_ROOT, PACKAGE_ROOT


def initialize(root=DATA_ROOT):
    root.mkdir(parents=True, exist_ok=True)
    for name in ('config', 'credentials', 'modelos', 'dados/evidencias', 'dados/execucoes', 'runtime'):
        (root / name).mkdir(parents=True, exist_ok=True)
    for source in (PACKAGE_ROOT / 'config').glob('*.example.json'):
        directory = 'credentials' if source.name == 'credentials.example.json' else 'config'
        target = root / directory / source.name.replace('.example', '')
        if not target.exists():
            shutil.copyfile(source, target)


if __name__ == '__main__':
    initialize()
    print('Estrutura criada em instance/access_review. Preencha os arquivos e forneca os modelos DOCX.')
