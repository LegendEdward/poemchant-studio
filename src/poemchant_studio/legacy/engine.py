"""Offline inference adapter around an unchanged frozen research model."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from .contract import identity,number,parse_text,project_digest,validate_project
from .vendor.score_contract import from_prediction,input_uncertainty

ROOT=Path(__file__).resolve().parent


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class Engine:
    def __init__(self,model_dir=None):
        self.folder=Path(model_dir).resolve() if model_dir else ROOT.parent/'models/release_v1'
        manifest=read(self.folder/'release_manifest.json');self.manifest=manifest
        self.manifest_sha256=sha(self.folder/'release_manifest.json');self.verify_cache()
        self.exposure=read(self.folder/'text_exposure.json')

    def verify_cache(self):
        if sha(self.folder/'release_manifest.json')!=self.manifest_sha256:raise ValueError('模型发布清单已改变。')
        manifest=self.manifest
        for name,expected in manifest['files'].items():
            path=(self.folder/name).resolve()
            if not path.is_relative_to(self.folder) or sha(path)!=expected:raise ValueError('模型缓存校验失败：'+name)

    def validate_origin(self,project):
        validate_project(project);provenance=project['model_score']['provenance']
        regenerated=self.generate(project['input']['original_text'],title=project['poem']['title'],author=project['poem']['author'],
            poem_id=project['poem_id'],labels=project['input']['labels'],model=project['input']['requested_model'],
            speed_ms=provenance['speed_nonfinal_median_ms'],base_hz=provenance['register_control_Hz'],
            line_gap_s=project['playback']['line_gap_s'],source=project['poem']['source'])
        if regenerated['source_hashes']['model_score_sha256']!=project['source_hashes']['model_score_sha256']:
            raise ValueError('工程模型原稿与当前冻结模型不一致，未作为本模型结果导入。')
        if regenerated['model_id'] != project['model_id'] or regenerated['parameter_status'] != project['parameter_status']:
            raise ValueError('工程模型或来源状态被改变。')
        return True

    def generate(self,text,title='未题名',author='未署名',poem_id=None,labels=None,model=None,speed_ms=520.,base_hz=228.44713451717257,line_gap_s=.65,source=None):
        self.verify_cache()
        lines,form=parse_text(text)
        for value,label in [(title,'题名'),(author,'作者')]:
            if not isinstance(value,str) or len(value)>160 or any(ord(c)<32 for c in value):raise ValueError(label+'格式或长度不正确。')
        poem_id=poem_id or 'input-'+hashlib.sha256(text.encode()).hexdigest()[:16]
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,80}',poem_id):raise ValueError('诗篇编号不安全。')
        speed=number(speed_ms,150,1200,'非句末字时长（毫秒）');register=number(base_hz,80,600,'音区基准（Hz）');gap=number(line_gap_s,0,3,'句间试听间隔')
        if model is not None and model not in ('M0','M1','M2','M3','M4'):raise ValueError('不支持的模型方案。')
        if labels is not None:
            if not isinstance(labels,dict) or set(labels)!={'historical','modern','rhyme'}:
                raise ValueError('注音须包含historical、modern、rhyme三个字段。')
            for name,allowed in [('historical',set('平上去入?')),('modern',set('12345?')),('rhyme',set('0123?'))]:
                values=labels[name]
                if not isinstance(values,list) or len(values)!=len(lines) or any(not isinstance(v,str) or len(v)!=len(line) or not set(v)<=allowed for v,line in zip(values,lines)):
                    raise ValueError('注音行数、字数或类别与原诗不匹配。')
        # Absolute imports inside the frozen predictor resolve to these exact copies.
        vendor=Path(__file__).parent/'vendor';sys.path.insert(0,str(vendor))
        try:
            from research_predict import predict
            prediction=predict(self.folder,'\n'.join(lines),labels,model,speed,register)
        finally:sys.path.remove(str(vendor))
        import numpy as np
        provenance={'model_bundle_sha256':sha(self.folder/'bundle.json'),'calibration_sha256':sha(self.folder/'calibration.json'),
            'product_model_manifest_sha256':sha(self.folder/'release_manifest.json'),'mode':prediction['mode'],
            'duration_model':prediction['duration_model'],'speed_nonfinal_median_ms':speed,'register_control_Hz':register,
            'selected_label_origin':'provided_unverified_labels' if labels is not None else 'training_only_lexicon_candidates',
            'requires_reference_audio':False,'pitch':'coarse template, no human or historical melody validation'}
        score=from_prediction(prediction,read(self.folder/'calibration.json'),provenance)
        # The predictor's input sentinel is '?'; the score contract expresses
        # unknown selected labels as null. This changes no predicted numbers.
        for line in score['lines']:
            for char in line['characters']:
                phonology=char['phonology']
                for field in ('selected_historical','selected_modern_tone','raw_rhyme'):
                    if phonology[field]=='?':phonology[field]=None
                char['uncertainty']['input']=input_uncertainty(phonology)
        by_line=[]
        for line in lines:
            h=hashlib.sha256(line.encode()).hexdigest();by_line.append({'text_sha256':h,'exact_release_splits':self.exposure['exact_sentence_sha256_to_splits'].get(h,[])})
        source=source or {}
        if not isinstance(source,dict):raise ValueError('来源记录须为对象。')
        json.dumps(source,ensure_ascii=False,allow_nan=False)
        files={str(p.relative_to(ROOT)):sha(p) for p in sorted(ROOT.rglob('*.py'))}
        project={'schema':'PoemChantProject1.0','schema_version':'1.0','poem_id':poem_id,'score_id':'',
            'model_id':'prosody_v1:'+prediction['duration_model'],'parameter_status':'frozen_automatic_weak_reference_model',
            'source_hashes':{'input_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'model_score_sha256':identity(score),
                'model_release_sha256':sha(self.folder/'release_manifest.json'),'generator_sources_sha256':files,
                'generator_entrypoint_sha256':sha(ROOT/'app.py'),
                'product_manifest_sha256':sha(ROOT/'release_manifest.json') if (ROOT/'release_manifest.json').exists() else None},
            'split_exposure':{'matching':'exact_original_Unicode_sentence_SHA256_only_no_silent_normalization',
                'any_training_sentence_match':any('train' in v['exact_release_splits'] for v in by_line),'lines':by_line,
                'unmatched_is_not_proof_of_semantic_or_recording_independence':True},
            'validation_status':'generated_candidate_not_human_validated','human_reviewed':False,
            'poem':{'title':title,'author':author,'form':form,'lines':lines,'source':source},
            'input':{'original_text':text,'labels':labels,'requested_model':model},
            'playback':{'line_gap_s':gap,'is_measured_pause':False,'instrument':'deterministic_harmonic_flute'},
            'model_score':score,'edits':[],'runtime':{'Python':platform.python_version(),'NumPy':np.__version__}}
        project['score_id']=project_digest(project);validate_project(project)
        return project
