"""Annotated exports and atomic, immutable revision folders."""
import csv
import hashlib
import html
import io
import json
import math
from pathlib import Path
import shutil
import tempfile
import zipfile
from .document import validate_document
from .legacy.contract import canonical_value
from .legacy.exports import to_midi, to_musicxml, to_wav

FILES = {'project': 'project.poemchant.json', 'annotations': 'annotations.json',
         'csv': 'annotations.csv', 'svg': 'score.svg', 'musicxml': 'score.musicxml',
         'midi': 'score.mid', 'audio': 'preview.wav', 'legacy': 'score.project.json',
         'readme': 'README.txt', 'manifest': 'manifest.json', 'zip': 'score-bundle.zip'}


def json_bytes(value):
    return (json.dumps(canonical_value(value), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def safe_cell(value):
    text = str(value) if value is not None else ''
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


def annotation_csv(doc):
    rendered = validate_document(doc)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['line', 'position', 'character', 'pinyin', 'modern_tone', 'historical_tone',
                     'pingze_candidate', 'rhyme_group', 'caesura_after', 'duration_ms',
                     'line_start_s', 'line_end_s', 'note', 'annotation_origin', 'generation_mode'])
    chars = [c for line in rendered['lines'] for c in line['characters']]
    for a, c in zip(doc['annotations'], chars):
        pingze = '平' if a['historical_tone'] == '平' else '仄' if a['historical_tone'] else '?'
        writer.writerow([a['line'], a['position'], a['character'], a['pinyin'] or '',
                         a['modern_tone'] or '?', a['historical_tone'] or '?', pingze,
                         safe_cell(a['rhyme_group']), int(a['caesura_after']),
                         round((c['end_s'] - c['start_s']) * 1000, 6), round(c['start_s'], 9),
                         round(c['end_s'], 9), safe_cell(a['note']), a['origin'],
                         doc['score_project']['model_id']])
    # UTF-8 BOM makes Chinese column contents readable in desktop spreadsheet apps.
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def annotated_svg(doc):
    rendered = validate_document(doc)
    project = doc['score_project']
    escape = html.escape
    width, row_height = 1400, 258
    title_chunks = [project['poem']['title'][i:i+34] for i in range(0, len(project['poem']['title']), 34)]
    author_chunks = [project['poem']['author'][i:i+65] for i in range(0, len(project['poem']['author']), 65)]
    header = 142 + len(title_chunks) * 32 + len(author_chunks) * 18
    height = header + len(rendered['lines']) * row_height + 80
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="#faf8f2"/>',
           '<style>text{font-family:"Songti SC","Noto Serif CJK SC",serif;fill:#203c38}.meta{font-family:system-ui,sans-serif;font-size:15px;fill:#63736b}.small{font-family:system-ui,sans-serif;font-size:13px;fill:#6c786f}</style>']
    y = 45
    for chunk in title_chunks:
        out.append(f'<text x="66" y="{y}" font-size="30">{escape(chunk)}</text>')
        y += 32
    for chunk in author_chunks:
        out.append(f'<text x="68" y="{y}" class="meta">{escape(chunk)}</text>')
        y += 18
    mode = '本地研究模型' if project['model_id'].startswith('prosody_v1:') else '公开规则 R0（未训练）'
    out.append(f'<text x="68" y="{y+18}" class="meta">候选吟诵曲线谱 · {mode} · {rendered["duration_s"]:.2f} 秒 · 器乐示意</text>')
    out.append(f'<text x="68" y="{y+42}" class="small">字下方依次为：拼音 / 历史调类 / 时长 / 韵部候选。橙色表示待核对或用户修改；短竖线表示编辑性分节。</text>')
    pitches = [69 + 12 * math.log2(h/440) for line in rendered['lines'] for c in line['characters'] for run in c['pitch_runs'] for _, h in run['points']]
    low, high = min(pitches, default=58)-1, max(pitches, default=66)+1
    if high-low < 8:
        low, high = (low+high)/2-4, (low+high)/2+4
    ann = {(a['line'], a['position']): a for a in doc['annotations']}
    for li, line in enumerate(rendered['lines'], 1):
        top = header + (li-1)*row_height
        scale = 1252 / line['duration_s']
        yp = lambda hz: top + 94 - (69 + 12*math.log2(hz/440)-low)/(high-low)*80
        for f in (0, .5, 1):
            out.append(f'<path d="M72 {top+14+f*80:.2f} H1324" stroke="#dce2da" fill="none"/>')
        desired = [72+(c['start_s']+c['end_s'])/2*scale for c in line['characters']]
        labels = []
        for x in desired:
            labels.append(max(x, labels[-1]+143 if labels else 143))
        if labels[-1] > 1250:
            labels[-1] = 1250
            for i in range(len(labels)-2, -1, -1):
                labels[i] = min(labels[i], labels[i+1]-143)
        for ci, c in enumerate(line['characters']):
            a = ann[(li, c['position'])]
            x0, x1 = 72+c['start_s']*scale, 72+c['end_s']*scale
            x, mid = labels[ci], (x0+x1)/2
            uncertain = c['model_uncertainty']['input']['ambiguous_or_unknown']
            color = '#b66b35' if c['edited'] or a['origin'] == 'user_edited' or uncertain else '#267169'
            out.append(f'<path d="M{x0:.4f} {top+5} v98" stroke="#d1d9d0" stroke-dasharray="3 4"/>')
            if not c['pitch_runs']:
                out.append(f'<text x="{mid:.3f}" y="{top+58}" class="small" text-anchor="middle">音高未知</text>')
            for run in c['pitch_runs']:
                points = ' '.join(f'{72+t*scale:.4f},{yp(h):.4f}' for t, h in run['points'])
                if len(run['points']) == 1:
                    t, h = run['points'][0]
                    out.append(f'<circle cx="{72+t*scale:.4f}" cy="{yp(h):.4f}" r="3" fill="{color}"/>')
                else:
                    out.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3"/>')
            out.append(f'<path d="M{mid:.3f} {top+105} L{x:.3f} {top+121}" stroke="#c7d0c5"/>')
            out.append(f'<text data-character="{escape(c["character"], quote=True)}" x="{x:.3f}" y="{top+154}" font-size="31" text-anchor="middle">{escape(c["character"])}</text>')
            label = f'{a["pinyin"] or "?"} · {a["historical_tone"] or "?"}'
            out.append(f'<text x="{x:.3f}" y="{top+179}" class="meta" text-anchor="middle">{escape(label)}</text>')
            duration = 1000*(c['end_s']-c['start_s'])
            out.append(f'<text x="{x:.3f}" y="{top+200}" class="small" text-anchor="middle">{duration:.0f} ms</text>')
            rhyme = a['rhyme_group'].split('/')[-1]
            rhyme = rhyme[:11] + ('…' if len(rhyme) > 11 else '')
            out.append(f'<text x="{x:.3f}" y="{top+222}" class="small" text-anchor="middle">{escape(rhyme or "韵部待核对")}</text>')
            if a['caesura_after']:
                out.append(f'<path d="M{x1:.3f} {top+128} v26" stroke="#b66b35" stroke-width="2"/>')
        out.append(f'<text x="1324" y="{top+247}" class="small" text-anchor="end">第 {li} 句 · {line["duration_s"]:.3f} 秒 · 横轴为本句时间</text>')
    out.append(f'<text x="68" y="{height-47}" class="small">未经独立吟诵审校；不代表历史吟调或特定人物风格。音高空缺保持留空；句间试听间隔不是测量停顿。</text>')
    out.append(f'<text x="68" y="{height-24}" class="small">PoemChant Studio 2.0.0 · {escape(project["model_id"])} · 工程 {doc["document_id"][:16]}</text></svg>')
    return '\n'.join(out).encode('utf-8')


def payloads_for(doc):
    rendered = validate_document(doc)
    project = doc['score_project']
    midi, midi_info = to_midi(project)
    xml, xml_info = to_musicxml(project)
    wav, wav_info = to_wav(project)
    from xml.etree import ElementTree as ET
    root = ET.fromstring(xml)
    creator = root.find('./identification/creator')
    creator.text = 'PoemChant Studio; ' + project['model_id']
    xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    text = ('PoemChant Studio 候选吟诵谱\n\n'
            'project.poemchant.json：完整可编辑工程，含标注、生成原稿、修改记录。\n'
            'annotations.csv / annotations.json：逐字标注。CSV 对公式起始字符增加保护前缀，JSON 保留原值。\n'
            'score.svg：含读音、调类、字长、韵部候选的连续曲线谱。\n'
            'score.musicxml：自由时间的代表音近似。score.mid：连续弯音器乐谱。\n'
            'preview.wav：器乐示意，不是人声吟诵。\n'
            '保存标注不会静默重新推理；按标注重生成须显式操作，会建立新稿。\n'
            '分节与句间留白是编辑/试听控制，不是录音真值。用户编辑不自动等于专家审定。\n'
            '规则模式未训练、未校准；本地研究模式为既有弱参考模型，不能证明历史旋律真实性。\n'
            f'本工程模式：{project["model_id"]}\n')
    payloads = {FILES['project']: json_bytes(doc), FILES['annotations']: json_bytes(doc['annotations']),
                FILES['csv']: annotation_csv(doc), FILES['svg']: annotated_svg(doc),
                FILES['musicxml']: xml, FILES['midi']: midi, FILES['audio']: wav,
                FILES['legacy']: json_bytes(project), FILES['readme']: text.encode('utf-8')}
    manifest = {'version': '2.0.0', 'document_id': doc['document_id'],
                'title': project['poem']['title'], 'author': project['poem']['author'],
                'model_id': project['model_id'], 'duration_s': rendered['duration_s'],
                'updated_at': doc['updated_at'], 'human_reviewed': False,
                'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in payloads.items()},
                'export_diagnostics': {'midi': midi_info, 'musicxml': xml_info, 'audio': wav_info}}
    payloads[FILES['manifest']] = json_bytes(manifest)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    payloads[FILES['zip']] = buffer.getvalue()
    return payloads, manifest


def write_document(doc, destination):
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError('该位置已有文件，未覆盖；请选择新的输出文件夹。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.saving-', dir=destination.parent))
    try:
        payloads, manifest = payloads_for(doc)
        for name, data in payloads.items():
            (temporary / name).write_bytes(data)
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest
