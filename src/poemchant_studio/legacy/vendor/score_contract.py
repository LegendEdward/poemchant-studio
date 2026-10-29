"""Research-only ChantScore v2 adapters and invariant checks; no corpus access."""
from __future__ import annotations

from bisect import bisect_right
import copy
import hashlib
import json
import math


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def base(kind, provenance):
    return {'schema': 'ChantScore', 'schema_version': '2.0', 'kind': kind, 'human_verified': False,
            'units': {'time': 'seconds', 'pitch': 'Hz', 'interpolation': 'linear_cents_within_each_run'},
            'provenance': provenance, 'lines': []}


def labels(historical, modern, pinyin, rhyme, candidates=None, source='release_metadata'):
    candidates = candidates or {'historical': [historical], 'modern': [modern], 'pinyin': [pinyin]}
    selected = lambda v: None if v in (None, '__unknown__') else str(v)
    return {'historical_candidates': candidates['historical'], 'modern_tone_candidates': candidates['modern'],
            'pinyin_candidates': candidates['pinyin'], 'selected_historical': selected(historical),
            'selected_modern_tone': selected(modern), 'raw_rhyme': selected(rhyme), 'source': source}


def input_uncertainty(phonology):
    return {'ambiguous_or_unknown': any(len(phonology[k]) != 1 for k in
            ('historical_candidates', 'modern_tone_candidates', 'pinyin_candidates')) or
            phonology['selected_historical'] is None or phonology['selected_modern_tone'] is None,
            'candidate_lists_are_verified_readings': False, 'rhyme_symbol_is_phonological_class': False}


def from_reference(example, tolerance, provenance):
    result = base('automatic_reference', provenance)
    line = {'text': example['text'], 'time_origin': 'recorded_clip_seconds', 'duration_s': example['duration_s'],
            'between_line_pause_s': None, 'unassigned_alignment_spans': example['unassigned_alignment_spans'], 'characters': []}
    for item in example['characters']:
        payload = copy.deepcopy(item['representations'][f'adaptive_{tolerance}'])
        finite = sum(v is not None for v in item['reference_Hz'])
        payload['support_kind'] = 'algorithm_agreement_reference'
        phonology = labels(item['historical'], item['modern_tone'], item['modern_pinyin'], item['raw_rhyme'])
        line['characters'].append({'character': item['character'], 'position': item['position'],
            'start_s': payload['start_s'], 'end_s': payload['end_s'], 'phonology': phonology,
            'boundary_scenarios': copy.deepcopy(item['boundary_policies']), 'pitch': payload,
            'uncertainty': {'input': input_uncertainty(phonology), 'measurement': {
                'source_frames': len(item['reference_Hz']), 'shared_frames': finite,
                'unavailable_frames': len(item['reference_Hz']) - finite,
                'semantics': 'shared50_algorithm_agreement_proxy_not_true_voicing_or_accuracy'},
                'model_spread': None, 'calibration': None}})
    result['lines'].append(line)
    return result


def from_prediction(prediction, calibration, provenance):
    result = base('model_prediction', provenance)
    mode = 'automatic_text_secondary' if prediction['mode'].startswith('automatic') else 'provided_annotation_conditioned'
    cal = calibration['cohorts']['primary'][mode][prediction['duration_model']]
    q = cal['q_log']; factor = math.exp(q) if not cal['unbounded'] else None
    for source in prediction['lines']:
        line = {'text': source['text'], 'time_origin': 'line_local_prediction_seconds',
                'duration_s': source['duration_ms'] / 1000, 'between_line_pause_s': None,
                'unassigned_alignment_spans': [], 'characters': []}
        for item in source['characters']:
            start = item['start_within_line_ms'] / 1000; duration = item['duration_ms'] / 1000; end = start + duration
            phonology = labels(item['input_features']['historical'], item['input_features']['modern'], None,
                item['input_features']['rhyme'], item['training_label_candidates'], 'training_only_lexicon_candidates')
            # Missing template bins split controls; their gaps are not recorded unvoicing.
            runs, current = [], []
            for point in item['pitch_points'] + [None]:
                if point is not None and point['hz'] is not None:
                    current.append([start + point['phase'] * duration, point['hz']])
                elif current:
                    runs.append({'start_s': current[0][0], 'end_s': current[-1][0],
                                 'first_frame_index': None, 'last_frame_index': None, 'points': current}); current = []
            missing, cursor = [], start
            for run in runs:
                if run['start_s'] > cursor + 1e-9:
                    missing.append([cursor, run['start_s']])
                cursor = run['end_s']
            if end > cursor + 1e-9:
                missing.append([cursor, end])
            pitch = {'start_s': start, 'end_s': end, 'grid_origin_s': None, 'grid_hop_s': None,
                'source_frame_start_index': None, 'source_frame_count': None, 'runs': runs, 'missing_spans': missing,
                'support_kind': 'template_control_support_not_recorded_voicing'}
            line['characters'].append({'character': item['character'], 'position': item['position'], 'start_s': start, 'end_s': end,
                'phonology': phonology, 'boundary_scenarios': {'predicted': {'end_s': end, 'duration_s': duration}}, 'pitch': pitch,
                'uncertainty': {'input': input_uncertainty(phonology), 'measurement': None,
                    'model_spread': {'range_log': item['candidate_model_spread_log_not_probability'], 'probability': False},
                    'calibration': {'nominal_coverage': cal['nominal_coverage'], 'unit': cal['unit'], 'q_log': q,
                        'unbounded': cal['unbounded'], 'lower_duration_s': duration / factor if factor else 0.,
                        'upper_duration_s': duration * factor if factor else None,
                        'target': 'E0_log_relative_duration', 'absolute_seconds_use_external_speed_control': True,
                        'exchangeability_verified': False}}})
        result['lines'].append(line)
    return result


def validate_semantics(score):
    # Reject NaN/infinity even if a validator accepts a Python float as JSON number.
    json.dumps(score, allow_nan=False)
    for line in score['lines']:
        if len(line['text']) != len(line['characters']):
            raise ValueError('Text and character count differ')
        previous = 0.
        for position, char in enumerate(line['characters'], 1):
            start, end, pitch = char['start_s'], char['end_s'], char['pitch']
            if char['position'] != position or char['character'] != line['text'][position-1] or not 0 <= start < end <= line['duration_s'] + 1e-8 or start < previous - 1e-8:
                raise ValueError('Invalid character order or boundary')
            if abs(pitch['start_s'] - start) > 1e-8 or abs(pitch['end_s'] - end) > 1e-8:
                raise ValueError('Pitch and character boundaries disagree')
            previous = end; previous_run = start; previous_index = -1; shared = 0
            for run in pitch['runs']:
                a, b = run['start_s'], run['end_s']
                if not start - 1e-8 <= a <= b <= end + 1e-8 or a < previous_run - 1e-8 or not run['points']:
                    raise ValueError('Overlapping or out-of-bound pitch support')
                points = run['points']
                if points[0][0] < a - 1e-8 or points[-1][0] > b + 1e-8 or any(points[i][0] >= points[i+1][0] for i in range(len(points)-1)) or any(v <= 0 for _, v in points):
                    raise ValueError('Invalid pitch controls')
                if score['kind'] == 'automatic_reference':
                    first, last = run['first_frame_index'], run['last_frame_index']
                    grid_start, count = pitch['source_frame_start_index'], pitch['source_frame_count']
                    if type(first) is not int or type(last) is not int or not grid_start <= first <= last < grid_start + count or first <= previous_index:
                        raise ValueError('Invalid integer support indices')
                    if abs(a - first * .01) > 1e-8 or not last * .01 < b <= (last + 1) * .01 + 1e-8:
                        raise ValueError('Integer frame indices and support seconds differ')
                    shared += last - first + 1; previous_index = last
                previous_run = b
            missing = pitch['missing_spans']
            all_spans = sorted([(r['start_s'], r['end_s']) for r in pitch['runs']] + [tuple(s) for s in missing])
            cursor = start
            for a, b in all_spans:
                if abs(a - cursor) > 1e-8 or b < a:
                    raise ValueError('Support and missing intervals must partition each character')
                cursor = b
            if abs(cursor - end) > 1e-8:
                raise ValueError('Support and missing intervals do not reach character end')
            uncertainty = char['uncertainty']
            if score['kind'] == 'automatic_reference':
                measurement = uncertainty['measurement']
                if shared != measurement['shared_frames'] or measurement['source_frames'] != pitch['source_frame_count'] or measurement['unavailable_frames'] != measurement['source_frames'] - shared:
                    raise ValueError('Reference support denominator changed')
                if pitch['grid_origin_s'] != 0 or pitch['grid_hop_s'] != .01:
                    raise ValueError('Reference grid changed')
            else:
                cal = uncertainty['calibration']
                if cal is None or uncertainty['measurement'] is not None or pitch['source_frame_count'] is not None:
                    raise ValueError('Prediction cannot masquerade as measured support')
                if not cal['unbounded'] and not 0 < cal['lower_duration_s'] <= end-start <= cal['upper_duration_s']:
                    raise ValueError('Prediction interval does not contain the point estimate')
    return True


def interpolate_cents(points, time):
    times = [p[0] for p in points]; upper = bisect_right(times, time)
    if upper == 0:
        return points[0][1]
    if upper == len(points):
        return points[-1][1]
    left, right = points[upper-1], points[upper]
    fraction = (time-left[0]) / (right[0]-left[0])
    return 2 ** ((1-fraction) * math.log2(left[1]) + fraction * math.log2(right[1]))


def reference_export_runs(score, example):
    if score['kind'] != 'automatic_reference' or len(score['lines']) != 1:
        raise ValueError('Reference export adapter needs exactly one measured clip')
    runs = []
    for char, source in zip(score['lines'][0]['characters'], example['characters']):
        pitch = char['pitch']; start = pitch['source_frame_start_index']; count = pitch['source_frame_count']
        recovered = [False] * count
        for run in pitch['runs']:
            indices = list(range(run['first_frame_index'], run['last_frame_index'] + 1))
            relative = [i-start for i in indices]
            for i in relative:
                recovered[i] = True
            time = [i * .01 for i in indices]
            runs.append({'start_s': run['start_s'], 'end_s': run['end_s'], 'time_s': time,
                         'Hz': [interpolate_cents(run['points'], t) for t in time],
                         'reference_Hz': [source['reference_Hz'][i] for i in relative], 'character': char['character']})
        if recovered != [v is not None for v in source['reference_Hz']]:
            raise ValueError('Serialized score changed the original reference mask')
    return runs
