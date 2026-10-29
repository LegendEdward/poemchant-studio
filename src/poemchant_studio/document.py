"""Editable annotation envelope around the immutable original score and edits."""
import copy
from datetime import datetime, timezone
import json
from .legacy.contract import identity, validate_project
from .phonology import PINYIN, readings

SCHEMA = 'PoemChantStudio1.0'
FIELDS = {'line', 'position', 'character', 'pinyin', 'modern_tone', 'historical_tone',
          'rhyme_group', 'caesura_after', 'note', 'origin'}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def annotations_for(project):
    values = []
    for li, line in enumerate(project['model_score']['lines'], 1):
        for char, lexical in zip(line['characters'], readings(line['text'])):
            p = char['phonology']
            modern = p['selected_modern_tone']
            candidates = [v for v in p['pinyin_candidates'] if modern and v[-1:] == modern]
            selected = candidates[0] if len(candidates) == 1 else (lexical['pinyin'] if modern else None)
            if selected and modern and selected[-1] != modern:
                selected = None
            values.append({'line': li, 'position': char['position'], 'character': char['character'],
                           'pinyin': selected, 'modern_tone': modern,
                           'historical_tone': p['selected_historical'],
                           'rhyme_group': lexical['rhyme_candidates'][0]['group'] if len(lexical['rhyme_candidates']) == 1 else '',
                           'caesura_after': char['position'] in (2, 4) and char['position'] < len(line['text']),
                           'note': '', 'origin': 'automatic_candidate'})
    return values


def signature(doc):
    return identity({k: v for k, v in doc.items() if k != 'document_id'})


def make_document(project, annotations=None, note='', created_at=None):
    doc = {'schema': SCHEMA, 'app_version': '2.0.0', 'document_id': '',
           'created_at': created_at or stamp(), 'updated_at': stamp(),
           'score_project': copy.deepcopy(project),
           'annotations': copy.deepcopy(annotations if annotations is not None else annotations_for(project)),
           'note': note, 'review_status': 'candidate_not_independently_reviewed'}
    doc['document_id'] = signature(doc)
    validate_document(doc)
    return doc


def validate_document(doc):
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        raise ValueError('不是本应用支持的工程文件。')
    expected = {'schema', 'app_version', 'document_id', 'created_at', 'updated_at',
                'score_project', 'annotations', 'note', 'review_status'}
    if set(doc) != expected or doc['review_status'] != 'candidate_not_independently_reviewed':
        raise ValueError('工程版本或审核状态不正确。')
    if not isinstance(doc['note'], str) or len(doc['note']) > 4000:
        raise ValueError('全诗备注最多 4000 字。')
    for key in ('created_at', 'updated_at'):
        if not isinstance(doc[key], str) or len(doc[key]) > 50:
            raise ValueError('工程时间格式不正确。')
        try:
            datetime.fromisoformat(doc[key])
        except ValueError as exc:
            raise ValueError('工程时间格式不正确。') from exc
    rendered = validate_project(doc['score_project'])
    flat = [(li, c) for li, line in enumerate(rendered['lines'], 1) for c in line['characters']]
    if not isinstance(doc['annotations'], list) or len(doc['annotations']) != len(flat):
        raise ValueError('标注数量与原诗不一致。')
    for annotation, (li, char) in zip(doc['annotations'], flat):
        if not isinstance(annotation, dict) or set(annotation) != FIELDS:
            raise ValueError('逐字标注字段不完整。')
        if type(annotation['line']) is not int or type(annotation['position']) is not int or (annotation['line'], annotation['position'], annotation['character']) != (li, char['position'], char['character']):
            raise ValueError('标注位置或原字与诗句不一致。')
        if annotation['modern_tone'] not in ('1', '2', '3', '4', '5', None) or annotation['historical_tone'] not in ('平', '上', '去', '入', None):
            raise ValueError('声调标注须为规定类别或未知。')
        value = annotation['pinyin']
        if value is not None and (not isinstance(value, str) or len(value) > 24 or not PINYIN.fullmatch(value)):
            raise ValueError('拼音请使用带数字声调的格式，例如 chang2；未知请留空。')
        if value and annotation['modern_tone'] != value[-1]:
            raise ValueError('拼音末尾调号与现代调号不一致。')
        if type(annotation['caesura_after']) is not bool:
            raise ValueError('句内分节标记须为真或假。')
        for field, limit in [('rhyme_group', 120), ('note', 500)]:
            if not isinstance(annotation[field], str) or len(annotation[field]) > limit or '\x00' in annotation[field]:
                raise ValueError('韵部或逐字备注过长，或包含不支持字符。')
        if annotation['origin'] not in ('automatic_candidate', 'user_edited'):
            raise ValueError('标注来源须保留为自动候选或用户修改。')
    if doc['document_id'] != signature(doc):
        raise ValueError('工程内容校验不一致。请从应用导出完整工程，避免直接改动文件。')
    json.dumps(doc, allow_nan=False)
    return rendered


def update_document(doc, project, annotations, note):
    validate_document(doc)
    original = annotations_for(project)
    clean = copy.deepcopy(annotations)
    if isinstance(clean, list):
        for value, base in zip(clean, original):
            if isinstance(value, dict):
                value['origin'] = 'automatic_candidate' if {k: v for k, v in value.items() if k != 'origin'} == {k: v for k, v in base.items() if k != 'origin'} else 'user_edited'
    return make_document(project, clean, note, doc['created_at'])


def annotation_labels(doc):
    validate_document(doc)
    lines = doc['score_project']['poem']['lines']
    labels = {k: [['?'] * len(line) for line in lines] for k in ('historical', 'modern', 'rhyme')}
    for item in doc['annotations']:
        li, ci = item['line'] - 1, item['position'] - 1
        labels['historical'][li][ci] = item['historical_tone'] or '?'
        labels['modern'][li][ci] = item['modern_tone'] or '?'
        # A dictionary rhyme group does not imply the corpus-specific 0–3 symbol.
        raw = doc['score_project']['model_score']['lines'][li]['characters'][ci]['phonology']['raw_rhyme']
        labels['rhyme'][li][ci] = raw or '?'
    return {k: [''.join(row) for row in value] for k, value in labels.items()}
