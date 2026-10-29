from pathlib import Path
import os
import sys


def data_home() -> Path:
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'PoemChant Studio'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'PoemChant Studio'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'poemchant-studio'
