#!/usr/bin/env python3
"""Research inference using only a portable model bundle and poem text."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import prosody_models
from prosody_models import UNKNOWN, automatic_rows, predict_duration, predict_pitch


def read(path):
    return json.loads(path.read_text())


def bundle_file(folder, name):
    path = (folder / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(folder):
        raise ValueError('Model artifact path leaves bundle')
    return path


def predict(folder, text, labels=None, model_name=None, speed_ms=None, base_hz=None):
    folder = folder.resolve(); bundle = read(folder / 'bundle.json')
    for name, identity in bundle['files'].items():
        if hashlib.sha256(bundle_file(folder, name).read_bytes()).hexdigest() != identity:
            raise RuntimeError('Model bundle integrity changed')
    if hashlib.sha256(Path(prosody_models.__file__).read_bytes()).hexdigest() != bundle['files']['source/prosody_models.py']:
        raise RuntimeError('Prediction implementation differs from bundled source')
    lines = [re.sub(r'\s+', '', s) for s in re.split(r'[\n，。！？；,;!?]+', text) if s.strip()]
    if not lines or any(len(line) not in (5, 7) or not re.fullmatch(r'[\u3400-\u9fff\uf900-\ufaff]+', line) for line in lines):
        raise ValueError('Research entry requires complete five- or seven-character Chinese lines')
    rows = []
    for li, line in enumerate(lines):
        for ci, character in enumerate(line):
            rows.append({'item_name': f'input_{li + 1:03}', 'length': len(line), 'position': ci + 1,
                         'order': li + 1, 'count': len(lines), 'speaker': None, 'character': character,
                         'historical': UNKNOWN, 'modern': UNKNOWN, 'rhyme': UNKNOWN})
    lexicon = read(bundle_file(folder, bundle['lexicon']))
    if labels is None:
        rows = automatic_rows(rows, lexicon); mode = 'automatic_training_lexicon_secondary'
        chosen = model_name or bundle['automatic_text_default']
    else:
        mode = 'provided_annotations_conditioned'; chosen = model_name or bundle['provided_annotation_default']
        for name, allowed in [('historical', set('平上去入?')), ('modern', set('12345?')), ('rhyme', set('0123?'))]:
            values = labels[name]
            if len(values) != len(lines) or any(len(v) != len(line) or not set(v).issubset(allowed) for v, line in zip(values, lines)):
                raise ValueError('Provided label lines do not match poem text or nominal vocabulary')
        for row in rows:
            for name in ('historical', 'modern', 'rhyme'):
                row[name] = labels[name][row['order'] - 1][row['position'] - 1]
    models = {name: read(bundle_file(folder, path)) for name, path in bundle['duration_models'].items()}
    if chosen not in models:
        raise ValueError('Requested duration model is absent')
    predictions = {name: predict_duration(rows, model) for name, model in models.items()}
    defaults = read(bundle_file(folder, bundle['defaults']))
    speed = defaults['speed_nonfinal_median_ms'] if speed_ms is None else speed_ms
    register = defaults['register_Hz'] if base_hz is None else base_hz
    if not math.isfinite(speed) or not math.isfinite(register) or speed <= 0 or register <= 0:
        raise ValueError('Speed and register must be positive finite controls')
    pitch = read(bundle_file(folder, bundle['pitch_model'])); result = []; offset = 0
    for li, line in enumerate(lines):
        characters = []; local_time = 0
        for ci, character in enumerate(line):
            row = rows[offset]; duration = speed * math.exp(float(predictions[chosen][offset])); contour = predict_pitch(row, pitch)
            points = [{'phase': phase, 'relative_semitones': relative,
                       'hz': register * 2 ** (relative / 12) if relative is not None else None,
                       'support_training_components': support, 'training_reference_available_fraction': available}
                      for phase, relative, support, available in zip(pitch['phase_centers'], contour['curve'], contour['support_components'], contour['reference_available_fraction'])]
            candidates = lexicon.get(character, {'historical': [], 'modern': [], 'pinyin': []})
            spread = max(float(v[offset]) for v in predictions.values()) - min(float(v[offset]) for v in predictions.values())
            characters.append({'character': character, 'position': ci + 1, 'start_within_line_ms': local_time,
                'duration_ms': duration, 'log_relative_duration': float(predictions[chosen][offset]),
                'input_features': {key: row[key] for key in ('historical', 'modern', 'rhyme')}, 'training_label_candidates': candidates,
                'pitch_points': points, 'pitch_fallback_levels': contour['fallback_levels'],
                'candidate_model_spread_log_not_probability': spread, 'calibrated_interval': None})
            local_time += duration; offset += 1
        result.append({'text': line, 'characters': characters, 'duration_ms': local_time, 'between_line_pause_ms': None})
    return {'schema': 'research_prosody_prediction_v1', 'mode': mode, 'duration_model': chosen,
            'speed_nonfinal_median_ms': speed, 'register_control_Hz': register, 'lines': result,
            'model_bundle_sha256': hashlib.sha256((folder / 'bundle.json').read_bytes()).hexdigest(),
            'requires_reference_audio': False, 'human_verified': False, 'final_score_contract': False,
            'limitations': ['training label candidates are not verified readings', 'rhyme is unknown in automatic text mode',
                'pitch templates are automatic weak-reference predictions; source gaps are not reconstructed',
                'model spread is not a confidence probability; calibration belongs to P07',
                'no claimed personal style, historical melody, naturalness or fixed-meter performance']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-dir', type=Path, required=True); parser.add_argument('--text', required=True)
    parser.add_argument('--labels', type=Path); parser.add_argument('--model', choices=('M0', 'M1', 'M2', 'M3', 'M4'))
    parser.add_argument('--speed-ms', type=float); parser.add_argument('--base-hz', type=float); parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = predict(args.model_dir, args.text, read(args.labels) if args.labels else None, args.model, args.speed_ms, args.base_hz)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x') as handle:
            handle.write(serialized)
    else:
        print(serialized)


if __name__ == '__main__':
    main()
