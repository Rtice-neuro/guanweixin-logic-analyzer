"""Validate request/response instruction fetch against the independent RV32I model.

Preserves all legacy RTL/results. Includes explicit instruction-bus faults and
reset races. This is functional RTL evidence, not official ISA certification or
an FPGA timing/benchmark result.
"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import firmware
import verify


def directed_programs():
    tests = {'directed': (firmware.directed().resolve(), None, 0)}
    for seed in (7, 42, 2026):
        tests[f'random_{seed}'] = (firmware.random_program(seed).resolve(), None, 0)
    for name, op, off in (
        ('misaligned_lw', 'lw', 1), ('misaligned_sh', 'sh', 1),
        ('unmapped_load', 'lw', 1024), ('unmapped_store', 'sw', 1024),
    ):
        p = firmware.Program(); p.li(28, 0x10000000); p.emit(op, 1, 28, off)
        tests[name] = (p.resolve(), None, 0)
    for name, word in (
        ('illegal', 0xffffffff), ('illegal_shift', 0x02001013),
        ('illegal_jalr', 0x00001067), ('ecall', 0x00000073),
        ('bad_jump', 0x0020006f),
    ):
        tests[name] = ([word], None, 0)

    # Architecturally correct paths never execute the deliberately faulting
    # sequential address. The bus event log proves whether a speculative fault
    # response was actually observed; absence of such a request is not a fault.
    for kind in ('beq', 'jal', 'jalr'):
        p = firmware.Program(); p.li(28, 0x10000000); p.li(6, 0x1357)
        if kind == 'jalr':
            target_reg_index = len(p.items)
            p.li(5, 24); p.emit('jalr', 1, 5, 0)
        elif kind == 'jal':
            p.emit('jal', 1, 'target')
        else:
            p.emit('beq', 0, 0, 'target')
        fault = p.pc
        p.emit('sw', 6, 28, 0)
        p.label('target'); p.emit('sw', 6, 28, 4); p.emit('ebreak')
        if kind == 'jalr':
            # The exact target is computed after the constant's 1-instruction
            # encoding and branch slot have been laid out.
            p.items[target_reg_index] = ('addi', (5, 0, p.labels['target']))
        tests[f'wrong_path_fault_{kind}'] = (p.resolve(), fault, 0)

    # A delayed load permits a returned branch to occupy the fetch buffer while
    # a faulting sequential response waits behind it. Redirect must discard
    # both in-flight and already-buffered wrong-path errors.
    p = firmware.Program(); p.li(28, 0x10000000); p.li(6, 0x1357)
    p.emit('sw', 6, 28, 0); p.emit('lw', 7, 28, 0)
    p.emit('beq', 7, 6, 'target'); fault = p.pc
    p.emit('sw', 0, 28, 0)
    p.label('target'); p.emit('sw', 7, 28, 4); p.emit('ebreak')
    tests['wrong_path_fault_after_delayed_load'] = (p.resolve(), fault, 0)

    # These fault addresses contain EBREAK, so the legacy independent reference
    # already stops before retiring them. Only the expected cause changes to 1.
    p = firmware.Program(); p.li(28, 0x10000000); p.li(6, 77)
    p.emit('sw', 6, 28, 0); fault = p.pc; p.emit('ebreak')
    tests['fetch_fault_precise_after_store'] = (p.resolve(), fault, 0)
    p = firmware.Program(); p.emit('jal', 1, 'fault'); p.emit('sw', 0, 0, 0)
    p.label('fault'); fault = p.pc; p.emit('ebreak')
    tests['fetch_fault_jal_target'] = (p.resolve(), fault, 0)
    tests['fetch_fault_first_instruction'] = ([0x00100073], 0, 0)

    for phase in (1, 2, 3):
        p = firmware.Program(); p.li(28, 0x10000000); p.li(6, 0x2345)
        p.emit('sw', 6, 28, 0); p.emit('lw', 7, 28, 0)
        p.emit('addi', 0, 7, 1); p.emit('ebreak')
        tests[f'reset_phase_{phase}'] = (p.resolve(), None, phase)
    return tests


def parse_trace(path):
    rows = []
    for line in path.read_text().splitlines():
        row = line.split(',')
        rows.append((int(row[0], 16), int(row[1], 16), int(row[2]),
                     int(row[3]), int(row[4], 16)))
    return rows

def reference_final_ram(trace):
    # Replay stores using the independent model's architectural results, not
    # the DUT's addresses/data. Check every byte, including untouched words.
    registers=[0]*32; memory=bytearray(1024)
    for pc,insn,we,rd,value in trace:
        if insn&0x7f==0x23:
            rs1=(insn>>15)&31; rs2=(insn>>20)&31; f3=(insn>>12)&7
            immediate=((insn>>25)<<5)|((insn>>7)&31)
            if immediate&0x800: immediate-=0x1000
            address=(registers[rs1]+immediate)&0xffffffff
            count={0:1,1:2,2:4}[f3]
            offset=address-0x10000000
            if not 0<=offset<=1024-count: raise AssertionError('Reference store outside RAM')
            memory[offset:offset+count]=registers[rs2].to_bytes(4,'little')[:count]
        if we and rd: registers[rd]=value&0xffffffff
    return [int.from_bytes(memory[i:i+4],'little') for i in range(0,1024,4)]


def run_case(name, words, fault, reset_phase, seed, delay, data_delay, out, vvp):
    expected, trap, writes = verify.reference(words)
    if fault is not None:
        # A fetch fault is architecturally executed iff its PC occurs in the
        # reference trace, or it is the terminating EBREAK's PC. For these
        # explicit cases every real-path fault is at the ending EBREAK.
        if not name.startswith('wrong_path_'):
            trap = 1
    folder = out / f'{name}_seed{seed}_delay{delay}'
    folder.mkdir(exist_ok=True)
    for name_generated in ['core_trace.csv','instruction_bus.csv','ram_final.hex']:
        (folder/name_generated).unlink(missing_ok=True)
    assert len(words) <= 2048
    padded = words + [0xffffffff] * (2048 - len(words))
    (folder / 'program.hex').write_text(''.join(f'{w:08x}\n' for w in padded), encoding='ascii')
    args = [vvp, out / 'core_sync.vvp', '+HEX=program.hex', f'+TRAP={trap}',
            f'+SEED={seed}', f'+MAX_DELAY={delay}', f'+RESET_PHASE={reset_phase}']
    args.append(f'+DATA_DELAY={data_delay}')
    if fault is not None:
        args.append(f'+FAULT_ADDR={fault:08x}')
    output = verify.run(args, folder, folder / 'simulation.log')
    actual = parse_trace(folder / 'core_trace.csv')
    assert len(actual) == len(expected), (name, seed, 'trace length', len(actual), len(expected))
    for index, (got, want) in enumerate(zip(actual, expected)):
        assert got[:3] == want[:3] and (not want[2] or got[3:] == want[3:]), (name, seed, index, got, want)
    metrics = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', output)}
    assert metrics['writes'] == writes, (name, seed, 'duplicate/missing stores', metrics['writes'], writes)
    assert metrics['retired'] == len(expected), (name, seed, 'retirement counter', metrics['retired'], len(expected))
    if (out.parent.name=='sync_v04'):
        final=[int(x,16) for x in (folder/'ram_final.hex').read_text().split()]
        assert final==reference_final_ram(expected), (name,seed,'final RAM byte mismatch')
    return {'test': name, 'latency_seed': seed, 'maximum_response_delay': delay,
            'maximum_data_delay': data_delay,
            'retirements_compared': len(actual), 'stores': writes, 'expected_trap': trap,
            'injected_fault_address': fault, 'reset_phase': reset_phase,
            'final_ram_words_compared':256 if out.parent.name=='sync_v04' else 0,
            'metrics': metrics, 'pass': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--random-programs', type=int, default=100)
    parser.add_argument('--directed-only', action='store_true')
    parser.add_argument('--version',choices=['v03','v04'],default='v03')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    out = ROOT / ('results/sync_'+args.version) / 'cpu'
    out.mkdir(parents=True, exist_ok=True)
    target = out / 'verification.json'
    core = ROOT / ('rtl_'+args.version) / 'gwx_core_sync.v'
    bench=ROOT/'sim'/('tb_core_sync.v' if args.version=='v03' else 'tb_core_turnover.v')
    report = {'started_utc': datetime.now(timezone.utc).isoformat(), 'all_pass': False,'version':args.version,
              'scope': 'Synchronous instruction request/response RTL, independent RV32I retirement model, random instruction/data delays, precise fetch faults, reset races; not official ISA certification or FPGA hardware.',
              'core_sha256': hashlib.sha256(core.read_bytes()).hexdigest(),
              'testbench_sha256':hashlib.sha256(bench.read_bytes()).hexdigest(),
              'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'checks': []}
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    iv, vvp = verify.find_tools()
    verify.run([iv, '-g2012', '-Wall', '-s', 'tb_core_sync', '-o', out / 'core_sync.vvp',
                core, bench], ROOT, out / 'compile.log')
    tests = directed_programs()
    if not args.directed_only:
        tests.update({f'stress_{n}': (firmware.random_program(n).resolve(), None, 0)
                      for n in range(args.random_programs)})
    try:
        for name, (words, fault, reset_phase) in tests.items():
            for seed, delay, data_delay in ((1, 1, 0), (12345, 7, 7), (87654321, 23, 31)):
                report['checks'].append(run_case(name, words, fault, reset_phase, seed, delay, data_delay, out, vvp))
            target.write_text(json.dumps(report, indent=2), encoding='utf-8')
            if not name.startswith('stress_') or int(name.split('_')[1]) % 10 == 9:
                print(f'PASS SYNC {name}; total_cases={len(report["checks"])}', flush=True)
        # This reproducible seed was selected from an explicit, bounded
        # coverage search. The resulting branch commits on the same edge that
        # the wrong-path fault response handshakes, exercising redirect priority.
        words, fault, reset_phase = tests['wrong_path_fault_after_delayed_load']
        aligned = run_case('wrong_path_fault_redirect_response_same_cycle', words, fault,
                           reset_phase, 108 if args.version=='v03' else 137, 23, 31, out, vvp)
        assert aligned['metrics']['redirects_rsp_fire'] > 0, 'Same-cycle redirect/response fixture lost coverage'
        report['checks'].append(aligned)
        report.update(all_pass=True, check_count=len(report['checks']),
                      retirements_compared=sum(c['retirements_compared'] for c in report['checks']),
                      canceled_fault_responses=sum(c['metrics']['fault_responses'] for c in report['checks']
                                                   if c['test'].startswith('wrong_path_fault_')),
                      protocol_coverage={key: sum(c['metrics'][key] for c in report['checks'])
                                         for key in ('req_wait_cycles', 'rsp_wait_cycles', 'data_wait_cycles',
                                                     'redirects_req_fire', 'redirects_rsp_fire', 'redirects_pending',
                                                     'redirects_buffered_fault', 'error_rsp_wait_cycles')},
                      finished_utc=datetime.now(timezone.utc).isoformat())
        assert report['protocol_coverage']['redirects_req_fire'] > 0
        assert report['protocol_coverage']['redirects_buffered_fault'] > 0
        assert report['protocol_coverage']['error_rsp_wait_cycles'] > 0
        if args.version=='v04':
            report['turnover_accepts']=sum(c['metrics'].get('turnover_accepts',0) for c in report['checks'])
            assert report['turnover_accepts']>0, 'No same-cycle request/response turnover coverage'
        assert hashlib.sha256(core.read_bytes()).hexdigest()==report['core_sha256'], 'Core changed during verification'
        assert hashlib.sha256(bench.read_bytes()).hexdigest()==report['testbench_sha256'], 'Testbench changed during verification'
    except Exception as error:
        report.update(all_pass=False, error=repr(error), finished_utc=datetime.now(timezone.utc).isoformat())
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')
        raise
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'ALL PASS SYNCHRONOUS CPU: {report["check_count"]} cases; {report["retirements_compared"]} retirement records; canceled_fault_responses={report["canceled_fault_responses"]}', flush=True)


if __name__ == '__main__':
    main()
