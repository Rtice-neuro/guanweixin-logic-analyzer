"""Synthetic periodic-signal corpus. No rule result or scenario ID enters prompts."""
from __future__ import annotations
import hashlib, json, random
from pathlib import Path

LABELS = ['NORMAL', 'MISSING_PULSE', 'PERIOD', 'STUCK_HIGH', 'STUCK_LOW', 'UNKNOWN']
CODES = dict(zip(LABELS, 'ABCDEF'))
PERIODS = {'train': (6, 8, 10, 12), 'validation': (7, 11), 'test': (9, 13)}
SEEDS = {'train': 28001, 'validation': 28002, 'test': 28003}


def summarize(bits, expected_period):
    if len(bits) != 64 or any(type(x) is not int or x not in (0, 1) for x in bits):
        raise ValueError('Expected exactly 64 binary samples')
    if type(expected_period) is not int or not 4 <= expected_period <= 16:
        raise ValueError('Expected period must be 4..16 samples; out-of-domain otherwise')
    rises = [i for i in range(1, 64) if bits[i] and not bits[i-1]]
    gaps = [b-a for a, b in zip(rises, rises[1:])]
    edges = sum(a != b for a, b in zip(bits, bits[1:]))
    # Integer ratios (16 means the configured expected period), saturated at 63.
    # Context includes no acquisition mode, injected channel or CPU diagnosis.
    relative = [min(63, (16*g + expected_period//2)//expected_period) for g in gaps]
    text = f'h{sum(bits)} e{edges} g' + ','.join(map(str, relative)) + '\nanswer:'
    return dict(prompt=text, high_samples=sum(bits), edges=edges, rises=rises,
                gaps=gaps, relative_gaps=relative, expected_period=expected_period)


def rule_baseline(bits, expected_period):
    """Independent simple reference, NOT a training teacher nor production firmware."""
    s = summarize(bits, expected_period)
    if s['high_samples'] == 64: return 'STUCK_HIGH'
    if s['high_samples'] == 0: return 'STUCK_LOW'
    if len(s['gaps']) < 2: return 'UNKNOWN'
    if any(g*100 >= expected_period*160 for g in s['gaps']): return 'MISSING_PULSE'
    if any(g*100 < expected_period*75 or g*100 > expected_period*125 for g in s['gaps']): return 'PERIOD'
    return 'NORMAL'


def make_case(rng, period, label):
    if label.startswith('STUCK_'):
        bits = [int(label == 'STUCK_HIGH')]*64
    elif label == 'UNKNOWN':
        # Sparse finite bursts or irregular events are outside the periodic contract.
        bits = [0]*64
        if rng.random() < .5:
            start = rng.randrange(8, 48)
            width = rng.randrange(2, 12)
            bits = [int(start <= i < start + width) for i in range(64)]
        else:
            level = rng.randrange(2)
            for i in range(64):
                if rng.random() < .4: level ^= 1
                bits[i] = level
    else:
        phase = rng.uniform(-period, 0)
        duty = rng.uniform(.20, .65)
        starts = [phase + k*period for k in range(14) if phase+k*period < 64]
        starts = [x + rng.uniform(-.025, .025)*period for x in starts]
        if label == 'MISSING_PULSE':
            interior = [i for i, t in enumerate(starts) if period < t < 64-period]
            del starts[rng.choice(interior)]
        elif label == 'PERIOD':
            interior = [i for i, t in enumerate(starts) if period < t < 64-period]
            i = rng.choice(interior)
            starts[i] += rng.choice((-1, 1))*rng.uniform(.34, .48)*period
            starts.sort()
        bits = [int(any(t <= i < t + max(1, duty*period) for t in starts)) for i in range(64)]
        # Reject injection cases whose fault disappears due to digital sampling.
        if label == 'MISSING_PULSE' and not any(g >= period*1.6 for g in summarize(bits, period)['gaps']):
            return make_case(rng, period, label)
        if label == 'PERIOD' and not any(g < period*.75 or g > period*1.25 for g in summarize(bits, period)['gaps']):
            return make_case(rng, period, label)
    s = summarize(bits, period)
    return dict(samples=bits, label=label, answer=CODES[label], **s)


def write_corpus(root, per_class=600):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    manifest = dict(provenance='SYNTHETIC_ONLY', real_external_training=False,
                    split_policy='Disjoint nominal-period groups and independent seeds; periodic captures only.',
                    label_source='Generator event, not production rule output',
                    no_model_inputs=['scenario', 'injected_channel', 'rule_faults', 'filename', 'label'], splits={})
    for split, periods in PERIODS.items():
        rng = random.Random(SEEDS[split]); count = per_class if split == 'train' else max(120, per_class//5)
        cases = []
        for label in LABELS:
            for _ in range(count): cases.append(make_case(rng, rng.choice(periods), label))
        rng.shuffle(cases)
        for i, case in enumerate(cases): case['id'] = f'{split}-{i:05d}'
        raw = ''.join(json.dumps(c, ensure_ascii=False, separators=(',', ':'))+'\n' for c in cases)
        p = root/(split+'.jsonl'); p.write_text(raw, encoding='utf-8')
        manifest['splits'][split] = dict(rows=len(cases), periods=list(periods), seed=SEEDS[split], sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    return manifest
