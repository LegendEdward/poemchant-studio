"""User-visible invariants: immutable drafts, truthful unknowns and real exports."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
import zipfile
from xml.etree import ElementTree as ET
import mido
from poemchant_studio.document import make_document, update_document, validate_document
from poemchant_studio.exports import FILES, payloads_for, write_document
from poemchant_studio.legacy.contract import edit_project
from poemchant_studio.models import ModelManager
from poemchant_studio.rules import RulesEngine
from poemchant_studio.server import create_server

POEM = '床前明月光，疑是地上霜。举头望明月，低头思故乡。'


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.engine = RulesEngine()
        self.project = self.engine.generate(POEM, title='静夜思', author='李白')
        self.doc = make_document(self.project)

    def test_rules_never_claim_training_or_calibration(self):
        self.assertIn('untrained', self.project['parameter_status'])
        self.assertFalse(self.project['model_score']['provenance']['trained'])
        for line in self.project['model_score']['lines']:
            for char in line['characters']:
                self.assertIsNone(char['uncertainty']['calibration']['nominal_coverage'])
                self.assertIsNone(char['uncertainty']['measurement'])
        self.engine.validate_origin(self.project)

    def test_explicit_unknown_labels_remain_flagged(self):
        labels = {'historical':['?????']*4, 'modern':['?????']*4, 'rhyme':['?????']*4}
        project = self.engine.generate(POEM, labels=labels)
        for line in project['model_score']['lines']:
            for char in line['characters']:
                self.assertTrue(char['uncertainty']['input']['ambiguous_or_unknown'])
                self.assertIsNone(char['phonology']['selected_historical'])
                self.assertEqual(char['pitch']['runs'], [])

    def test_all_four_supported_shapes(self):
        seven = ['远上寒山石径斜', '白云生处有人家', '停车坐爱枫林晚', '霜叶红于二月花']
        five = self.project['poem']['lines']
        for lines in (five, seven, five*2, seven*2):
            doc = make_document(self.engine.generate('\n'.join(lines)))
            self.assertEqual(len(doc['annotations']), sum(map(len, lines)))
            validate_document(doc)

    def test_annotations_edits_and_original_survive_export_reimport(self):
        original = copy.deepcopy(self.project)
        edited = edit_project(self.project, [{'line':1,'position':1,'character':'床','duration_ms':700,
                                             'pitch_points':[[0,210],[.25,220],[.5,None],[.75,230],[1,240]]}], .9)
        annotations = copy.deepcopy(self.doc['annotations'])
        annotations[0]['note'] = '曲线断开处保留未知。'
        annotations[0]['caesura_after'] = True
        doc = update_document(self.doc, edited, annotations, '整体备注')
        self.assertEqual(original, self.project)
        self.assertEqual(doc['score_project']['model_score'], original['model_score'])
        self.assertEqual(doc['annotations'][0]['origin'], 'user_edited')
        data, manifest = payloads_for(doc)
        restored = json.loads(data[FILES['project']])
        rendered = validate_document(restored)
        self.engine.validate_origin(restored['score_project'])
        first = rendered['lines'][0]['characters'][0]
        self.assertAlmostEqual(first['end_s']-first['start_s'], .7)
        self.assertEqual(len(first['pitch_runs']), 2)
        self.assertLess(first['pitch_runs'][0]['end_s'], first['pitch_runs'][1]['start_s'])
        self.assertEqual(restored, json.loads(payloads_for(restored)[0][FILES['project']]))
        with zipfile.ZipFile(io.BytesIO(data[FILES['zip']])) as archive:
            for name in archive.namelist():
                self.assertEqual(archive.read(name), data[name])

    def test_csv_formula_protection_preserves_original_json(self):
        annotations = copy.deepcopy(self.doc['annotations'])
        annotations[0]['note'] = '=HYPERLINK("https://example.invalid")'
        doc = update_document(self.doc, self.project, annotations, '')
        data, _ = payloads_for(doc)
        row = list(csv.DictReader(io.StringIO(data[FILES['csv']].decode('utf-8-sig'))))[0]
        self.assertTrue(row['note'].startswith("'="))
        self.assertTrue(json.loads(data[FILES['annotations']])[0]['note'].startswith('='))

    def test_unknown_pitch_remains_unknown_in_exports(self):
        edited = edit_project(self.project, [{'line':1,'position':1,'character':'床','pitch_points':[[0,None],[1,None]]}])
        doc = update_document(self.doc, edited, self.doc['annotations'], '')
        rendered = validate_document(doc)
        self.assertEqual(rendered['lines'][0]['characters'][0]['pitch_runs'], [])
        data, _ = payloads_for(doc)
        self.assertIn('音高未知', data[FILES['svg']].decode())
        root = ET.fromstring(data[FILES['musicxml']])
        self.assertIsNotNone(root.find('./part/measure/note/rest'))
        with wave.open(io.BytesIO(data[FILES['audio']])) as wav:
            frames = wav.readframes(round(.4*wav.getframerate()))
            self.assertEqual(set(frames), {0})

    def test_actual_midi_xml_audio_and_annotation_exports(self):
        data, manifest = payloads_for(self.doc)
        midi = mido.MidiFile(file=io.BytesIO(data[FILES['midi']]))
        self.assertGreater(len(midi.tracks[0]), 20)
        self.assertAlmostEqual(midi.length, manifest['duration_s'], delta=.002)
        root = ET.fromstring(data[FILES['musicxml']])
        self.assertEqual(''.join(n.text for n in root.findall('.//lyric/text')), ''.join(self.project['poem']['lines']))
        with wave.open(io.BytesIO(data[FILES['audio']])) as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertAlmostEqual(wav.getnframes()/wav.getframerate(), manifest['duration_s'], delta=.0001)
        for name, info in manifest['files'].items():
            self.assertEqual(hashlib.sha256(data[name]).hexdigest(), info['sha256'])

    def test_invalid_reading_and_forged_original_rejected(self):
        annotations = copy.deepcopy(self.doc['annotations'])
        annotations[0]['modern_tone'] = '4'
        with self.assertRaisesRegex(ValueError, '不一致'):
            update_document(self.doc, self.project, annotations, '')
        forged = copy.deepcopy(self.doc)
        forged['score_project']['model_score']['lines'][0]['characters'][0]['end_s'] += .1
        with self.assertRaises(ValueError):
            validate_document(forged)

    def test_escaping_title_and_no_overwrite(self):
        doc = make_document(self.engine.generate(POEM, title='<script>alert(1)</script>'))
        data, _ = payloads_for(doc)
        self.assertNotIn('<script>', data[FILES['svg']].decode())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'score'
            write_document(doc, output)
            before = (output/FILES['project']).read_bytes()
            with self.assertRaises(FileExistsError):
                write_document(doc, output)
            self.assertEqual((output/FILES['project']).read_bytes(), before)

    def test_wrong_shape_and_bad_edits_rejected(self):
        for text in ('', '床前明月光', 'abcd，efgh。ijkl，mnop。'):
            with self.assertRaises(ValueError):
                self.engine.generate(text)
        for duration in (-1, True, float('nan'), 5001):
            with self.assertRaises(ValueError):
                edit_project(self.project, [{'line':1,'position':1,'character':'床','duration_ms':duration}])

    def test_model_zip_paths_never_escape_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ModelManager(Path(tmp))
            for name in ('../outside.py', '/outside.py', 'a/../../outside.py'):
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, 'w') as archive:
                    archive.writestr('release_manifest.json', '{}')
                    archive.writestr(name, 'bad')
                with self.assertRaises((ValueError, OSError, KeyError)):
                    manager.import_pack(buffer.getvalue())
            self.assertFalse((Path(tmp)/'outside.py').exists())
            self.assertFalse((Path(tmp)/'model_packs'/'prosody_v1').exists())


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = create_server(0, Path(self.tmp.name))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        page = urllib.request.urlopen(self.base).read().decode()
        import re
        self.token = re.search('name="poemchant-token" content="([^"]+)"', page)[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        request = urllib.request.Request(self.base+path, data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                  headers={'Content-Type':'application/json','X-PoemChant-Token':self.token, **(headers or {})})
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_generate_save_reopen_and_restore_an_earlier_draft(self):
        first = self.call('/api/generate', {'text':POEM, 'title':'静夜思', 'mode':'rules'})
        body = {'run_id':first['run_id'],'edits':[{'line':1,'position':1,'character':'床','duration_ms':750}],
                'annotations':first['document']['annotations'],'note':'新稿','line_gap_s':.8}
        body['annotations'][0]['note'] = '候选读音待核对'
        second = self.call('/api/save', body)
        self.assertNotEqual(first['run_id'], second['run_id'])
        again = self.call('/api/open', {'run_id':second['run_id']})
        self.assertEqual(again['document'], second['document'])
        old = self.call('/api/open', {'run_id':first['run_id']})
        self.assertEqual(old['document']['score_project']['edits'], [])
        self.assertEqual(old['document']['annotations'][0]['note'], '')
        imported = self.call('/api/import', {'document':second['document']})
        self.assertEqual(imported['document'], second['document'])
        state = self.call('/api/state')
        self.assertEqual(len(state['recent']), 3)
        with urllib.request.urlopen(self.base+second['files']['csv']) as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
        self.assertEqual(rows[0]['duration_ms'], '750.0')
        self.assertEqual(rows[0]['note'], '候选读音待核对')

    def test_untrusted_requests_rejected_and_service_still_works(self):
        attempts = [('/api/generate', {'text':POEM}, {'X-PoemChant-Token':'bad'}),
                    ('/api/generate', {'text':POEM}, {'Origin':'https://evil.example'}),
                    ('/api/generate', {'text':POEM}, {'Host':'evil.example'}),
                    ('/api/import', {'document':[]}, {}),
                    ('/api/open', {'run_id':'../../etc/passwd'}, {})]
        for path, body, headers in attempts:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.call(path, body, headers)
            self.assertIn(caught.exception.code, (400,403))
        self.assertEqual(self.call('/api/state')['version'], '2.0.0')

    def test_explicit_reinference_uses_annotations_and_removes_acoustic_edits(self):
        first = self.call('/api/generate', {'text':POEM,'mode':'rules'})
        anns = first['document']['annotations']
        anns[0]['pinyin'], anns[0]['modern_tone'] = 'chuang4', '4'
        second = self.call('/api/reinfer', {'run_id':first['run_id'], 'edits':[{'line':1,'position':1,'character':'床','duration_ms':750}],
                          'annotations':anns,'note':'测试重生成','line_gap_s':.7})
        project = second['document']['score_project']
        self.assertEqual(project['input']['labels']['modern'][0][0], '4')
        self.assertEqual(project['edits'], [])
        self.assertEqual(second['document']['annotations'][0]['pinyin'], 'chuang4')


if __name__ == '__main__':
    unittest.main()
