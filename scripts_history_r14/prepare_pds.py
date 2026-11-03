from pathlib import Path
import re,shutil,argparse
p=argparse.ArgumentParser();p.add_argument('--work',default='F:/FPGA_Work/gwx_ai_r14');a=p.parse_args()
S=Path(__file__).resolve().parents[1]/'pds';R=Path(a.work).resolve()
if not str(R).isascii():raise ValueError('PDS requires an ASCII build path')
for d in ['inputs','rom_banks','pds_run']:(R/d).mkdir(parents=True,exist_ok=True)
for f in (S/'rom_banks').glob('*.hex'):shutil.copy2(f,R/'rom_banks'/f.name)
for f in (S/'templates').iterdir():
 if f.is_file():
  s=f.read_text(encoding='utf-8');s=re.sub(r'F:/FPGA_Work/[^"\n]+?/rom_banks/',(R/'rom_banks').as_posix()+'/',s);(R/'inputs'/f.name).write_text(s,encoding='utf-8')
s=(S/'ai_template.fic').read_text();s=re.sub(r'Project.device.designInputFile=.*','Project.device.designInputFile='+(R/'pds_run/synthesize/guanweixin_ai_board_top_syn.adf').as_posix(),s);(R/'ai.fic').write_text(s)
s=(S/'original_run.tcl').read_text().replace('F:/FPGA_Work/contest_completion_20261030_r05b',R.as_posix());(R/'run.tcl').write_text(s)
print('PDS WORKSPACE:',R)
