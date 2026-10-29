"""Build a self-contained arm64 macOS app; no research model pack is bundled."""
from pathlib import Path
import argparse
import plistlib
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('The native app must be built on macOS. The Python source runs elsewhere.')
    import PyInstaller.__main__
    package = ROOT / 'src' / 'poemchant_studio'
    backend_dist = ROOT / 'build' / 'backend-dist'
    PyInstaller.__main__.run([
        '--noconfirm', '--clean', '--name', 'PoemChantBackend', '--onedir',
        '--distpath', str(backend_dist), '--workpath', str(ROOT / 'build' / 'freezer'),
        '--specpath', str(ROOT / 'build'), '--paths', str(ROOT / 'src'),
        '--add-data', str(package / 'web') + ':poemchant_studio/web',
        '--add-data', str(package / 'resources') + ':poemchant_studio/resources',
        '--add-data', str(package / 'legacy') + ':poemchant_studio/legacy',
        '--collect-data', 'pypinyin', '--collect-data', 'opencc',
        '--copy-metadata', 'pypinyin', '--copy-metadata', 'opencc-python-reimplemented',
        '--hidden-import', 'numpy', '--hidden-import', 'poemchant_studio.legacy.vendor.prosody_models',
        '--exclude-module', 'tkinter', '--exclude-module', 'matplotlib', '--exclude-module', 'lxml',
        '--target-architecture', 'arm64', str(ROOT / 'scripts' / 'desktop_backend.py')])
    destination = args.output_dir.resolve() / '吟谱 PoemChant Studio.app'
    if destination.exists():
        shutil.rmtree(destination)
    contents = destination / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    resources = contents / 'Resources'
    resources.mkdir()
    shutil.copytree(backend_dist / 'PoemChantBackend', resources / 'backend', symlinks=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ROOT / 'licenses', resources / 'licenses')
    shutil.copy2(ROOT / 'LICENSE', resources / 'licenses' / 'PoemChant_MIT.txt')
    info = {'CFBundleName': 'PoemChant Studio', 'CFBundleDisplayName': '吟谱',
            'CFBundleIdentifier': 'org.poemchant.studio', 'CFBundleExecutable': 'PoemChantStudio',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '2.0.0',
            'CFBundleVersion': '20000', 'LSMinimumSystemVersion': '14.0',
            'NSHighResolutionCapable': True, 'NSPrincipalClass': 'NSApplication',
            'NSHumanReadableCopyright': 'Copyright © 2026 Edward Yiyang Zhou. MIT.',
            'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True}}
    icon = ROOT / 'native' / 'PoemChant.icns'
    if icon.exists():
        shutil.copy2(icon, resources / icon.name)
        info['CFBundleIconFile'] = icon.name
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['xcrun', 'swiftc', '-O', '-target', 'arm64-apple-macosx14.0',
                    '-framework', 'AppKit', '-framework', 'WebKit',
                    str(ROOT / 'native' / 'PoemChant.swift'), '-o', str(contents / 'MacOS' / 'PoemChantStudio')], check=True)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(destination)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(destination)], check=True)
    print(destination)


if __name__ == '__main__':
    main()
