"""Free-time reference-run exports; unavailable support becomes silent controls."""
from __future__ import annotations

import io
import math
import statistics
import struct
from xml.etree import ElementTree as ET

PPQ, TEMPO, BEND_RANGE, DIVISIONS = 480, 500000, 48, 10000


def midi_pitch(hz):
    if not math.isfinite(hz) or hz <= 0:
        raise ValueError('Pitch requires positive finite Hz')
    return 69 + 12 * math.log2(hz / 440)


def vlq(value):
    if not 0 <= value <= 0x0fffffff:
        raise ValueError('MIDI delta exceeds valid variable-length range')
    data = [value & 127]; value >>= 7
    while value:
        data.insert(0, (value & 127) | 128); value >>= 7
    return bytes(data)


def write_midi(runs, duration_s):
    events = [(0, -10, b'\xff\x51\x03' + TEMPO.to_bytes(3, 'big')), (0, -9, bytes([0xc0, 73]))]
    for order, (controller, value) in enumerate([(101, 0), (100, 0), (6, BEND_RANGE), (38, 0), (101, 127), (100, 127)]):
        events.append((0, -8 + order, bytes([0xb0, controller, value])))
    expected = []; dropped = 0; skipped = 0; source_points = 0
    for run in runs:
        pitches = [midi_pitch(value) for value in run['Hz']]; source_points += len(pitches)
        start, end = round(run['start_s'] * PPQ * 1e6 / TEMPO), round(run['end_s'] * PPQ * 1e6 / TEMPO)
        base = round((min(pitches) + max(pitches)) / 2)
        if start >= end or not 0 <= base <= 127:
            skipped += 1; dropped += len(pitches); continue
        points = []
        for t, target, reference in zip(run['time_s'], pitches, run['reference_Hz']):
            tick = round(t * PPQ * 1e6 / TEMPO)
            bend = round(8192 + (target - base) * 8192 / BEND_RANGE)
            if tick >= end or tick < start or not 0 <= bend <= 16383:
                dropped += 1; continue
            events.append((tick, 1, bytes([0xe0, bend & 127, bend >> 7])))
            points.append({'time_s': t, 'target_midi': target, 'reference_midi': midi_pitch(reference)})
        if not points:
            skipped += 1; continue
        events.extend([(start, 2, bytes([0x90, base, 80])), (end, 0, bytes([0x80, base, 0]))])
        expected.append({'start_s': run['start_s'], 'end_s': run['end_s'], 'base_midi': base, 'points': points})
    events.sort(key=lambda value: (value[0], value[1])); previous = 0; track = bytearray()
    for tick, _, payload in events:
        track.extend(vlq(tick - previous)); track.extend(payload); previous = tick
    final = max(previous, round(duration_s * PPQ * 1e6 / TEMPO))
    track.extend(vlq(final - previous) + b'\xff\x2f\x00')
    data = b'MThd' + struct.pack('>IHHH', 6, 0, 1, PPQ) + b'MTrk' + struct.pack('>I', len(track)) + track
    return data, {'notes': expected, 'source_points': source_points, 'encoded_points': sum(len(v['points']) for v in expected),
                  'dropped_points': dropped, 'skipped_runs': skipped, 'bend_range_semitones': BEND_RANGE}


def read_midi_with_mido(data):
    import mido
    file = mido.MidiFile(file=io.BytesIO(data)); notes = []; active = None; pending = []; tick = 0; tempo = TEMPO
    bend_range = 2; rpn_msb = rpn_lsb = 127; last_bend = 0
    for message in file.tracks[0]:
        tick += message.time; time_s = mido.tick2second(tick, file.ticks_per_beat, tempo)
        if message.type == 'set_tempo':
            if tick:
                raise ValueError('Diagnostic reader expects the emitted single transport tempo')
            tempo = message.tempo
        elif message.type == 'control_change':
            if message.control == 101:
                rpn_msb = message.value
            elif message.control == 100:
                rpn_lsb = message.value
            elif message.control == 6 and (rpn_msb, rpn_lsb) == (0, 0):
                bend_range = message.value
        elif message.type == 'pitchwheel':
            last_bend = message.pitch
            if active is None:
                pending.append((time_s, message.pitch))
            else:
                active['points'].append({'time_s': time_s, 'midi': active['base_midi'] + message.pitch * bend_range / 8192})
        elif message.type == 'note_on' and message.velocity:
            if active is not None:
                raise ValueError('Unexpected polyphony in monophonic reference export')
            active = {'start_s': time_s, 'base_midi': message.note, 'points': [
                {'time_s': at, 'midi': message.note + bend * bend_range / 8192} for at, bend in pending]}
            if not pending:
                active['points'].append({'time_s': time_s, 'midi': message.note + last_bend * bend_range / 8192})
            pending = []
        elif message.type == 'note_off' or (message.type == 'note_on' and not message.velocity):
            if active is None or active['base_midi'] != message.note:
                raise ValueError('MIDI note lifecycle changed')
            active['end_s'] = time_s; notes.append(active); active = None; pending = []
    if active is not None:
        raise ValueError('MIDI note is left active')
    return {'notes': notes, 'ticks_per_beat': file.ticks_per_beat, 'bend_range_semitones': bend_range, 'tempo_us': tempo}


def midi_roundtrip_metrics(expected, decoded):
    if len(expected['notes']) != len(decoded['notes']) or decoded['bend_range_semitones'] != BEND_RANGE:
        raise ValueError('MIDI roundtrip structure changed')
    times = []; quantization = []; total = []
    for source, result in zip(expected['notes'], decoded['notes']):
        if source['base_midi'] != result['base_midi'] or len(source['points']) != len(result['points']):
            raise ValueError('MIDI roundtrip note or point counts changed')
        times.extend([abs(source['start_s'] - result['start_s']), abs(source['end_s'] - result['end_s'])])
        for before, after in zip(source['points'], result['points']):
            times.append(abs(before['time_s'] - after['time_s']))
            quantization.append(100 * abs(before['target_midi'] - after['midi']))
            total.append(100 * abs(before['reference_midi'] - after['midi']))
    return {'source_points': expected['source_points'], 'encoded_points': expected['encoded_points'],
            'dropped_points': expected['dropped_points'], 'skipped_runs': expected['skipped_runs'],
            'max_time_error_ms': 1000 * max(times) if times else None,
            'pitch_quantization_MAE_cents': statistics.mean(quantization) if quantization else None,
            'max_pitch_quantization_cents': max(quantization) if quantization else None,
            'representation_plus_quantization_MAE_cents': statistics.mean(total) if total else None,
            'comparison': 'paired_encoded_events_with_timestamp_error_reported_not_waveform_accuracy'}


def pitch_node(parent, midi):
    names = [('C',0),('C',1),('D',0),('D',1),('E',0),('F',0),('F',1),('G',0),('G',1),('A',0),('A',1),('B',0)]
    step, alter = names[midi % 12]; pitch = ET.SubElement(parent, 'pitch')
    ET.SubElement(pitch, 'step').text = step
    if alter:
        ET.SubElement(pitch, 'alter').text = str(alter)
    ET.SubElement(pitch, 'octave').text = str(midi // 12 - 1)


def write_musicxml(runs, duration_s):
    root = ET.Element('score-partwise', version='4.0'); plist = ET.SubElement(root, 'part-list')
    part = ET.SubElement(plist, 'score-part', id='P1'); ET.SubElement(part, 'part-name').text = 'Automatic reference note approximation'
    part = ET.SubElement(root, 'part', id='P1'); measure = ET.SubElement(part, 'measure', number='1', implicit='yes')
    attr = ET.SubElement(measure, 'attributes'); ET.SubElement(attr, 'divisions').text = str(DIVISIONS)
    ET.SubElement(ET.SubElement(attr, 'time'), 'senza-misura')
    direction = ET.SubElement(measure, 'direction'); text = ET.SubElement(ET.SubElement(direction, 'direction-type'), 'words')
    text.text = 'Free time; rests indicate missing or unassigned pitch support, not measured silence.'
    ET.SubElement(direction, 'sound', tempo='60')
    cursor = 0; expected = []; dropped = 0; source_points = 0
    def rest(duration):
        if duration > 0:
            node = ET.SubElement(measure, 'note'); ET.SubElement(node, 'rest'); ET.SubElement(node, 'duration').text = str(duration)
    for run in runs:
        source_points += len(run['reference_Hz'])
        start, end = round(run['start_s'] * DIVISIONS), round(run['end_s'] * DIVISIONS)
        median_pitch = statistics.median([midi_pitch(v) for v in run['reference_Hz']]); note = round(median_pitch)
        if start >= end or not 0 <= note <= 127:
            dropped += len(run['reference_Hz']); continue
        if start < cursor:
            raise ValueError('Reference support overlaps after MusicXML time quantization')
        rest(start - cursor); node = ET.SubElement(measure, 'note'); pitch_node(node, note)
        ET.SubElement(node, 'duration').text = str(end - start)
        if run.get('character'):
            lyric = ET.SubElement(node, 'lyric'); ET.SubElement(lyric, 'text').text = run['character']
        expected.append({'start_s': run['start_s'], 'end_s': run['end_s'], 'note_midi': note,
                         'median_midi': median_pitch, 'reference_midi': [midi_pitch(v) for v in run['reference_Hz']]})
        cursor = end
    rest(max(0, round(duration_s * DIVISIONS) - cursor))
    return ET.tostring(root, encoding='utf-8', xml_declaration=True), {'notes': expected, 'source_points': source_points, 'dropped_points': dropped}


def read_musicxml(data):
    root = ET.fromstring(data); divisions = int(root.findtext('.//divisions')); tempo = float(root.find('.//sound').get('tempo'))
    cursor = 0; notes = []
    for measure in root.findall('./part/measure'):
        for node in measure.findall('note'):
            duration = int(node.findtext('duration'))
            if duration <= 0:
                raise ValueError('MusicXML has nonpositive duration')
            pitch = node.find('pitch')
            if pitch is not None:
                step = {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[pitch.findtext('step')]
                midi = 12 * (int(pitch.findtext('octave')) + 1) + step + int(pitch.findtext('alter', '0'))
                notes.append({'start_s': cursor / divisions * 60 / tempo, 'end_s': (cursor + duration) / divisions * 60 / tempo, 'midi': midi})
            cursor += duration
    return notes


def musicxml_roundtrip_metrics(expected, decoded):
    if len(expected['notes']) != len(decoded):
        raise ValueError('MusicXML note count changed')
    times = []; representative = []; errors = []
    for source, result in zip(expected['notes'], decoded):
        if source['note_midi'] != result['midi']:
            raise ValueError('MusicXML step/alter/octave changed representative note')
        times.extend([abs(source['start_s'] - result['start_s']), abs(source['end_s'] - result['end_s'])])
        representative.append(100 * abs(source['median_midi'] - result['midi']))
        errors.extend(100 * abs(value - result['midi']) for value in source['reference_midi'])
    return {'source_points': expected['source_points'], 'encoded_points': len(errors), 'dropped_points': expected['dropped_points'],
            'max_time_error_ms': 1000 * max(times) if times else None,
            'representative_note_quantization_MAE_cents': statistics.mean(representative) if representative else None,
            'reference_frame_pitch_MAE_cents': statistics.mean(errors) if errors else None,
            'comparison': 'representative_note_and_time_loss_not_continuous_curve_reconstruction'}
