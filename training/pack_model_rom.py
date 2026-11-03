"""Use all 36 bits of each DRM word; two interleaved banks serve unaligned 32-bit CPU reads."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
(ROOT/"reports").mkdir(exist_ok=True)
raw=(ROOT/'diagnostic_q4.bin').read_bytes()
value=int.from_bytes(raw,'little');words=[]
while value:words.append(value&((1<<36)-1));value>>=36
needed=(len(raw)*8+35)//36
words += [0]*(needed-len(words));words += [0]*(35500-len(words))
for parity,name in [(0,'even'),(1,'odd')]:
 (ROOT/f'model_{name}.hex').write_text(''.join(f'{v:09x}\n'for v in words[parity::2]),encoding='ascii')
# Exhaustive CPU address reconstruction, including word reads spanning a 36-bit boundary.
for i in range(len(raw)//4):
 index=i*8//9;offset=i*32-index*36
 actual=((words[index]|(words[index+1]<<36))>>offset)&0xffffffff
 if actual!=int.from_bytes(raw[i*4:i*4+4],'little'):raise RuntimeError('Packed-ROM reconstruction')
(ROOT/'reports/model_rom_packing.json').write_text(json.dumps(dict(bytes=len(raw),banks=2,bank_width=36,bank_depth=17750,
    expected_drm18_blocks=70,all_word_addresses_verified=len(raw)//4,physical_implementation_verified=False),indent=2),encoding='utf-8')
print('PASS packed model ROM: 39936 CPU words reconstructed from 36-bit banks')
