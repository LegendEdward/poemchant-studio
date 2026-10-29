"""Allowlist-only public archives; private research packs are never collected."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2.0.0'
FILES = ['README.md','README.en.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md',
         'SECURITY.md','pyproject.toml','.gitignore','.gitattributes','requirements-build.lock']
DIRECTORIES = ['src','native','scripts','tests','docs','licenses','examples','.github']


def allowed_sources():
    paths = [ROOT/name for name in FILES]
    for name in DIRECTORIES:
        paths.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                     and not any(part.endswith('.egg-info') for part in p.parts)
                     and p.suffix not in ('.pyc','.log'))
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or unsafe release input: '+str(path.relative_to(ROOT)))
        if any(part in ('private','model_packs','.venv','test-output') for part in path.relative_to(ROOT).parts):
            raise ValueError('Private input entered release allowlist')
    return sorted(set(paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, default=ROOT/'dist'/'吟谱 PoemChant Studio.app')
    args = parser.parse_args()
    dist = ROOT/'dist'
    dist.mkdir(exist_ok=True)
    source = dist/f'poemchant-studio-{VERSION}-source.zip'
    sources = allowed_sources()
    with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in sources:
            info = zipfile.ZipInfo(f'poemchant-studio-{VERSION}/'+path.relative_to(ROOT).as_posix(),(2026,10,29,0,0,0))
            info.external_attr = (0o100755 if path.suffix in ('.command','.sh') else 0o100644)<<16
            archive.writestr(info,path.read_bytes(),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    app = args.app.resolve()
    binary = dist/f'PoemChant-Studio-{VERSION}-macOS-arm64.zip'
    subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(app),str(binary)],check=True)
    wheels = sorted(dist.glob('poemchant_studio-*.whl'))
    artifacts = [source,binary]+wheels
    manifest = {'version':VERSION,'platform':'macOS 14+ Apple Silicon for the binary; source available',
                'signing':'ad-hoc, not Apple Developer ID or notarized',
                'research_model_included':False,'recordings_included':False,
                'public_source_files':len(sources),
                'artifacts':{p.name:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for p in artifacts}}
    (dist/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (dist/'SHA256SUMS.txt').write_text(''.join(value['sha256']+'  '+name+'\n' for name,value in manifest['artifacts'].items()),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
