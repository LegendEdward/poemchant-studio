from pathlib import Path
import importlib.metadata as metadata
import json
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ['numpy', 'pypinyin', 'opencc-python-reimplemented', 'pyinstaller', 'altgraph',
            'macholib', 'pyinstaller-hooks-contrib', 'packaging']


def main():
    output = ROOT / 'licenses'
    output.mkdir(exist_ok=True)
    records = []
    for name in PACKAGES:
        distribution = metadata.distribution(name)
        targets = []
        for relative in distribution.files or []:
            if any(part.lower().startswith(('license', 'copying', 'notice', 'authors')) for part in relative.parts) and ('.dist-info' in str(relative) or relative.name.lower().startswith(('license', 'copying', 'notice'))):
                source = distribution.locate_file(relative)
                if source.is_file() and source.suffix.lower() not in ('.pyc', '.py'):
                    filename = name + '_' + relative.name
                    if (output / filename).exists() and (output / filename).read_bytes() != source.read_bytes():
                        filename = name + '_' + '_'.join(relative.parts[-2:])
                    (output / filename).write_bytes(source.read_bytes())
                    targets.append(filename)
        if not targets:
            raise RuntimeError('Missing license file for ' + name)
        records.append({'package': name, 'version': distribution.version, 'files': sorted(set(targets))})
    python_license = Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'
    (output / 'Python_LICENSE.txt').write_bytes(python_license.read_bytes())
    (output / 'dependency-manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Collected license notices for', len(records), 'packages and Python')


if __name__ == '__main__':
    main()
