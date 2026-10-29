"""Continuous score display and deterministic instrumental interchange."""
from __future__ import annotations
import html
import io
import math
import statistics
import wave
from xml.etree import ElementTree as ET
from .contract import validate_project
from .vendor.score_contract import interpolate_cents
from .vendor.score_formats import write_midi,pitch_node,DIVISIONS

SAMPLE_RATE=22050


def export_runs(project):
    rendered=validate_project(project);offset=0.;runs=[];missing=[]
    for li,line in enumerate(rendered['lines'],1):
        for char in line['characters']:
            if not char['pitch_runs']:missing.append({'line':li,'position':char['position'],'character':char['character']})
            for run in char['pitch_runs']:
                count=max(1,math.ceil((run['end_s']-run['start_s'])/.01-1e-10))
                t=[run['start_s']+.01*i for i in range(count)]
                hz=[interpolate_cents(run['points'],value) for value in t]
                runs.append({'start_s':run['start_s']+offset,'end_s':run['end_s']+offset,
                    'time_s':[value+offset for value in t],'Hz':hz,'reference_Hz':hz,
                    'character':char['character'],'line':li,'position':char['position']})
        offset+=line['duration_s']+rendered['line_gap_s']
    return runs,rendered,{'synthetic_audition_grid_hop_s':.01,'not_measured_reference_frames':True,
        'characters_without_pitch_support':missing,'line_gap_is_playback_control':True}


def to_midi(project):
    runs,rendered,info=export_runs(project);data,quantized=write_midi(runs,rendered['duration_s'])
    return data,{**info,'MIDI_source_points':quantized['source_points'],'MIDI_encoded_points':quantized['encoded_points'],
        'MIDI_dropped_points':quantized['dropped_points'],'MIDI_skipped_runs':quantized['skipped_runs'],
        'bend_range_semitones':quantized['bend_range_semitones']}


def to_musicxml(project):
    rendered=validate_project(project);root=ET.Element('score-partwise',version='4.0')
    work=ET.SubElement(root,'work');ET.SubElement(work,'work-title').text=project['poem']['title']+' · 候选吟诵谱'
    ident=ET.SubElement(root,'identification');ET.SubElement(ident,'creator',type='composer').text='PoemChant local, frozen research model'
    plist=ET.SubElement(root,'part-list');part=ET.SubElement(plist,'score-part',id='P1');ET.SubElement(part,'part-name').text='Instrumental note approximation'
    part=ET.SubElement(root,'part',id='P1');offset=0.;dropped=0;lyrics=0
    for li,line in enumerate(rendered['lines']):
        measure=ET.SubElement(part,'measure',number=str(li+1),implicit='yes')
        if li==0:
            attributes=ET.SubElement(measure,'attributes');ET.SubElement(attributes,'divisions').text=str(DIVISIONS)
            ET.SubElement(ET.SubElement(attributes,'time'),'senza-misura')
            direction=ET.SubElement(measure,'direction');ET.SubElement(ET.SubElement(direction,'direction-type'),'words').text='Free time; pitch is a note approximation; rests are playback controls, not measured pauses.'
            ET.SubElement(direction,'sound',tempo='60')
        for char in line['characters']:
            spans=[];cursor=char['start_s']
            for run in char['pitch_runs']:
                if run['start_s']>cursor+1e-10:spans.append((cursor,run['start_s'],None))
                if run['end_s']>run['start_s']+1e-10:
                    count=max(1,math.ceil((run['end_s']-run['start_s'])/.01))
                    values=[69+12*math.log2(interpolate_cents(run['points'],run['start_s']+.01*i)/440) for i in range(count)]
                    spans.append((run['start_s'],run['end_s'],round(statistics.median(values))))
                cursor=run['end_s']
            if char['end_s']>cursor+1e-10:spans.append((cursor,char['end_s'],None))
            if not spans:spans=[(char['start_s'],char['end_s'],None)]
            wrote_lyric=False
            for start,end,note in spans:
                ticks=round((offset+end)*DIVISIONS)-round((offset+start)*DIVISIONS)
                if ticks<=0:dropped+=1;continue
                node=ET.SubElement(measure,'note')
                if note is None:ET.SubElement(node,'rest')
                elif 0<=note<=127:pitch_node(node,note)
                else:raise ValueError('音符近似超出支持音区。')
                ET.SubElement(node,'duration').text=str(ticks)
                if not wrote_lyric:
                    lyric=ET.SubElement(node,'lyric');ET.SubElement(lyric,'text').text=char['character'];wrote_lyric=True;lyrics+=1
            if not wrote_lyric:raise ValueError('时值量化不能保留原字，未导出不完整文件。')
        end=offset+line['duration_s']
        if li<len(rendered['lines'])-1:
            gap=round((end+rendered['line_gap_s'])*DIVISIONS)-round(end*DIVISIONS)
            if gap:
                node=ET.SubElement(measure,'note');ET.SubElement(node,'rest');ET.SubElement(node,'duration').text=str(gap)
        offset=end+rendered['line_gap_s']
    ET.indent(root)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True),{'MusicXML_lyrics':lyrics,'MusicXML_zero_tick_spans_dropped':dropped,
        'pitch_semantics':'nearest12TET time-sampled median per contiguous generated curve run','rests_are_measured_silence':False}


def to_wav(project):
    import numpy as np
    rendered=validate_project(project);count=round(rendered['duration_s']*SAMPLE_RATE)
    signal=np.zeros(count,dtype=np.float64);offset=0.
    for line in rendered['lines']:
        for char in line['characters']:
            for run in char['pitch_runs']:
                first=round((offset+run['start_s'])*SAMPLE_RATE);last=min(count,round((offset+run['end_s'])*SAMPLE_RATE))
                n=last-first
                if n<=0:continue
                local=run['start_s']+np.arange(n)/SAMPLE_RATE
                points=np.array(run['points'],dtype=float)
                hz=2**np.interp(local,points[:,0],np.log2(points[:,1]))
                phase=2*np.pi*np.cumsum(hz)/SAMPLE_RATE
                audio=(np.sin(phase)+.18*np.sin(2*phase)+.05*np.sin(3*phase))*(.6/1.23)
                envelope=np.minimum(1,np.arange(n)/(SAMPLE_RATE*.01))
                envelope=np.minimum(envelope,(n-1-np.arange(n))/(SAMPLE_RATE*.035))
                signal[first:last]+=audio*np.maximum(0,envelope)
        offset+=line['duration_s']+rendered['line_gap_s']
    if np.max(np.abs(signal),initial=0)>1:raise ValueError('试听信号超出范围，未进行静默截幅。')
    pcm=np.rint(signal*32767).astype('<i2').tobytes();buffer=io.BytesIO()
    with wave.open(buffer,'wb') as handle:
        handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(SAMPLE_RATE);handle.writeframes(pcm)
    return buffer.getvalue(),{'sample_rate':SAMPLE_RATE,'samples':count,'channels':1,'sample_width_bytes':2,
        'duration_s':count/SAMPLE_RATE,'instrument':'deterministic_harmonic_flute','voice_synthesis':False,
        'maximum_absolute_sample_fraction':float(np.max(np.abs(signal),initial=0))}


def to_svg(project):
    rendered=validate_project(project);escape=html.escape;width=1200
    title=project['poem']['title'];title_lines=[title[i:i+38] for i in range(0,len(title),38)] or ['未题名']
    author=project['poem']['author'];author_lines=[author[i:i+65] for i in range(0,len(author),65)] or ['未署名']
    header=100+len(title_lines)*34+len(author_lines)*20;height=header+len(rendered['lines'])*210+65
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#faf9f5"/>',
        '<style>text{font-family:"Songti SC","Noto Serif CJK SC",serif;fill:#243d37}.small{font-family:system-ui,sans-serif;font-size:13px;fill:#64716c}</style>']
    y=42
    for line in title_lines:parts.append(f'<text x="54" y="{y}" font-size="28">{escape(line)}</text>');y+=34
    for line in author_lines:parts.append(f'<text x="55" y="{y}" class="small">{escape(line)}</text>');y+=20
    parts.append(f'<text x="55" y="{y+7}" class="small">候选连续吟诵谱 · 器乐示意 · 未经人工审校'+(' · 含自行修改' if project['edits'] else '')+'</text>')
    all_pitch=[12*math.log2(h/440)+69 for line in rendered['lines'] for char in line['characters'] for run in char['pitch_runs'] for _,h in run['points']]
    lower=min(all_pitch,default=60)-1;upper=max(all_pitch,default=64)+1
    if upper-lower<6:middle=(lower+upper)/2;lower,upper=middle-3,middle+3
    for li,line in enumerate(rendered['lines']):
        top=header+li*210;scale=1080/line['duration_s'];yp=lambda h:top+94-(69+12*math.log2(h/440)-lower)/(upper-lower)*80
        for fraction in [0,.5,1]:parts.append(f'<path d="M55 {top+14+fraction*80:.3f} H1135" stroke="#dce2dc" fill="none"/>')
        desired=[55+(c['start_s']+c['end_s'])/2*scale for c in line['characters']];label=[]
        for x in desired:label.append(max(x,label[-1]+74 if label else 88))
        if label and label[-1]>1100:
            label[-1]=1100
            for i in range(len(label)-2,-1,-1):label[i]=min(label[i],label[i+1]-74)
        for ci,char in enumerate(line['characters']):
            x0=55+char['start_s']*scale;x1=55+char['end_s']*scale;xm=(x0+x1)/2;lx=label[ci]
            color='#ae6a37' if char['edited'] or char['model_uncertainty']['input']['ambiguous_or_unknown'] else '#26706b'
            parts.append(f'<path d="M{x0:.3f} {top+9} v91" stroke="#d4ddd5" stroke-dasharray="3 4"/>')
            for run in char['pitch_runs']:
                points=' '.join(f'{55+t*scale:.4f},{yp(h):.4f}' for t,h in run['points'])
                if len(run['points'])==1:parts.append(f'<circle cx="{55+run["points"][0][0]*scale:.4f}" cy="{yp(run["points"][0][1]):.4f}" r="2.5" fill="{color}"/>')
                else:parts.append(f'<polyline points="{points}" stroke="{color}" stroke-width="2.6" fill="none"/>')
            parts.append(f'<path d="M{xm:.3f} {top+103} L{lx:.3f} {top+119}" stroke="#ccd5cf" fill="none"/>')
            parts.append(f'<text data-character="{escape(char["character"],quote=True)}" x="{lx:.3f}" y="{top+147}" text-anchor="middle" font-size="29">{escape(char["character"])}</text>')
            p=char['phonology'];reading=p['pinyin_candidates'][0] if len(p['pinyin_candidates'])==1 else '读音待核对'
            parts.append(f'<text class="small" x="{lx:.3f}" y="{top+170}" text-anchor="middle">{escape(reading)} · {escape(p["selected_historical"] or "?")}</text>')
            parts.append(f'<text class="small" x="{lx:.3f}" y="{top+189}" text-anchor="middle">{1000*(char["end_s"]-char["start_s"]):.0f} ms</text>')
        parts.append(f'<text class="small" x="1135" y="{top+207}" text-anchor="end">{line["duration_s"]:.2f} 秒 · 横轴为本句时间</text>')
    footer=height-38
    parts.append(f'<text class="small" x="55" y="{footer}">橙色表示读音疑点或自行修改。模型时长范围及修改记录保存在工程JSON中；句间间隔是试听控制。</text>')
    parts.append(f'<text class="small" x="55" y="{footer+20}">模型 {escape(project["model_id"])} · 谱号 {project["score_id"][:16]} · 连续曲线不是历史吟调复原或人声。</text></svg>')
    return '\n'.join(parts).encode()
