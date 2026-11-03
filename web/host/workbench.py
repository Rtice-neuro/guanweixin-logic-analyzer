"""Original local instrument workbench, inspired by professional analyzer workflows."""
import json
from pathlib import Path

ASSETS = Path(__file__).with_name('assets')


def safe_json(value):
    return json.dumps(value, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def render_page(store, worker, token, selected=None, query='', enable_benchmarks=False, waveform=None):
    rows = store.records()
    record = store.get(selected) if selected else (rows[0] if rows else None)
    payload = dict(record=record, history=[{k:v for k,v in r.items() if k in ('id','received_at','origin','source','status','faults','config')} for r in rows], query=query)
    template = (ASSETS/'index.html').read_text(encoding='utf-8')
    bootstrap = 'const token='+safe_json(token)+';const benchmarkEnabled='+safe_json(enable_benchmarks)+';const bootstrap='+safe_json(payload)+';'
    template = template.replace('<!--BOOTSTRAP-->', bootstrap)
    return template.replace('<!--INITIAL_WAVE-->', waveform(record) if record and waveform else '<p class="empty">等待有效采集记录。连接串口并同步设备，或导入已有记录。</p>')
