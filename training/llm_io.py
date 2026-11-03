"""Strict non-pickle weight/tokenizer IO and llama2.c-compatible exports."""
import hashlib, json, struct
from pathlib import Path
import numpy as np
import torch


class Tokenizer:
    def __init__(self, path):
        raw = Path(path).read_bytes(); off = 4
        self.maximum, = struct.unpack_from('<i', raw)
        if not 0 < self.maximum <= 1024: raise ValueError('Tokenizer bound')
        self.vocab, self.scores = [], []
        for _ in range(512):
            score, length = struct.unpack_from('<fi', raw, off); off += 8
            if not 0 <= length <= self.maximum: raise ValueError('Token length')
            token = raw[off:off+length].decode('utf-8'); off += length
            self.vocab.append(token); self.scores.append(score)
        if off != len(raw): raise ValueError('Tokenizer trailing/truncated data')
        self.index = {v:i for i,v in enumerate(self.vocab)}
        self.cache = {}

    def encode(self, text, bos=True):
        key = (text, bos)
        if key in self.cache: return self.cache[key][:]
        ids = ([1] if bos else []) + ([self.index[' ']] if text else [])
        for ch in text:
            ids.extend([self.index[ch]] if ch in self.index else [b+3 for b in ch.encode()])
        while len(ids) > 1:
            candidates = []
            for i in range(len(ids)-1):
                j = self.index.get(self.vocab[ids[i]] + self.vocab[ids[i+1]])
                if j is not None: candidates.append((self.scores[j], -i, j))
            if not candidates: break
            _, minus_i, j = max(candidates); i = -minus_i
            ids[i:i+2] = [j]
        self.cache[key] = ids[:]
        return ids


def load_legacy(model, path):
    raw = Path(path).read_bytes()
    if len(raw) < 28 or len(raw) > 2000000: raise ValueError('Weight file size')
    dim, hidden, layers, heads, kvheads, vocab, seq = struct.unpack_from('<7i', raw)
    if (dim, hidden, layers, heads, kvheads, vocab, seq) != (64,172,5,8,4,512,512):
        raise ValueError('Unexpected model configuration')
    values = np.frombuffer(raw, dtype='<f4', offset=28); off = 0
    def take(param):
        nonlocal off
        count = param.numel(); data = values[off:off+count].copy(); off += count
        if len(data) != count or not np.isfinite(data).all(): raise ValueError('Bad weight tensor')
        with torch.no_grad(): param.copy_(torch.from_numpy(data.reshape(tuple(param.shape))))
    take(model.tok_embeddings.weight)
    for layer in model.layers: take(layer.attention_norm.weight)
    for name in ('wq','wk','wv','wo'):
        for layer in model.layers: take(getattr(layer.attention, name).weight)
    for layer in model.layers: take(layer.ffn_norm.weight)
    for name in ('w1','w2','w3'):
        for layer in model.layers: take(getattr(layer.feed_forward, name).weight)
    take(model.norm.weight)
    # Legacy format stores two unused RoPE tables after the actual parameters.
    off += seq*(dim//heads)
    if off != len(values): raise ValueError('Legacy format extent mismatch')
    return dict(header=[dim,hidden,layers,heads,kvheads,vocab,seq], sha256=hashlib.sha256(raw).hexdigest(), parameter_count=sum(p.numel() for p in model.parameters()))


def export_weights(model, root, context=128):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    # Pad 172 -> 192 with zero neurons to make every matrix row divisible by GS64.
    # Silu(0)*0 contributes zero; no original neuron is removed or approximated.
    dim, hidden, padded, layers, heads, kvheads, vocab = 64,172,192,5,8,4,512
    def arr(t): return t.detach().cpu().numpy().astype('<f4')
    norms = [arr(l.attention_norm.weight) for l in model.layers] + [arr(l.ffn_norm.weight) for l in model.layers] + [arr(model.norm.weight)]
    tensors = [('embedding', arr(model.tok_embeddings.weight))]
    for name in ('wq','wk','wv','wo'):
        tensors += [(f'layer{i}.{name}', arr(getattr(l.attention,name).weight)) for i,l in enumerate(model.layers)]
    for name in ('w1','w2','w3'):
        for i,l in enumerate(model.layers):
            a = arr(getattr(l.feed_forward,name).weight)
            a = np.pad(a, ((0,0),(0,padded-hidden))) if name == 'w2' else np.pad(a, ((0,padded-hidden),(0,0)))
            tensors.append((f'layer{i}.{name}', a))
    qpath = root/'diagnostic_q8.bin'; offset = 256 + sum(a.nbytes for a in norms); table=[]
    header = struct.pack('<Ii7iB',0x616b3432,2,dim,padded,layers,heads,kvheads,vocab,context,1) + struct.pack('<i',64)
    with qpath.open('wb') as f:
        f.write(header); f.write(bytes(256-len(header)))
        for a in norms: f.write(a.tobytes())
        for name,a in tensors:
            blocks = a.reshape(-1,64)
            scale = np.max(np.abs(blocks),axis=1)/127
            scale = np.where(scale==0,1.0,scale).astype('<f4')
            q = np.rint(blocks/scale[:,None]).clip(-127,127).astype('i1')
            error = float(np.max(np.abs(q.astype(np.float32)*scale[:,None]-blocks)))
            f.write(q.tobytes()); f.write(scale.tobytes())
            table.append(dict(name=name,shape=list(a.shape),offset=offset,qbytes=q.nbytes,scale_bytes=scale.nbytes,max_abs_error=error))
            offset += q.nbytes + scale.nbytes
    # Portable FP32 file (same padded geometry), for an independent C reference.
    with (root/'diagnostic_f32.bin').open('wb') as f:
        f.write(struct.pack('<7i',dim,padded,layers,heads,kvheads,vocab,context))
        f.write(tensors[0][1].tobytes())
        for l in model.layers: f.write(arr(l.attention_norm.weight).tobytes())
        for _,a in tensors[1:1+4*layers]: f.write(a.tobytes())
        for l in model.layers: f.write(arr(l.ffn_norm.weight).tobytes())
        for _,a in tensors[1+4*layers:]: f.write(a.tobytes())
        f.write(arr(model.norm.weight).tobytes())
        f.write(bytes(context*(dim//heads)*4))
    np.savez(root/'diagnostic_weights.npz', **{k:v.detach().cpu().numpy() for k,v in model.state_dict().items()})
    info = dict(quantization='Q8_0 group64 matmul weights; RMSNorm/RoPE/softmax/SwiGLU stay FP32', context=context,
                full_integer_inference=False, original_hidden=hidden,padded_hidden=padded,
                padding_preserves_fp32_function=True, tensors=table, file_bytes=qpath.stat().st_size,
                model_sha256=hashlib.sha256(qpath.read_bytes()).hexdigest(), fpga_deployed=False)
    (root/'export_manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    return info
