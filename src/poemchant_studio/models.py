"""Optional JSON-only research pack. No downloaded Python is ever executed."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile
from .rules import RulesEngine

MAX_PACK_BYTES = 16 * 1024 * 1024
RESEARCH_SOURCE_HASH = 'c4cee71d4fcfed830ff2babab148c6ae429df73d3af9728a8d85bad14fc52d44'


def check_pack(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / 'release_manifest.json').read_text(encoding='utf-8'))
    files = manifest.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 200:
        raise ValueError('模型包清单不完整。')
    for name, expected in files.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise ValueError('模型包清单格式不正确。')
        path = folder / name
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or not path.resolve().is_relative_to(folder) or path.is_symlink():
            raise ValueError('模型包包含越界路径。')
        if path.stat().st_size > MAX_PACK_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('模型文件校验失败：' + name)
    bundle = json.loads((folder / 'bundle.json').read_text(encoding='utf-8'))
    if bundle.get('files', {}).get('source/prosody_models.py') != RESEARCH_SOURCE_HASH:
        raise ValueError('该模型使用了不兼容的预测实现。只支持 prosody_v1 JSON 模型。')
    from .legacy.engine import Engine
    return Engine(folder)


class ModelManager:
    def __init__(self, home, model_dir=None):
        self.home = Path(home)
        self.rules = RulesEngine()
        self.research = None
        self.problem = None
        folder = Path(model_dir) if model_dir else self.home / 'model_packs' / 'prosody_v1'
        if folder.is_dir():
            try:
                self.research = check_pack(folder)
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                self.problem = '本地研究模型未加载：' + str(exc)

    def information(self):
        return {'default': 'research' if self.research else 'rules',
                'research_available': self.research is not None, 'problem': self.problem,
                'modes': [{'id': 'rules', 'name': '公开规则 R0', 'trained': False},
                          {'id': 'research', 'name': '本地研究模型 M2 / M3', 'trained': True,
                           'available': self.research is not None}],
                'public_release_includes_research_pack': False}

    def engine(self, mode=None):
        if mode == 'research' or (mode is None and self.research):
            if self.research is None:
                raise ValueError('请先导入本地研究模型包，或切换公开规则模式。')
            return self.research
        if mode not in (None, 'rules'):
            raise ValueError('未识别的生成模式。')
        return self.rules

    def validate_origin(self, project):
        engine = self.rules if project.get('model_id', '').startswith('public-rules-v1:') else self.engine('research')
        engine.validate_origin(project)

    def import_pack(self, data):
        if len(data) > MAX_PACK_BYTES:
            raise ValueError('模型压缩包超过 16MB。')
        parent = self.home / 'model_packs'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.import-', dir=parent))
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = [e for e in archive.infolist() if not e.is_dir()]
                if not 1 <= len(entries) <= 200 or sum(e.file_size for e in entries) > MAX_PACK_BYTES:
                    raise ValueError('模型包解压大小或文件数量超限。')
                roots = [e.filename for e in entries if e.filename.endswith('release_manifest.json')]
                if len(roots) != 1:
                    raise ValueError('模型包须有且仅有一个 release_manifest.json。')
                prefix = roots[0][:-len('release_manifest.json')]
                seen = set()
                for entry in entries:
                    name = entry.filename
                    if not name.startswith(prefix):
                        raise ValueError('模型包目录不一致。')
                    name = name[len(prefix):]
                    path = PurePosixPath(name)
                    mode = entry.external_attr >> 16
                    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or stat.S_ISLNK(mode) or name in seen:
                        raise ValueError('模型包包含重复、不安全路径或符号链接。')
                    if path.suffix not in ('.json', '.py'):
                        raise ValueError('只接受 JSON 模型和用于核对的源文件；不接受程序或录音。')
                    seen.add(name)
                    target = temporary / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(entry))
            check_pack(temporary)
            destination = parent / 'prosody_v1'
            if destination.exists():
                old_manifest = (destination / 'release_manifest.json').read_bytes()
                if old_manifest != (temporary / 'release_manifest.json').read_bytes():
                    raise ValueError('已有不同模型，请先备份本地模型目录。当前文件没有被覆盖。')
                check_pack(destination)
                shutil.rmtree(temporary)
            else:
                temporary.rename(destination)
            self.research = check_pack(destination)
            self.problem = None
            return self.information()
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
