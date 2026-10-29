"""Loopback application service; no external network calls or telemetry."""
import base64
import binascii
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import secrets
import signal
import threading
from urllib.parse import quote, unquote, urlsplit
import webbrowser
import zipfile
from . import __version__
from .document import annotation_labels, make_document, update_document, validate_document
from .exports import FILES, write_document
from .legacy.contract import edit_project
from .models import ModelManager
from .paths import data_home

WEB = Path(__file__).parent / 'web'
ID = re.compile(r'[0-9a-f]{16}')


class Store:
    def __init__(self, home, model_dir=None):
        self.home = Path(home).expanduser().resolve()
        self.projects = self.home / 'projects'
        self.projects.mkdir(parents=True, exist_ok=True)
        self.models = ModelManager(self.home, model_dir)
        self.lock = threading.Lock()

    def path(self, identifier):
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise ValueError('工程编号不正确。')
        folder = self.projects / identifier
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.projects):
            raise ValueError('工程路径不正确。')
        return folder

    def load(self, identifier):
        doc = json.loads((self.path(identifier) / FILES['project']).read_text(encoding='utf-8'))
        validate_document(doc)
        self.models.validate_origin(doc['score_project'])
        return doc

    def save(self, doc):
        identifier = secrets.token_hex(8)
        manifest = write_document(doc, self.path(identifier))
        return {'run_id': identifier, 'document': doc, 'duration_s': manifest['duration_s'],
                'rendered': validate_document(doc),
                'files': {key: f'/runs/{identifier}/' + quote(name) for key, name in FILES.items()}}

    def recent(self):
        candidates = [p for p in self.projects.iterdir() if ID.fullmatch(p.name) and p.is_dir() and not p.is_symlink()]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        result = []
        for folder in candidates[:100]:
            try:
                info = json.loads((folder / FILES['manifest']).read_text(encoding='utf-8'))
                result.append({'run_id': folder.name, **{k: info[k] for k in ('title', 'author', 'model_id', 'updated_at', 'duration_s')}})
            except (OSError, ValueError, KeyError):
                continue
        return result


def create_server(port=0, home=None, model_dir=None):
    if type(port) is not int or not 0 <= port <= 65535 or 0 < port < 1024:
        raise ValueError('端口须为 0 或 1024–65535。')
    store = Store(home or data_home(), model_dir)
    token = secrets.token_hex(32)

    class Handler(BaseHTTPRequestHandler):
        def host_ok(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def authenticated(self):
            return self.host_ok() and secrets.compare_digest(self.headers.get('X-PoemChant-Token', ''), token)

        def send(self, data, kind='application/json; charset=utf-8', status=200, download=None):
            total, first, last = len(data), 0, len(data)-1
            header = self.headers.get('Range')
            if header and status == 200:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
                if not match or not any(match.groups()):
                    self.send_error(416)
                    return
                a, b = match.groups()
                if a:
                    first, last = int(a), min(last, int(b)) if b else last
                else:
                    first = max(0, total-int(b))
                if first > last or first >= total:
                    self.send_error(416)
                    return
                data, status = data[first:last+1], 206
            self.send_response(status)
            for key, value in [('Content-Type', kind), ('Content-Length', str(len(data))),
                               ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                               ('Referrer-Policy', 'no-referrer'), ('Accept-Ranges', 'bytes'),
                               ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")]:
                self.send_header(key, value)
            if status == 206:
                self.send_header('Content-Range', f'bytes {first}-{last}/{total}')
            if download:
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(download))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def response(self, value, status=200):
            self.send(json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), status=status)

        def do_GET(self):
            if not self.host_ok():
                self.response({'error': '仅接受本机访问。'}, 403)
                return
            url = urlsplit(self.path)
            path = unquote(url.path)
            if path == '/':
                self.send((WEB / 'index.html').read_text(encoding='utf-8').replace('__TOKEN__', token).encode(), 'text/html; charset=utf-8')
                return
            if path in ('/app.js', '/style.css'):
                self.send((WEB / path[1:]).read_bytes(), 'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                return
            if path == '/api/health':
                self.response({'ready': True, 'version': __version__})
                return
            if path.startswith('/api/'):
                if not self.authenticated():
                    self.response({'error': '请刷新应用后重试。'}, 403)
                    return
                if path == '/api/state':
                    self.response({'version': __version__, 'models': store.models.information(), 'recent': store.recent()})
                    return
            match = re.fullmatch(r'/runs/([0-9a-f]{16})/([^/]+)', path)
            if match and match[2] in FILES.values():
                file = store.path(match[1]) / match[2]
                if not file.is_file() or file.is_symlink():
                    self.response({'error': '文件不存在。'}, 404)
                    return
                kinds = {'.wav': 'audio/wav', '.svg': 'image/svg+xml', '.json': 'application/json',
                         '.csv': 'text/csv; charset=utf-8', '.mid': 'audio/midi', '.musicxml': 'application/vnd.recordare.musicxml+xml',
                         '.zip': 'application/zip', '.txt': 'text/plain; charset=utf-8'}
                self.send(file.read_bytes(), kinds.get(file.suffix, 'application/octet-stream'), download=file.name if url.query == 'download=1' else None)
                return
            self.response({'error': '没有这个页面。'}, 404)

        def do_POST(self):
            origin = self.headers.get('Origin')
            allowed_origins = (None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}')
            if not self.authenticated() or origin not in allowed_origins:
                self.response({'error': '请求校验失败，请刷新应用。'}, 403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 24 * 1024 * 1024:
                    raise ValueError('输入为空或超过 24MB。')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('请求格式不正确。')
                route = urlsplit(self.path).path
                with store.lock:
                    if route == '/api/generate':
                        allowed = {'text', 'title', 'author', 'mode', 'model', 'speed_ms', 'base_hz', 'line_gap_s'}
                        if set(body) - allowed:
                            raise ValueError('生成设置包含不支持字段。')
                        mode = body.pop('mode', None)
                        project = store.models.engine(mode).generate(**body)
                        result = store.save(make_document(project))
                    elif route == '/api/open':
                        if set(body) != {'run_id'}:
                            raise ValueError('打开工程格式不正确。')
                        doc = store.load(body['run_id'])
                        identifier = body['run_id']
                        result = {'run_id': identifier, 'document': doc, 'rendered': validate_document(doc),
                                  'duration_s': validate_document(doc)['duration_s'],
                                  'files': {key: f'/runs/{identifier}/' + quote(name) for key, name in FILES.items()}}
                    elif route == '/api/import':
                        if set(body) != {'document'}:
                            raise ValueError('导入工程格式不正确。')
                        doc = body['document']
                        if not isinstance(doc, dict):
                            raise ValueError('工程内容须为 JSON 对象。')
                        if doc.get('schema') == 'PoemChantProject1.0':
                            doc = make_document(doc)
                        validate_document(doc)
                        store.models.validate_origin(doc['score_project'])
                        result = store.save(doc)
                    elif route in ('/api/save', '/api/reinfer'):
                        if set(body) != {'run_id', 'edits', 'annotations', 'note', 'line_gap_s'}:
                            raise ValueError('保存内容不完整。')
                        doc = store.load(body['run_id'])
                        project = edit_project(doc['score_project'], body['edits'], body['line_gap_s'])
                        doc = update_document(doc, project, body['annotations'], body['note'])
                        if route == '/api/reinfer':
                            old = doc['score_project']
                            mode = 'research' if old['model_id'].startswith('prosody_v1:') else 'rules'
                            p = old['model_score']['provenance']
                            project = store.models.engine(mode).generate(old['input']['original_text'],
                                title=old['poem']['title'], author=old['poem']['author'], poem_id=old['poem_id'],
                                labels=annotation_labels(doc), model=old['input']['requested_model'],
                                speed_ms=p['speed_nonfinal_median_ms'], base_hz=p['register_control_Hz'],
                                line_gap_s=old['playback']['line_gap_s'], source=old['poem']['source'])
                            # Explicit re-inference replaces previous acoustic edits, retaining annotations.
                            doc = update_document(doc, project, doc['annotations'], doc['note'])
                        result = store.save(doc)
                    elif route == '/api/model/import':
                        if set(body) != {'base64'} or not isinstance(body['base64'], str):
                            raise ValueError('模型包格式不正确。')
                        result = {'models': store.models.import_pack(base64.b64decode(body['base64'], validate=True))}
                    else:
                        self.response({'error': '不支持的操作。'}, 404)
                        return
                self.response(result)
            except (ValueError, TypeError, KeyError, OSError, RuntimeError, binascii.Error, zipfile.BadZipFile) as exc:
                self.response({'error': str(exc) or '数据格式不正确，未保存。'}, 400)

        def log_message(self, fmt, *args):
            # Do not log poems, annotations, tokens, or full file-system paths.
            print(json.dumps({'http': fmt % args}, ensure_ascii=False), flush=True)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.store = store
    return server


def serve(port=0, home=None, model_dir=None, open_browser=True, ready_file=None):
    server = create_server(port, home, model_dir)
    url = f'http://127.0.0.1:{server.server_port}/'
    if ready_file:
        ready = Path(ready_file)
        ready.parent.mkdir(parents=True, exist_ok=True)
        ready.write_text(json.dumps({'url': url, 'version': __version__}), encoding='utf-8')
        ready.chmod(0o600)
    print(json.dumps({'status': 'ready', 'url': url}, ensure_ascii=False), flush=True)
    if open_browser:
        webbrowser.open(url)
    def terminate(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if ready_file:
            Path(ready_file).unlink(missing_ok=True)
