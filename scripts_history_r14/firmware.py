"""Small, auditable RV32I instruction encoder and demo firmware builder.

No GCC is needed for this assembly-only demo. This is not a C compiler.
"""
from pathlib import Path
import json
import random

ROOT = Path(__file__).resolve().parents[1]
R_OP = {'add':(0,0),'sub':(0,32),'sll':(1,0),'slt':(2,0),'sltu':(3,0),
        'xor':(4,0),'srl':(5,0),'sra':(5,32),'or':(6,0),'and':(7,0)}
I_OP = {'addi':0,'slti':2,'sltiu':3,'xori':4,'ori':6,'andi':7}
LOAD = {'lb':0,'lh':1,'lw':2,'lbu':4,'lhu':5}
STORE = {'sb':0,'sh':1,'sw':2}
BRANCH = {'beq':0,'bne':1,'blt':4,'bge':5,'bltu':6,'bgeu':7}

class Program:
    def __init__(self): self.items=[]; self.labels={}
    @property
    def pc(self): return len(self.items)*4
    def label(self, name):
        assert name not in self.labels
        self.labels[name]=self.pc
    def emit(self, op, *args): self.items.append((op,args))
    def li(self, rd, value):
        value &= 0xffffffff
        signed=value if value < 0x80000000 else value-0x100000000
        if -2048 <= signed <= 2047: self.emit('addi',rd,0,signed)
        else:
            low=((value & 0xfff)^0x800)-0x800
            self.emit('lui',rd,((value-low)>>12)&0xfffff)
            self.emit('addi',rd,rd,low)
    def resolve(self):
        result=[]
        for index,(op,args) in enumerate(self.items):
            pc=index*4
            if op in R_OP:
                rd,a,b=args; f3,f7=R_OP[op]
                code=(f7<<25)|(b<<20)|(a<<15)|(f3<<12)|(rd<<7)|0x33
            elif op in I_OP or op in ('slli','srli','srai') or op in LOAD or op=='jalr':
                rd,a,imm=args
                if op in ('slli','srli','srai'):
                    assert 0<=imm<32
                    f3=1 if op=='slli' else 5
                    imm|=0x400 if op=='srai' else 0
                    opc=0x13
                elif op in I_OP: f3=I_OP[op]; opc=0x13
                elif op in LOAD: f3=LOAD[op]; opc=3
                else: f3=0; opc=0x67
                assert -2048<=imm<=2047
                code=((imm&0xfff)<<20)|(a<<15)|(f3<<12)|(rd<<7)|opc
            elif op in STORE:
                b,a,imm=args; assert -2048<=imm<=2047
                imm &= 0xfff
                code=((imm>>5)<<25)|(b<<20)|(a<<15)|(STORE[op]<<12)|((imm&31)<<7)|0x23
            elif op in BRANCH:
                a,b,label=args; off=self.labels[label]-pc if isinstance(label,str) else label
                assert off%2==0 and -4096<=off<=4094
                u=off&0x1fff
                code=((u>>12)<<31)|(((u>>5)&63)<<25)|(b<<20)|(a<<15)|(BRANCH[op]<<12)|(((u>>1)&15)<<8)|(((u>>11)&1)<<7)|0x63
            elif op=='jal':
                rd,label=args; off=self.labels[label]-pc if isinstance(label,str) else label
                assert off%2==0 and -(1<<20)<=off<(1<<20)
                u=off&0x1fffff
                code=((u>>20)<<31)|(((u>>1)&1023)<<21)|(((u>>11)&1)<<20)|(((u>>12)&255)<<12)|(rd<<7)|0x6f
            elif op in ('lui','auipc'):
                rd,imm=args; code=(imm<<12)|(rd<<7)|(0x37 if op=='lui' else 0x17)
            elif op=='raw': code=args[0]
            elif op=='ebreak': code=0x00100073
            elif op=='ecall': code=0x00000073
            elif op=='fence': code=0x0000000f
            else: raise ValueError(op)
            result.append(code&0xffffffff)
        return result

def demo():
    p=Program()
    for reg,value in [(20,0x40000000),(21,0x40000100),(22,0x40000400),(23,0x10000000),(24,0x20000000)]: p.li(reg,value)
    def puts(text):
        for char in text:
            p.li(10,ord(char)); p.emit('jal',1,'putchar')
    puts('GUANWEIXIN v0.1\r\n')
    p.li(5,1); p.li(6,0); p.li(7,17)
    p.label('sum_loop'); p.emit('add',6,6,5); p.emit('addi',5,5,1); p.emit('blt',5,7,'sum_loop')
    p.emit('sw',6,23,0); p.emit('lw',18,23,0); p.li(8,136); p.emit('bne',18,8,'failed')
    p.emit('sw',18,21,0)
    p.li(5,16); p.emit('sw',5,22,4); p.li(5,1); p.emit('sw',5,22,0)
    p.label('wait_capture'); p.emit('lw',5,22,0); p.emit('andi',5,5,2); p.emit('beq',5,0,'wait_capture')
    p.li(5,0); p.li(19,0); p.li(7,64); p.emit('addi',8,24,0)
    p.label('capture_sum'); p.emit('lw',9,8,0); p.emit('add',19,19,9)
    p.emit('addi',8,8,4); p.emit('addi',5,5,1); p.emit('blt',5,7,'capture_sum')
    p.li(8,3040); p.emit('bne',19,8,'failed')
    puts('SUM='); p.emit('addi',10,18,0); p.emit('jal',1,'printhex'); puts('\r\nCAPSUM=')
    p.emit('addi',10,19,0); p.emit('jal',1,'printhex'); puts('\r\nPASS\r\n')
    p.li(5,1); p.emit('sw',5,21,4)
    p.label('finished'); p.emit('jal',0,'finished')
    p.label('failed'); puts('FAIL\r\n'); p.li(5,2); p.emit('sw',5,21,4); p.emit('jal',0,'finished')
    p.label('putchar'); p.emit('sb',10,20,0); p.emit('jalr',0,1,0)
    p.label('printhex'); p.emit('addi',16,1,0); p.emit('addi',12,10,0); p.li(13,28); p.li(15,10)
    p.label('hex_loop'); p.emit('srl',14,12,13); p.emit('andi',14,14,15); p.emit('bltu',14,15,'hex_digit')
    p.emit('addi',10,14,55); p.emit('jal',0,'hex_output')
    p.label('hex_digit'); p.emit('addi',10,14,48)
    p.label('hex_output'); p.emit('jal',1,'putchar'); p.emit('addi',13,13,-4); p.emit('bge',13,0,'hex_loop'); p.emit('jalr',0,16,0)
    return p

def directed():
    p=Program(); p.li(28,0x10000000)
    for r,val in [(1,-1),(2,0x80000000),(3,31),(4,0x12345678),(5,1),(6,0)]: p.li(r,val)
    p.emit('addi',0,0,123)  # x0 must remain zero
    for op in R_OP:
        p.emit(op,7,2,3); p.emit(op,8,1,5); p.emit(op,9,4,0)
    for op in I_OP:
        for imm in [-2048,-1,0,1,2047]: p.emit(op,10,2,imm)
    for op in ['slli','srli','srai']:
        for imm in [0,1,31]: p.emit(op,11,2,imm)
    p.emit('auipc',12,1)
    p.emit('sw',4,28,0)
    for op in ['lb','lbu']: 
        for off in range(4): p.emit(op,13,28,off)
    for op in ['lh','lhu']:
        for off in [0,2]: p.emit(op,13,28,off)
    p.emit('sb',1,28,1); p.emit('sh',2,28,2); p.emit('lw',14,28,0)
    for op in ['lb','lbu','lh','lhu']: p.emit(op,14,28,0)
    p.emit('sw',1,28,4)
    for op in LOAD: p.emit(op,15,28,4)
    p.emit('lw',16,28,4); p.emit('add',17,16,5); p.emit('sw',17,28,8)
    # Every branch with true and false conditions, plus wrong-path stores.
    pairs={'beq':[(5,5),(5,0)],'bne':[(5,0),(5,5)],'blt':[(1,5),(5,1)],
           'bge':[(5,1),(1,5)],'bltu':[(5,1),(1,5)],'bgeu':[(1,5),(5,1)]}
    n=0
    for op,conditions in pairs.items():
        for a,b in conditions:
            label='b'+str(n); n+=1
            p.emit(op,a,b,label); p.emit('sw',4,28,16+n*4); p.emit('addi',18,18,1); p.label(label)
    p.li(19,7); p.label('back'); p.emit('addi',19,19,-1); p.emit('bne',19,0,'back')
    p.emit('jal',1,'subroutine'); p.emit('jal',0,'after_sub')
    p.label('subroutine'); p.emit('addi',20,1,0); p.emit('jalr',0,1,0)
    p.label('after_sub'); p.emit('fence'); p.emit('ebreak')
    return p

def random_program(seed):
    rng=random.Random(seed); p=Program(); p.li(28,0x10000000)
    for r in range(1,28): p.li(r,rng.getrandbits(32))
    for _ in range(700):
        rd=rng.randrange(0,28); a=rng.randrange(0,28); b=rng.randrange(0,28)
        kind=rng.randrange(5)
        if kind==0: p.emit(rng.choice(list(R_OP)),rd,a,b)
        elif kind==1: p.emit(rng.choice(list(I_OP)),rd,a,rng.randrange(-2048,2048))
        elif kind==2: p.emit(rng.choice(['slli','srli','srai']),rd,a,rng.randrange(32))
        elif kind==3:
            op=rng.choice(list(STORE)); align={'sb':1,'sh':2,'sw':4}[op]
            p.emit(op,a,28,rng.randrange(0,128//align)*align)
        else:
            op=rng.choice(list(LOAD)); align={'lb':1,'lbu':1,'lh':2,'lhu':2,'lw':4}[op]
            p.emit(op,rd,28,rng.randrange(0,128//align)*align)
    p.emit('ebreak'); return p

def build():
    out=ROOT/'firmware'; out.mkdir(exist_ok=True)
    p=demo(); words=p.resolve()
    header='`timescale 1ns/1ps\n// Generated by scripts/firmware.py; edit the builder to change firmware.\nmodule gwx_rom(input wire [31:0] addr, output reg [31:0] data);\n  always @* begin\n    case(addr)\n'
    lines=[f"      32'h{i*4:08x}: data=32'h{w:08x};" for i,w in enumerate(words)]
    (ROOT/'rtl/gwx_rom.v').write_text(header+'\n'.join(lines)+"\n      default: data=32'h00000000;\n    endcase\n  end\nendmodule\n",encoding='ascii')
    listing=[]
    for i,((op,args),word) in enumerate(zip(p.items,words)):
        for name,pc in p.labels.items():
            if pc==i*4: listing.append(name+':')
        listing.append(f'{i*4:08x}  {word:08x}  {op:8} '+', '.join(map(str,args)))
    (out/'demo_listing.txt').write_text('\n'.join(listing)+'\n',encoding='ascii')
    (out/'expected_uart.txt').write_bytes(b'GUANWEIXIN v0.1\r\nSUM=00000088\r\nCAPSUM=00000BE0\r\nPASS\r\n')
    tests={'directed':directed()}
    for seed in [7,42,2026]: tests['random_'+str(seed)]=random_program(seed)
    traps={}
    for name,op,off,cause in [('misaligned_lw','lw',1,4),('misaligned_sh','sh',1,6),('unmapped_load','lw',1024,5),('unmapped_store','sw',1024,7)]:
        t=Program(); t.li(28,0x10000000); t.emit(op,1,28,off); tests[name]=t; traps[name]=cause
    for name,word,cause in [('illegal',0xffffffff,2),('illegal_shift',0x02001013,2),('illegal_jalr',0x00001067,2),('ecall',0x00000073,11),('bad_jump',0x0020006f,0)]:
        t=Program(); t.emit('raw',word); tests[name]=t; traps[name]=cause
    metadata={}
    for name,t in tests.items():
        words=t.resolve(); assert len(words)<=2048
        (out/(name+'.hex')).write_text(''.join(f'{x:08x}\n' for x in words+[0]*(2048-len(words))),encoding='ascii')
        metadata[name]={'words':len(words),'trap':traps.get(name,3)}
    (out/'tests.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='ascii')
    print(f'Built demo: {len(p.items)} instructions; {len(tests)} CPU regression programs')

if __name__=='__main__': build()
