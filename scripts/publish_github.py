"""Publish the allowlisted application to the authenticated personal GitHub account."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from make_release import allowed_sources

ROOT = Path(__file__).resolve().parents[1]


def run(command, capture=False, check=True):
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=capture, check=check)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gh', default=shutil.which('gh'))
    parser.add_argument('--name', default='poemchant-studio')
    args = parser.parse_args()
    if not args.gh:
        raise SystemExit('Install GitHub CLI from https://cli.github.com and run gh auth login first.')
    gh = str(Path(args.gh).resolve())
    if run([gh,'auth','status','--hostname','github.com'],capture=True,check=False).returncode:
        raise SystemExit('GitHub authentication is required. Run gh auth login; never paste tokens into public issues.')
    user = json.loads(run([gh,'api','user'],capture=True).stdout)
    owner = user['login']
    if not all(c.isalnum() or c in '-_.' for c in args.name) or not args.name:
        raise ValueError('Invalid repository name')
    repo = owner+'/'+args.name
    release = json.loads((ROOT/'dist/release-manifest.json').read_text())
    artifacts = []
    for name, info in release['artifacts'].items():
        path = ROOT/'dist'/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:
            raise ValueError('Release asset changed: '+name)
        artifacts.append(str(path))
    for name in ['release-manifest.json','SHA256SUMS.txt']:
        artifacts.append(str(ROOT/'dist'/name))
    sources = allowed_sources()
    if not (ROOT/'.git').is_dir():
        run(['git','init','-b','main'])
    run(['git','config','user.name','Edward Yiyang Zhou'])
    run(['git','config','user.email',str(user['id'])+'+'+owner+'@users.noreply.github.com'])
    # Stage only reviewed release inputs, never a broad `git add .`.
    run(['git','add','--']+[str(p.relative_to(ROOT)) for p in sources])
    tracked = run(['git','ls-files','-z'],capture=True).stdout.split('\0')
    allowed = {p.relative_to(ROOT).as_posix() for p in sources}
    if {p for p in tracked if p}-allowed:
        raise ValueError('Unexpected tracked files; stop before publishing')
    staged = run(['git','diff','--cached','--quiet'],check=False).returncode
    if staged:
        run(['git','commit','-m','Release standalone PoemChant Studio 2.0.0'])
    origin = run(['git','remote','get-url','origin'],capture=True,check=False)
    expected = 'https://github.com/'+repo+'.git'
    if origin.returncode==0 and origin.stdout.strip()!=expected:
        raise ValueError('Existing remote is different; stop rather than replacing it')
    exists = run([gh,'repo','view',repo,'--json','nameWithOwner'],capture=True,check=False).returncode==0
    if exists and origin.returncode!=0:
        raise ValueError('Repository name already exists; choose a new name explicitly')
    if not exists:
        run([gh,'repo','create',repo,'--public','--description',
             'Offline editable candidate chant scores and annotations for classical Chinese poetry.',
             '--disable-wiki','--source',str(ROOT),'--remote','origin'])
    # Scope authentication to this invocation; do not change global git settings.
    helper = '!'+shlex_quote(gh)+' auth git-credential'
    git = ['git','-c','credential.helper=','-c','credential.helper='+helper]
    run(git+['push','--set-upstream','origin','main'])
    if run(['git','rev-parse','--verify','refs/tags/v2.0.0'],capture=True,check=False).returncode:
        run(['git','tag','v2.0.0'])
    run(git+['push','origin','v2.0.0'])
    if run([gh,'release','view','v2.0.0','--repo',repo],capture=True,check=False).returncode==0:
        raise ValueError('Release already exists; inspect it rather than overwriting assets')
    run([gh,'release','create','v2.0.0',*artifacts,'--repo',repo,'--verify-tag',
         '--title','PoemChant Studio 2.0.0 — standalone chant score editor',
         '--notes-file',str(ROOT/'docs/RELEASE_NOTES.md')])
    remote = json.loads(run([gh,'repo','view',repo,'--json','url,isPrivate,defaultBranchRef'],capture=True).stdout)
    info = json.loads(run([gh,'release','view','v2.0.0','--repo',repo,'--json','url,assets,isDraft'],capture=True).stdout)
    if remote['isPrivate'] or info['isDraft'] or len(info['assets'])!=len(artifacts):
        raise ValueError('Remote publication did not match the intended state')
    (ROOT/'build').mkdir(exist_ok=True)
    result = {'repository':remote,'release':info,'commit':run(['git','rev-parse','HEAD'],capture=True).stdout.strip()}
    (ROOT/'build/publish-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'repository_url':remote['url'],'release_url':info['url']},ensure_ascii=False))


def shlex_quote(value):
    import shlex
    return shlex.quote(value)


if __name__=='__main__':
    main()
