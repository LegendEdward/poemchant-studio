import argparse
import json
from pathlib import Path
import sys
from .document import make_document, validate_document
from .exports import write_document
from .models import ModelManager
from .paths import data_home


def main():
    parser = argparse.ArgumentParser(description='吟谱 · PoemChant Studio：离线候选吟诵谱与标注')
    parser.add_argument('--version', action='version', version='PoemChant Studio 2.0.0')
    sub = parser.add_subparsers(dest='command')
    serve_parser = sub.add_parser('serve', help='打开图形界面')
    serve_parser.add_argument('--port', type=int, default=0)
    serve_parser.add_argument('--home', type=Path)
    serve_parser.add_argument('--model-dir', type=Path)
    serve_parser.add_argument('--ready-file', type=Path)
    serve_parser.add_argument('--no-browser', action='store_true')
    generate = sub.add_parser('generate', help='生成一首，输出全部谱面和标注')
    generate.add_argument('--text', required=True)
    generate.add_argument('--title', default='未题名')
    generate.add_argument('--author', default='未署名')
    generate.add_argument('--output', type=Path, required=True)
    generate.add_argument('--model-dir', type=Path)
    generate.add_argument('--mode', choices=['rules', 'research'], default='rules')
    generate.add_argument('--speed-ms', type=float, default=520)
    generate.add_argument('--base-hz', type=float, default=220)
    render = sub.add_parser('render', help='重新导出完整工程')
    render.add_argument('--project', type=Path, required=True)
    render.add_argument('--output', type=Path, required=True)
    render.add_argument('--model-dir', type=Path)
    args = parser.parse_args()
    if args.command in (None, 'serve'):
        from .server import serve
        serve(port=getattr(args, 'port', 0), home=getattr(args, 'home', None),
              model_dir=getattr(args, 'model_dir', None), open_browser=not getattr(args, 'no_browser', False),
              ready_file=getattr(args, 'ready_file', None))
        return
    manager = ModelManager(data_home(), args.model_dir)
    if args.command == 'generate':
        project = manager.engine(args.mode).generate(args.text, title=args.title, author=args.author,
                    speed_ms=args.speed_ms, base_hz=args.base_hz)
        doc = make_document(project)
    else:
        doc = json.loads(args.project.read_text(encoding='utf-8'))
        validate_document(doc)
        manager.validate_origin(doc['score_project'])
    manifest = write_document(doc, args.output)
    print(json.dumps({'status': 'saved', 'directory': str(args.output.resolve()),
                      'document_id': doc['document_id'], 'duration_s': manifest['duration_s']}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, RuntimeError) as exc:
        print('未完成：' + str(exc), file=sys.stderr)
        raise SystemExit(2)
