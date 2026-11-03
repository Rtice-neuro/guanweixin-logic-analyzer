"""Build acceptance evidence from the currently saved local records."""
import hashlib
import json
from datetime import datetime

RULE_MODE = {'MISSING_PULSE': 1, 'PERIOD': 2}
CONFIG_KEYS = ('divider', 'mask', 'value', 'trigger', 'monitor', 'pmin', 'pmax', 'missing')

def _mode(record, fault):
    code = fault.get('code')
    if code in RULE_MODE:
        return RULE_MODE[code]
    if code != 'STUCK':
        return None
    channel = fault.get('channel')
    samples = record.get('samples') or []
    if not isinstance(channel, int) or not samples:
        return None
    levels = {(sample >> channel) & 1 for sample in samples}
    return 3 if levels == {0} else 4 if levels == {1} else None

def _same_profile(a, b):
    if a.get('source') != b.get('source') or a.get('origin') != b.get('origin'):
        return False
    ac, bc = a.get('config') or {}, b.get('config') or {}
    return all(ac.get(key) == bc.get(key) for key in CONFIG_KEYS) and len(a.get('samples') or []) == len(b.get('samples') or [])

def _unchanged_other_channels(current, baseline, target):
    a, b = current.get('samples') or [], baseline.get('samples') or []
    if len(a) != 64 or len(b) != len(a):
        return False
    mask = 0xff ^ (1 << target)
    return all(((x ^ y) & mask) == 0 for x, y in zip(a, b))

def evidence(store):
    """Return live evidence. Never depend on optional archived JSON files."""
    records = store.records()
    records.sort(key=lambda r: r.get('id', 0), reverse=True)
    baselines = [r for r in records if r.get('status') == 'PASS' and not r.get('faults') and len(r.get('samples') or []) == 64]
    cases = []
    for mode in range(1, 5):
        for channel in range(8):
            candidate = next((r for r in records for f in (r.get('faults') or []) if f.get('channel') == channel and _mode(r, f) == mode), None)
            if candidate is None:
                cases.append(dict(mode=mode, channel=channel, attempted=False, passed=False, record_id=None, source=None, fault_index=None, other_channels_unchanged=None, reason='当前数据库没有这组故障的板端回读记录'))
                continue
            fault = next(f for f in candidate.get('faults', []) if f.get('channel') == channel and _mode(candidate, f) == mode)
            base = next((r for r in baselines if _same_profile(candidate, r)), None)
            samples = candidate.get('samples') or []
            valid = candidate.get('status') == 'PASS' and len(samples) == 64
            unchanged = _unchanged_other_channels(candidate, base, channel) if base else None
            passed = bool(valid and unchanged is True)
            reason = '校验通过，目标通道故障已定位，其他七路与同配置正常记录逐点一致' if passed else '找到记录，但缺少同来源同配置正常基准，或回读/七路一致性检查未通过'
            cases.append(dict(mode=mode, channel=channel, attempted=True, passed=passed, record_id=candidate.get('id'), source=candidate.get('source'), origin=candidate.get('origin'), fault_index=fault.get('index'), other_channels_unchanged=unchanged, baseline_record_id=base.get('id') if base else None, reason=reason))
    normal = next((r for r in baselines), None)
    counts = store.latest()
    ai_total = store.diagnoses(limit=1).get('total', 0)
    benchmarks = store.benchmarks()
    snapshots = []
    for r in records:
        samples = r.get('samples') or []
        sample_bytes = bytes(samples) if all(isinstance(x, int) and 0 <= x <= 255 for x in samples) else b''
        snapshots.append({k: r.get(k) for k in ('id', 'received_at', 'board_id', 'origin', 'source', 'status', 'faults', 'config', 'clock_hz', 'checksum', 'analysis', 'trace', 'samples') if k in r})
        snapshots[-1]['sample_sha256'] = hashlib.sha256(sample_bytes).hexdigest() if sample_bytes else None
    latest = records[0] if records else None
    return dict(
        generated_at=datetime.now().astimezone().isoformat(timespec='seconds'),
        evidence_scope='当前本地数据库的板端串口回读记录。INJECTED 表示网页生成的64点样本经UART送入FPGA分析，不代表排针物理输入。',
        capture_count=counts.get('count', len(records)), latest_capture_id=latest.get('id') if latest else None,
        latest_capture_at=latest.get('received_at') if latest else None,
        cases=cases, cases_attempted=sum(c['attempted'] for c in cases), cases_passed=sum(c['passed'] for c in cases),
        coverage_total=32, normal_record_id=normal.get('id') if normal else None,
        ai_cases=ai_total, coremark=benchmarks,
        ila=dict(capture_count=0, imported=False, reason='网站不会自动读取 PDS Fabric Debugger；尚无 PDS 波形文件导入记录。'),
        records=snapshots,
    )

def example(store, mode, channel):
    if not 0 <= mode <= 4 or not 0 <= channel <= 7:
        raise ValueError('样例参数超限')
    e = evidence(store)
    if mode == 0:
        rid = e.get('normal_record_id')
    else:
        case = next((x for x in e['cases'] if x['mode'] == mode and x['channel'] == channel), None)
        rid = case.get('record_id') if case else None
    return store.get(rid) if rid else None

def baseline(store, rid):
    current = store.get(rid)
    if not current:
        raise ValueError('当前记录不存在')
    if not current.get('samples'):
        return dict(record=None, reason='当前记录没有样本')
    cfg = current.get('config', {})
    for r in store.records():
        if r['id'] == rid or r['status'] != 'PASS' or r.get('faults') or r.get('origin') != current.get('origin') or r.get('source') != current.get('source'):
            continue
        if all(r.get('config', {}).get(k) == cfg.get(k) for k in CONFIG_KEYS) and len(r.get('samples', [])) == len(current['samples']):
            return dict(record=store.get(r['id']), matched_fields=list(CONFIG_KEYS), reason='同来源、同采样与规则配置的正常记录；网页注入样本使用虚拟样点网格，不代表排针实时波形')
    return dict(record=None, reason='最近200条记录中没有同来源、同配置的正常基准；先保存一条正常记录')
