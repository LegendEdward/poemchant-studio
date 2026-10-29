"""Editable project contract. Model predictions remain immutable references."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from .vendor.score_contract import validate_semantics

VERSION='PoemChantProject1.0'


def canonical_value(item):
    # JSON browsers coalesce 0.0/0 and discard negative zero. Preserve numeric
    # values, not incidental Python-versus-JavaScript spelling or object order.
    if type(item) is float:
        if not math.isfinite(item):raise ValueError('工程含非有限数字。')
        return int(item) if item.is_integer() else item
    if isinstance(item,list):return [canonical_value(v) for v in item]
    if isinstance(item,dict):return {k:canonical_value(v) for k,v in item.items()}
    return item


def encoded(value):
    return json.dumps(canonical_value(value),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def identity(value):return hashlib.sha256(encoded(value)).hexdigest()


def number(value,low,high,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        raise ValueError(f'{label}须在{low:g}至{high:g}之间。')
    return float(value)


def parse_text(text):
    if not isinstance(text,str) or not text.strip():raise ValueError('请先输入古诗正文。')
    if len(text)>2000:raise ValueError('正文过长；目前支持四句或八句五言、七言诗。')
    lines=[s.strip() for s in re.split(r'[\n\r，。！？；,;!?]+',text) if s.strip()]
    if len(lines) not in (4,8):raise ValueError('请输入完整四句或八句诗，每句五字或七字。')
    length=len(lines[0])
    if length not in (5,7) or any(len(line)!=length for line in lines):raise ValueError('每句须同为五字或同为七字；请把题名、作者放在对应栏中。')
    if any(not re.fullmatch(r'[\u3400-\u9fff\uf900-\ufaff]+',line) for line in lines):
        raise ValueError('正文含当前不支持的字符或句内空格；原字未被替换，请核对输入。')
    return lines,('wu' if length==5 else 'qi')+('jue' if len(lines)==4 else 'lu')


def normalize_edits(edits,lines):
    if edits is None:return []
    if not isinstance(edits,list) or len(edits)>56:raise ValueError('修改记录格式不正确。')
    output=[];seen=set()
    for edit in edits:
        if not isinstance(edit,dict) or set(edit)-{'line','position','character','duration_ms','pitch_points'}:
            raise ValueError('修改记录含不支持的字段。')
        li,ci=edit.get('line'),edit.get('position')
        if type(li) is not int or type(ci) is not int or not 1<=li<=len(lines) or not 1<=ci<=len(lines[li-1]):raise ValueError('修改位置不在原诗内。')
        key=(li,ci)
        if key in seen:raise ValueError('同一字出现重复修改。')
        seen.add(key)
        if edit.get('character')!=lines[li-1][ci-1]:raise ValueError('修改记录的原字与正文不符，未应用旧修改。')
        value={'line':li,'position':ci,'character':edit['character']}
        if 'duration_ms' in edit:value['duration_ms']=number(edit['duration_ms'],50,5000,'字长（毫秒）')
        if 'pitch_points' in edit:
            points=edit['pitch_points']
            if not isinstance(points,list) or not 1<=len(points)<=32:raise ValueError('每字须有1至32个音高控制点。')
            previous=-1.;clean=[]
            for point in points:
                if not isinstance(point,list) or len(point)!=2:raise ValueError('音高控制点格式应为[相位,Hz或null]。')
                phase=number(point[0],0,1,'控制点相位')
                if phase<=previous:raise ValueError('控制点相位须严格递增。')
                hz=None if point[1] is None else number(point[1],30,2000,'音高（Hz）')
                clean.append([phase,hz]);previous=phase
            value['pitch_points']=clean
        if len(value)>3:output.append(value)
    return sorted(output,key=lambda v:(v['line'],v['position']))


def effective_score(project):
    """Render model or edited values without recentering any model interval."""
    score=project['model_score'];edits={(v['line'],v['position']):v for v in project['edits']};lines=[]
    for li,line in enumerate(score['lines'],1):
        cursor=0.;characters=[]
        for char in line['characters']:
            edit=edits.get((li,char['position']),{});old_start=char['start_s'];old_d=char['end_s']-old_start
            duration=edit.get('duration_ms',old_d*1000)/1000
            if 'pitch_points' in edit:
                runs=[];current=[]
                for point in edit['pitch_points']+[None]:
                    if point is not None and point[1] is not None:current.append([cursor+duration*point[0],point[1]])
                    elif current:
                        runs.append({'start_s':current[0][0],'end_s':current[-1][0],'points':current});current=[]
            else:
                runs=[{'start_s':cursor+(run['start_s']-old_start)/old_d*duration,
                    'end_s':cursor+(run['end_s']-old_start)/old_d*duration,
                    'points':[[cursor+(t-old_start)/old_d*duration,hz] for t,hz in run['points']]} for run in char['pitch']['runs']]
            characters.append({'character':char['character'],'position':char['position'],'start_s':cursor,'end_s':cursor+duration,
                'pitch_runs':runs,'phonology':copy.deepcopy(char['phonology']),'model_uncertainty':copy.deepcopy(char['uncertainty']),
                'edited':bool(edit),'model_interval_applies_to_edited_value':False})
            cursor+=duration
        lines.append({'text':line['text'],'duration_s':cursor,'characters':characters})
    duration=sum(line['duration_s'] for line in lines)+project['playback']['line_gap_s']*(len(lines)-1)
    if duration>180:raise ValueError('总试听时间超过180秒，请缩短字长或提高速度。')
    return {'kind':'user_edited_candidate' if edits else 'model_prediction_candidate','lines':lines,'duration_s':duration,
        'line_gap_s':project['playback']['line_gap_s'],'gap_semantics':'playback_control_not_measured_pause',
        'calibration_reference':'immutable model_score only; edited values have no calibrated coverage claim'}


def project_digest(project):
    return identity({k:v for k,v in project.items() if k not in ('score_id','validation_status')})


def validate_project(project):
    if not isinstance(project,dict) or project.get('schema')!=VERSION or project.get('schema_version')!='1.0':raise ValueError('不是支持的可编辑吟诵谱工程。')
    required={'schema','schema_version','poem_id','score_id','model_id','parameter_status','source_hashes','split_exposure','validation_status','human_reviewed','poem','input','playback','model_score','edits','runtime'}
    if set(project)!=required:raise ValueError('工程字段缺失或版本不匹配。')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,80}',project['poem_id']):raise ValueError('诗篇编号不安全。')
    if project['human_reviewed'] is not False or project['model_score']['human_verified'] is not False:raise ValueError('本版本不接受伪造的人工审核状态。')
    lines,form=parse_text(project['input']['original_text'])
    if lines!=project['poem']['lines'] or project['poem']['form']!=form:raise ValueError('工程原文与分句不一致。')
    if [line['text'] for line in project['model_score']['lines']]!=lines:raise ValueError('模型原稿中的原字不一致。')
    validate_semantics(project['model_score'])
    for line in project['model_score']['lines']:
        for char in line['characters']:
            phonology=char['phonology']
            for field,allowed in [('selected_historical',{'平','上','去','入',None}),
                                  ('selected_modern_tone',set('012345')|{None}),
                                  ('raw_rhyme',set('0123')|{None})]:
                if phonology[field] not in allowed:raise ValueError('未知读音或韵标记须用空值保留。')
    normalized=normalize_edits(project['edits'],lines)
    if normalized!=project['edits']:raise ValueError('修改记录不符合规范。')
    number(project['playback']['line_gap_s'],0,3,'句间试听间隔')
    if project['playback'].get('is_measured_pause') is not False:raise ValueError('试听间隔不是测量停顿。')
    if project['source_hashes']['input_text_sha256']!=hashlib.sha256(project['input']['original_text'].encode()).hexdigest():raise ValueError('原文字节散列不一致。')
    if project['source_hashes']['model_score_sha256']!=identity(project['model_score']):raise ValueError('模型原稿已被改动，请以修改记录编辑。')
    if project['score_id']!=project_digest(project):raise ValueError('工程内容与编号不一致。')
    rendered=effective_score(project)
    for line in rendered['lines']:
        previous=0.
        for char in line['characters']:
            if char['start_s']<previous-1e-8 or not char['start_s']<char['end_s']:raise ValueError('编辑后的时间轴重叠。')
            previous_run=char['start_s']
            for run in char['pitch_runs']:
                if not char['start_s']-1e-8<=run['start_s']<=run['end_s']<=char['end_s']+1e-8 or run['start_s']<previous_run-1e-8:raise ValueError('曲线支持时间不正确。')
                for t,h in run['points']:
                    if not math.isfinite(t) or not math.isfinite(h) or h<=0 or not run['start_s']-1e-8<=t<=run['end_s']+1e-8:raise ValueError('曲线控制点不合法。')
                previous_run=run['end_s']
            previous=char['end_s']
    json.dumps(project,allow_nan=False)
    return rendered


def edit_project(project,edits,line_gap_s=None):
    validate_project(project);result=copy.deepcopy(project)
    result['edits']=normalize_edits(edits,project['poem']['lines'])
    if line_gap_s is not None:result['playback']['line_gap_s']=number(line_gap_s,0,3,'句间试听间隔')
    result['validation_status']='generated_candidate_not_human_validated'
    result['score_id']=project_digest(result);validate_project(result)
    return result
