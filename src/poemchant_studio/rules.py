"""Public, untrained engineering baseline. Coefficients are explicit hypotheses."""
import hashlib
import json
import math
import statistics
from pathlib import Path
import numpy as np
from .legacy.contract import identity, number, parse_text, project_digest, validate_project
from .legacy.vendor.score_contract import from_prediction, input_uncertainty
from .phonology import readings

CONTOURS = {'1': [2, 2, 2, 2, 2], '2': [-2, -1, 0, 2, 3],
            '3': [-1, -3, -4, -2, 1], '4': [3, 2, 0, -2, -3], '5': [0, -1, -1, -1, -1]}
LENGTHS = {'平': 1.15, '上': 1.05, '去': .95, '入': .75, None: 1.0}
RULE_SPEC = {'id': 'public-rules-v1', 'contours_semitones': CONTOURS,
             'duration_weights': LENGTHS | {'unknown': 1.0}, 'caesura_factor': 1.08,
             'final_factor': 1.6, 'line_declination_semitones': .3,
             'status': 'untrained_engineering_hypotheses_not_validated_intoning_rules'}
# Stringify the None key before canonical encoding.
RULE_SPEC['duration_weights'] = {str(k): v for k, v in RULE_SPEC['duration_weights'].items()}
RULE_HASH = identity(RULE_SPEC)


class RulesEngine:
    def generate(self, text, title='未题名', author='未署名', poem_id=None, labels=None,
                 model=None, speed_ms=520., base_hz=220., line_gap_s=.65, source=None):
        lines, form = parse_text(text)
        for value in (title, author):
            if not isinstance(value, str) or len(value) > 160 or any(ord(c) < 32 for c in value):
                raise ValueError('题名或作者格式不正确。')
        if model not in (None, 'R0'):
            raise ValueError('公开规则模式只支持 R0；M0–M4 需要先导入本地研究模型。')
        speed = number(speed_ms, 150, 1200, '字长基准（毫秒）')
        register = number(base_hz, 80, 600, '音区（Hz）')
        gap = number(line_gap_s, 0, 3, '句间间隔（秒）')
        if labels is not None:
            if not isinstance(labels, dict) or set(labels) != {'historical', 'modern', 'rhyme'}:
                raise ValueError('标签字段不完整。')
            for key, allowed in [('historical', set('平上去入?')), ('modern', set('12345?')), ('rhyme', set('0123?'))]:
                values = labels[key]
                if not isinstance(values, list) or len(values) != len(lines) or any(not isinstance(v, str) or len(v) != len(line) or not set(v) <= allowed for v, line in zip(values, lines)):
                    raise ValueError('标签与诗句不匹配。')
        predicted = []
        for li, text_line in enumerate(lines):
            lexical = readings(text_line)
            weights = []
            for ci, reading in enumerate(lexical):
                historical = labels['historical'][li][ci] if labels else reading['historical_tone']
                historical = None if historical == '?' else historical
                weight = LENGTHS[historical]
                if ci == len(text_line) - 1:
                    weight *= 1.6
                elif ci in (1, 3):
                    weight *= 1.08
                weights.append(weight)
            normalizer = statistics.median(weights[:-1])
            chars, cursor = [], 0.
            for ci, reading in enumerate(lexical):
                historical = labels['historical'][li][ci] if labels else reading['historical_tone']
                modern = labels['modern'][li][ci] if labels else reading['modern_tone']
                rhyme = labels['rhyme'][li][ci] if labels else None
                duration = speed * weights[ci] / normalizer
                curve = CONTOURS.get(modern)
                points = [{'phase': j / 4, 'hz': register * 2 ** ((v - .3 * ci) / 12) if v is not None else None}
                          for j, v in enumerate(curve if curve else [None] * 5)]
                chars.append({'character': reading['character'], 'position': ci + 1,
                              'start_within_line_ms': cursor, 'duration_ms': duration,
                              'input_features': {'historical': historical, 'modern': modern, 'rhyme': rhyme},
                              'training_label_candidates': {'historical': reading['historical_candidates'],
                                                            'modern': sorted(set(v[-1] for v in reading['pinyin_candidates'])),
                                                            'pinyin': reading['pinyin_candidates']},
                              'pitch_points': points, 'candidate_model_spread_log_not_probability': None})
                cursor += duration
            predicted.append({'text': text_line, 'duration_ms': cursor, 'characters': chars})
        prediction = {'mode': 'automatic_public_rules', 'duration_model': 'R0', 'lines': predicted}
        cal = {'q_log': None, 'unbounded': True, 'nominal_coverage': None, 'unit': 'not_calibrated'}
        calibration = {'cohorts': {'primary': {'automatic_text_secondary': {'R0': cal}}}}
        score = from_prediction(prediction, calibration, {
            'mode': 'automatic_public_rules', 'duration_model': 'R0',
            'speed_nonfinal_median_ms': speed, 'register_control_Hz': register,
            'rule_spec_sha256': RULE_HASH, 'trained': False,
            'pitch': 'illustrative_modern_tone_contours_not_acoustically_measured',
            'requires_reference_audio': False, 'calibration': 'none'})
        for line in score['lines']:
            for char in line['characters']:
                char['phonology']['source'] = 'public_dictionary_candidates_unverified'
                char['pitch']['support_kind'] = 'illustrative_rule_controls_not_acoustic_evidence'
                for field in ('selected_historical', 'selected_modern_tone', 'raw_rhyme'):
                    if char['phonology'][field] == '?':
                        char['phonology'][field] = None
                char['uncertainty']['input'] = input_uncertainty(char['phonology'])
                char['uncertainty']['calibration']['target'] = 'none_untrained_rules'
        project = {'schema': 'PoemChantProject1.0', 'schema_version': '1.0',
                   'poem_id': poem_id or 'input-' + hashlib.sha256(text.encode()).hexdigest()[:16],
                   'score_id': '', 'model_id': 'public-rules-v1:R0',
                   'parameter_status': 'untrained_engineering_rules_not_learned_model',
                   'source_hashes': {'input_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                                     'model_score_sha256': identity(score), 'rule_spec_sha256': RULE_HASH},
                   'split_exposure': {'matching': 'not_applicable_public_rules_not_fitted', 'lines': [],
                                      'any_training_sentence_match': False},
                   'validation_status': 'generated_candidate_not_human_validated', 'human_reviewed': False,
                   'poem': {'title': title, 'author': author, 'form': form, 'lines': lines, 'source': source or {}},
                   'input': {'original_text': text, 'labels': labels, 'requested_model': None},
                   'playback': {'line_gap_s': gap, 'is_measured_pause': False, 'instrument': 'deterministic_harmonic_flute'},
                   'model_score': score, 'edits': [], 'runtime': {'NumPy': np.__version__}}
        project['score_id'] = project_digest(project)
        validate_project(project)
        return project

    def validate_origin(self, project):
        validate_project(project)
        if project.get('model_id') != 'public-rules-v1:R0' or project.get('parameter_status') != 'untrained_engineering_rules_not_learned_model':
            raise ValueError('规则模式来源标记不正确，不能冒充训练模型。')
        p = project['model_score']['provenance']
        regenerated = self.generate(project['input']['original_text'], title=project['poem']['title'],
                                    author=project['poem']['author'], poem_id=project['poem_id'],
                                    labels=project['input']['labels'], speed_ms=p['speed_nonfinal_median_ms'],
                                    base_hz=p['register_control_Hz'], line_gap_s=project['playback']['line_gap_s'],
                                    source=project['poem']['source'])
        if regenerated['source_hashes']['model_score_sha256'] != project['source_hashes']['model_score_sha256']:
            raise ValueError('规则原稿与当前版本不一致，不能冒充原生成结果。')
