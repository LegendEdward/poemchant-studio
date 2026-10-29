"""Explicit nominal predictors and training-only templates; JSON-serializable."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
import math

import numpy as np

UNKNOWN = '__unknown__'
NONPING = ('上', '去', '入')


def known(value):
    return UNKNOWN if value is None or str(value) in ('', '?', 'unknown', UNKNOWN) else str(value)


def feature_value(row, name):
    if name == 'position_cell':
        return f"{row['length']}:{row['position']}"
    if name == 'rhyme_marker':
        raw = known(row.get('rhyme'))
        return UNKNOWN if raw == UNKNOWN else '0' if raw == '0' else '1'
    return known(row.get(name))


def component_weights(rows):
    counts = Counter(r['component'] for r in rows)
    if not counts:
        raise ValueError('No training characters')
    return np.array([len(rows) / (len(counts) * counts[r['component']]) for r in rows])


def fit_encoder(rows, model, weights):
    if model not in ('M1', 'M2', 'M3'):
        raise ValueError('Nominal encoder only supports M1, M2 and M3')
    names = ['position_cell', 'order', 'count']
    if model in ('M2', 'M3'):
        names += ['historical', 'modern']
    if model == 'M3':
        names += ['rhyme_marker']
    categories = {name: sorted({feature_value(row, name) for row in rows} - {UNKNOWN}) + [UNKNOWN] for name in names}
    speakers = sorted({r['speaker'] for r in rows})
    proportions = [float(sum(w for r, w in zip(rows, weights) if r['speaker'] == speaker) / np.sum(weights)) for speaker in speakers]
    columns = [f'{name}={value}' for name, values in categories.items() for value in values]
    interactions = [f'{context}_x_{tone}' for context in ('final', 'rhyme') for tone in NONPING] if model == 'M3' else []
    columns += interactions + [f'anonymous_ID_nuisance={s}' for s in speakers]
    return {'model': model, 'categories': categories, 'speakers': speakers,
            'speaker_proportions': proportions, 'interactions': interactions, 'columns': columns,
            'forbidden_text_identity_features_present': False}


def encode(rows, encoder):
    x = np.zeros((len(rows), len(encoder['columns'])))
    offset = 0
    for name, values in encoder['categories'].items():
        lookup = {value: offset + i for i, value in enumerate(values)}
        for i, row in enumerate(rows):
            x[i, lookup.get(feature_value(row, name), lookup[UNKNOWN])] = 1
        offset += len(values)
    for interaction in encoder['interactions']:
        context, tone = interaction.split('_x_')
        for i, row in enumerate(rows):
            active = row['position'] == row['length'] if context == 'final' else feature_value(row, 'rhyme_marker') == '1'
            x[i, offset] = int(active and known(row.get('historical')) == tone)
        offset += 1
    speaker_lookup = {speaker: i for i, speaker in enumerate(encoder['speakers'])}
    proportions = np.array(encoder['speaker_proportions'])
    for i, row in enumerate(rows):
        speaker = speaker_lookup.get(row.get('speaker'))
        if speaker is not None:
            x[i, offset:] = -proportions
            x[i, offset + speaker] += 1
        # Unspecified or unknown IDs have population-mean zero contrasts.
    return x


def ridge_fit(x, y, weights, alpha):
    if alpha <= 0 or len(x) != len(y) or len(y) != len(weights) or np.any(weights <= 0):
        raise ValueError('Invalid ridge inputs')
    if not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(weights).all():
        raise ValueError('Nonfinite ridge inputs')
    total = weights.sum(); mean_x = np.sum(x * weights[:, None], axis=0) / total; mean_y = float(np.sum(y * weights) / total)
    centered = x - mean_x; gram = centered.T @ (centered * weights[:, None]); rhs = centered.T @ ((y - mean_y) * weights)
    system = gram + alpha * np.eye(x.shape[1]); coefficients = np.linalg.solve(system, rhs)
    return {'alpha': alpha, 'intercept': float(mean_y - mean_x @ coefficients), 'coefficients': coefficients.tolist(),
            'penalized_system_condition': float(np.linalg.cond(system)), 'fit_characters': len(y),
            'weights_sum': float(total), 'solver': 'weighted_centered_normal_equations_unpenalized_intercept'}


def design_diagnostics(x, weights, columns):
    centered = x - np.sum(x * weights[:, None], axis=0) / weights.sum()
    singular = np.linalg.svd(centered * np.sqrt(weights[:, None]), compute_uv=False)
    tolerance = max(centered.shape) * np.finfo(float).eps * singular[0] if len(singular) else 0
    present = singular[singular > tolerance]
    zeros = [columns[j] for j in range(x.shape[1]) if np.max(np.abs(centered[:, j])) < 1e-12]
    return {'rows': x.shape[0], 'columns': x.shape[1], 'centered_rank': len(present), 'rank_deficient': len(present) < x.shape[1],
            'full_unpenalized_condition': float(present[0] / present[-1]) if len(present) == x.shape[1] else None,
            'nonzero_subspace_condition': float(present[0] / present[-1]) if len(present) else None,
            'zero_variance_columns': zeros, 'nonzero_row_support': {columns[j]: int(np.count_nonzero(x[:, j])) for j in range(x.shape[1])},
            'parameter_interpretation': 'regularized_joint_predictive_parameters_not_separable_causal_effects'}


def normalize_predictions(values, rows):
    values = np.asarray(values, dtype=float)
    if values.shape != (len(rows),) or not np.isfinite(values).all():
        raise ValueError('Invalid prediction vector')
    groups = defaultdict(list); output = values.copy()
    for i, row in enumerate(rows):
        groups[row['item_name']].append(i)
    for indices in groups.values():
        indices.sort(key=lambda i: rows[i]['position'])
        length = rows[indices[0]]['length']
        if len(indices) != length or [rows[i]['position'] for i in indices] != list(range(1, length + 1)):
            raise ValueError('Prediction normalization requires complete sentence positions')
        nonfinal = np.sort(values[indices[:-1]])
        middle_left, middle_right = nonfinal[(len(nonfinal) - 1) // 2], nonfinal[len(nonfinal) // 2]
        normalizer = float(np.logaddexp(middle_left, middle_right) - math.log(2))
        output[indices] -= normalizer
    return output


def component_errors(predicted, targets, rows):
    errors = np.abs(np.asarray(predicted) - np.asarray(targets)); sums = defaultdict(float); counts = Counter()
    if len(errors) != len(rows) or not np.isfinite(errors).all():
        raise ValueError('Invalid evaluation residuals')
    for row, error in zip(rows, errors):
        sums[row['component']] += float(error); counts[row['component']] += 1
    means = {key: sums[key] / counts[key] for key in sorted(sums)}
    return {'component_macro_MAE': float(np.mean(list(means.values()))), 'character_micro_MAE': float(np.mean(errors)),
            'characters': len(rows), 'sentences': len({r['item_name'] for r in rows}), 'components': len(means),
            'by_component': means}


def fixed_rule_predictions(rows, config):
    d = config['duration']; grouping = config['grouping']; result = []
    for row in rows:
        interior = np.cumsum(grouping[str(row['length'])])[:-1]
        duration = d['base_ms']
        for active, factor in [(row['position'] in interior, 'foot_end_multiplier'),
            (row['position'] == row['length'], 'line_end_multiplier'), (row['historical'] == '平', 'ping_multiplier'),
            (row['historical'] == '入', 'ru_multiplier'), (feature_value(row, 'rhyme_marker') == '1', 'rhyme_multiplier')]:
            if active:
                duration *= d[factor]
        result.append(math.log(int(round(max(d['min_ms'], min(d['max_ms'], duration))))))
    return normalize_predictions(result, rows)


def template_keys(row, pitch=False):
    if pitch:
        return [(str(row['length']), str(row['position']), known(row.get('historical')), known(row.get('modern'))),
                (str(row['length']), str(row['position']), known(row.get('historical'))),
                (str(row['length']), str(row['position'])), (str(row['length']),)]
    return [(str(row['length']), str(row['order']), str(row['count'])),
            (str(row['length']), str(row['order'])), (str(row['length']),)]


def key_name(level, key):
    return json.dumps([level, *key], ensure_ascii=False, separators=(',', ':'))


def fit_duration_templates(rows, targets, minimum=20):
    groups = defaultdict(lambda: defaultdict(list))
    for row, value in zip(rows, targets):
        for level, key in enumerate(template_keys(row)):
            groups[(key_name(level, key), row['position'])][row['component']].append(float(value))
    templates = {}
    for (key, position), components in groups.items():
        if len(components) < minimum:
            continue
        templates.setdefault(key, {})[str(position)] = {'value': float(np.median([np.median(v) for v in components.values()])),
                                                       'components': len(components)}
    return {'model': 'M4', 'minimum_components': minimum, 'templates': templates,
            'aggregation': 'per_component_median_then_median_across_components'}


def template_duration_predictions(rows, model):
    values = []
    for row in rows:
        found = None
        for level, key in enumerate(template_keys(row)):
            value = model['templates'].get(key_name(level, key), {}).get(str(row['position']))
            if value is not None:
                found = value['value']; break
        if found is None:
            raise ValueError('No training-supported position template for sentence length')
        values.append(found)
    return normalize_predictions(values, rows)


def predict_duration(rows, model):
    if model['model'] == 'M0':
        return fixed_rule_predictions(rows, model['configuration'])
    if model['model'] == 'M4':
        return template_duration_predictions(rows, model)
    raw = encode(rows, model['encoder']) @ np.array(model['fit']['coefficients']) + model['fit']['intercept']
    return normalize_predictions(raw, rows)


def choose_default(scores):
    baseline = scores['M1']; candidates = [key for key in ('M2', 'M3', 'M4') if scores[key] <= .99 * baseline]
    if not candidates:
        return 'M1'
    winner = candidates[0]
    for key in candidates[1:]:
        if scores[key] < scores[winner] - 1e-12:
            winner = key
    return winner


def fit_lexicon(rows):
    by_character = defaultdict(lambda: {'historical': set(), 'pinyin': set(), 'modern': set()})
    for row in rows:
        entry = by_character[row['character']]
        entry['historical'].add(row['historical']); entry['modern'].add(row['modern']); entry['pinyin'].add(row['pinyin'])
    return {character: {key: sorted(value) for key, value in fields.items()} for character, fields in sorted(by_character.items())}


def automatic_rows(rows, lexicon):
    result = []
    for row in rows:
        entry = lexicon.get(row['character'], {})
        candidate = {**row, 'speaker': None, 'rhyme': UNKNOWN}
        for key in ('historical', 'modern'):
            values = entry.get(key, [])
            candidate[key] = values[0] if len(values) == 1 else UNKNOWN
        result.append(candidate)
    return result


def phase_curve(arrays, character, register_hz):
    if register_hz is None or register_hz <= 0:
        return [None] * 5
    t = arrays['time_s']; f = arrays['consensus_50_hz']; start = character['start_s']; end = character['policies']['E0']['end_s']
    mask = (t >= start) & (t < end) & np.isfinite(f)
    if int(mask.sum()) < 3:
        return [None] * 5
    phase = (t[mask] - start) / (end - start); semitones = 12 * np.log2(f[mask] / register_hz)
    edges = [0, .125, .375, .625, .875, 1]
    result = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        values = semitones[(phase >= lo) & (phase < hi)]
        result.append(float(np.median(values)) if len(values) else None)
    return result


def fit_pitch_templates(samples, minimum=20):
    groups = defaultdict(lambda: defaultdict(list))
    for row, curve in samples:
        vector = np.array([np.nan if v is None else v for v in curve])
        for level, key in enumerate(template_keys(row, pitch=True)):
            groups[key_name(level, key)][row['component']].append(vector)
    templates = {}
    for key, components in groups.items():
        if len(components) < minimum:
            continue
        values, available = [], []
        for curves in components.values():
            matrix = np.stack(curves); finite = np.isfinite(matrix)
            values.append([float(np.median(matrix[finite[:, j], j])) if finite[:, j].any() else np.nan for j in range(5)])
            available.append(finite.mean(axis=0))
        matrix = np.array(values); support = np.isfinite(matrix).sum(axis=0)
        templates[key] = {'curve': [float(np.median(matrix[np.isfinite(matrix[:, j]), j])) if support[j] >= minimum else None for j in range(5)],
                          'bin_components': support.tolist(), 'opportunity_components': len(components),
                          'reference_available_fraction': np.mean(available, axis=0).tolist()}
    return {'model': 'training_only_phase_pitch_template', 'minimum_components': minimum,
            'phase_centers': [0, .25, .5, .75, 1], 'templates': templates,
            'reference': 'E0_shared50_automatic_not_human_truth', 'units': 'semitones_relative_to_recording_group_median'}


def predict_pitch(row, model):
    curve = []; supports = []; availability = []; levels = []
    keys = [key_name(level, key) for level, key in enumerate(template_keys(row, pitch=True))]
    for j in range(5):
        found = None
        for level, key in enumerate(keys):
            candidate = model['templates'].get(key)
            if candidate is not None and candidate['curve'][j] is not None and candidate['bin_components'][j] >= model['minimum_components']:
                found = candidate; levels.append(level); break
        if found is None:
            curve.append(None); supports.append(0); availability.append(None); levels.append(None)
        else:
            curve.append(found['curve'][j]); supports.append(found['bin_components'][j]); availability.append(found['reference_available_fraction'][j])
    return {'curve': curve, 'support_components': supports, 'reference_available_fraction': availability, 'fallback_levels': levels}
