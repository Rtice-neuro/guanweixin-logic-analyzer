from pathlib import Path
import hashlib,sys
R=Path(__file__).resolve().parents[1];errors=[];count=0
for line in (R/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
 digest,name=line.split('  ',1);p=R/name;count+=1
 if not p.is_file()or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:errors.append(name)
print('Checked',count,'files; errors:',len(errors))
for e in errors:print(e)
sys.exit(bool(errors))
