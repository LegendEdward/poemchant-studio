"""Candidate dictionary lookup; neither contextual ancient readings nor ground truth."""
from functools import lru_cache
import json
from pathlib import Path
import re
from opencc import OpenCC
from pypinyin import Style, pinyin

TONE_MAP = {'上平声部': '平', '下平声部': '平', '上声部': '上', '去声部': '去', '入声部': '入'}
PINYIN = re.compile(r'[a-züv:]+[1-5]')


@lru_cache(maxsize=1)
def lexicon():
    resource = Path(__file__).parent / 'resources' / 'Pingshui_Rhyme.json'
    data = json.loads(resource.read_text(encoding='utf-8'))
    index = {}
    for section, rhymes in data.items():
        for rhyme, chars in rhymes.items():
            for char in chars:
                if len(char) != 1:
                    continue
                item = {'tone': TONE_MAP[section], 'group': section + '/' + rhyme}
                if item not in index.setdefault(char, []):
                    index[char].append(item)
    return index, OpenCC('s2t'), OpenCC('t2s')


def readings(text):
    index, s2t, t2s = lexicon()
    context = pinyin(text, style=Style.TONE3, neutral_tone_with_five=True, errors=lambda s: list(s))
    result = []
    for i, char in enumerate(text):
        variants = pinyin(char, style=Style.TONE3, heteronym=True, neutral_tone_with_five=True)[0]
        selected = context[i][0] if i < len(context) else None
        selected = selected if selected and PINYIN.fullmatch(selected) else None
        variants = list(dict.fromkeys(([selected] if selected else []) + [v for v in variants if PINYIN.fullmatch(v)]))
        candidates = list(index.get(char, []))
        proxy = None
        if not candidates:
            for converted in dict.fromkeys([s2t.convert(char), t2s.convert(char)]):
                for item in index.get(converted, []):
                    if item not in candidates:
                        candidates.append(item)
                        proxy = converted
        tones = list(dict.fromkeys(c['tone'] for c in candidates))
        result.append({'character': char, 'pinyin': selected, 'pinyin_candidates': variants,
                       'modern_tone': selected[-1] if selected else None,
                       'historical_tone': tones[0] if len(tones) == 1 else None,
                       'historical_candidates': tones, 'rhyme_candidates': candidates,
                       'lookup_proxy': proxy, 'source': 'pypinyin_context_and_secondary_pingshui_transcription',
                       'needs_review': len(variants) != 1 or len(tones) != 1 or len(candidates) != 1 or proxy is not None})
    return result
