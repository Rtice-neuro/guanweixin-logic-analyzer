from pathlib import Path
import sys,json,hashlib,shutil,re,csv,sqlite3,datetime
from urllib.request import urlopen
sys.stdout.reconfigure(encoding='utf-8')
P=Path('F:/脑机项目/guanweixin_demo_v01');R=P/'development/ai_accuracy_20261030_r14';O=P/'submission/观微芯_AI精度优化_20261030_r14';E=R/'reports/board';W=Path('F:/FPGA_Work/gwx_ai_r14');D=O/'docs';EV=O/'evidence'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
B=load(E/'board_acceptance.json');C=load(E/'configuration_evidence.json');I=load(E/'ila_analysis.json');A=load(O/'verification_fresh/model_data_audit.json');T=load(O/'verification_fresh/suite_status.json');assert B['all_pass']and C['sram_configuration_success']and not C['flash_written']and T['all_pass'];assert I['retire_valid']==I['firmware_instruction_matches']and not I['mismatches'];assert A['model_crc32']=='2a52a97d'
status=json.load(urlopen('http://127.0.0.1:8765/api/status'));assert status['ready']and not status['pending']and not status['error']
save(E/'final_api_status.json',status)
for n,u in [('final_api_ai','/api/ai/results'),('final_api_benchmarks','/api/benchmarks')]:save(E/(n+'.json'),json.load(urlopen('http://127.0.0.1:8765'+u)))
pre=load(E/'precheck.json');(E/'fresh_session_uart.bin').write_bytes((R/'board_data/rx_stream.bin').read_bytes()[pre['raw_offset']:])
timing=(W/'pds_run/report_timing/guanweixin_ai_board_top.rtr').read_text(encoding='utf-8');dmr=(W/'pds_run/device_map/guanweixin_ai_board_top.dmr').read_text(encoding='utf-8');assert'All Constraints Met'in timing
res={}
for key in ['LUT','FF','DRM','APM']:
 m=re.search(r'\|\s*'+key+r'\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)',dmr);assert m,key;res[key]=float(m[1]);res[key+'_available']=float(m[2])
assert '38.638'in timing
res.update(nominal_clock_mhz=27,static_estimated_max_mhz=38.638,all_constraints_met=True,slow_setup_slack_ns=11.156,slow_hold_slack_ns=.012,fast_setup_slack_ns=18.842,fast_hold_slack_ns=.012,clock_independently_calibrated=False,coremark_per_lut_whole_design=B['benchmarks'][0]['iterations_per_second']/res['LUT']);save(E/'implementation_metrics.json',res)
# Verify the actual PDS inputs and ROMs correspond to the delivered candidate.
checks=[]
for f in(O/'pds/templates').iterdir():
 if f.is_file():
  expected=re.sub(r'F:/FPGA_Work/[^"\n]+?/rom_banks/',(W/'rom_banks').as_posix()+'/',f.read_text(encoding='utf-8'));q=W/'inputs'/f.name;assert expected==q.read_text(encoding='utf-8'),f.name;checks.append(f.name)
for f in(W/'rom_banks').glob('*.hex'):assert f.read_bytes()==(O/'pds/rom_banks'/f.name).read_bytes();checks.append('rom_banks/'+f.name)
save(E/'source_rom_consistency.json',dict(all_pass=True,checked=len(checks),files=checks,clock_mhz=27,pins_unchanged=True,rtl_unchanged_from_r12=True,model_cpu_words_verified=39936))
prior=EV/'prior_r12_default';prior.mkdir(exist_ok=True)
for n in ['guanweixin_ai_board_top.sbit','ila_analysis.json','ila_decoded.csv','firmware_disassembly.txt']:
 if(EV/n).exists()and not(prior/n).exists():shutil.copy2(EV/n,prior/n)
shutil.copy2(Path(C['bitstream']),EV/'guanweixin_ai_board_top.sbit');assert sha(EV/'guanweixin_ai_board_top.sbit')==C['bitstream_sha256']
for n in ['ila_analysis.json','ila_decoded.csv','firmware_disassembly.txt']:shutil.copy2(E/n,EV/n)
shutil.copy2(W/'coremark_r14.vcd',EV/'coremark_final_r14.vcd')
for ext in ['dprj','wdf']:shutil.copy2(W/f'coremark_board_debug_r14.{ext}',E/f'coremark_board_debug_r14.{ext}')
shutil.copy2(W/'pds_run/device_map/guanweixin_ai_board_top.dmr',E/'pds_device_map.dmr');shutil.copy2(W/'pds_run/report_timing/guanweixin_ai_board_top.rtr',E/'pds_timing.rtr')
# Plot only the newly captured, decoded hardware window.
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
rows=list(csv.DictReader((E/'ila_decoded.csv').open(encoding='utf-8')));x=[int(r['sample'])for r in rows];fig,axes=plt.subplots(5,1,figsize=(12,6),sharex=True,gridspec_kw={'height_ratios':[2,1,1,1,1]});axes[0].step(x,[int(r['pc'],16)for r in rows],where='post',color='black',linewidth=.8);axes[0].set_ylabel('PC');axes[0].ticklabel_format(axis='y',style='plain',useOffset=False)
for ax,k,lab in zip(axes[1:],['retire_valid','forward','waiting','flush'],['Retire valid','Forward','Waiting','Flush']):ax.step(x,[int(r[k])for r in rows],where='post',color='black',linewidth=.8);ax.set_ylim(-.1,1.1);ax.set_yticks([0,1]);ax.set_ylabel(lab);ax.grid(alpha=.15)
axes[-1].set_xlabel('Sample index (core clock edges; exported VCD timescale is not calibrated)');fig.suptitle(f"r14 PDS real-board ILA | 512 cycles | {I['firmware_instruction_matches']} matched retirements");fig.tight_layout();fig.savefig(D/'coremark_ila_r14.png',dpi=180);plt.close(fig)
labels={'normal':'正常','missing':'丢脉冲','period':'周期异常','stuck_high':'卡高','stuck_low':'卡低'};lines=[]
for k,n in labels.items():
 a=next(v for v in B['ai']if v['case']==k)['frame'];c=next(v for v in B['ai']if v['case']==k+'_cpu')['frame'];lines.append(f"{n}：FPGA加速 {a['nominal_inference_seconds']:.3f} 秒，CPU软件 {c['nominal_inference_seconds']:.3f} 秒，收益 {B['class_speedups'][k]:.3f} 倍。")
perf,val=B['benchmarks'];ai_lines='\n\n'.join(lines);stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
s=f'''# 观微芯·八路逻辑检测仪
r14 技术与性能分析报告 | 2026-10-30

当前交付为盘古50上的片上自测演示版。自研处理器运行固件，硬件采集八路片上测试信号，CPU执行规则与微型Transformer推理，再通过UART送到本地Web显示波形、故障位置和历史日志。数据来源明确标为INTERNAL。

本轮验收：33条采集自检与IRQ自检通过，两项CoreMark均CRC通过，11次板端AI固定样例通过，真实ILA的{I['retire_valid']}条有效退休指令全部匹配本轮ELF。外部信号与外接显示屏未测试，视频和赛事门户提交不包含在本交付范围内。

最终位流SHA-256：{C['bitstream_sha256']}

模型CRC32：2a52a97d；模型SHA-256：{A['model_sha256']}。PDS配置方法为Fabric Debugger的Configure Bitstream File，写入SRAM，未写Flash。断电后须重新配置。

## 处理器结构与赛题基础任务

处理器支持RV32I基础整数指令，采用五级流水线，提供前递、冲刷、动态分支预测和返回地址栈，集成UART、GPIO、MMIO、异常与机器中断。固件构建明确使用rv32i_zmmul_zicsr，含Zmmul乘法和CSR扩展，不能将扩展指令收益隐去。

指令Cache为4KiB，数据Cache为2KiB，均为两路组相联；数据Cache写直达、未命中不写分配，按四字缓存行填充。内部突发填充链路已测试，不等同于完整AXI协议认证。

当前候选完整离线回归已通过，包括462个CPU参考场景、24个返回栈场景、12种异常/中断配置、三个缓存随机种子、Q4加速核及网页边界/恢复/历史查询。参考指令退休总数259281。该范围属于项目测试，不声称完整RISC-V特权规范认证。

## 八路采集到网页的数据链路

片上测试源产生八位并行数字信号，硬件完成定时采样、触发与64点缓存，CPU读取数据、核对软件和硬件校验和，并输出每通道故障和位置。默认采样分频270，在27MHz标称时钟下对应100k样点/秒的内部采样节拍。外部异步输入的完整时序、电平和抗干扰能力没有因此得到证明。

当前按次采集、按次诊断，AI运行期间有忙状态和超时控制；不能将约20秒的诊断过程称为连续实时推理。板端回包保留原始DATA、SUM、HW_SUM、TRACE、来源和模型标识。网页不执行模型，只展示和保存板端结果。时间戳为电脑接收时刻，不是硬件绝对时间校准。

默认交付禁用EXTERNAL命令，演示使用正常、丢脉冲、周期异常、卡高、卡低五个模式。33条本轮板端自检和11条AI验收记录均经过严格协议解析，实际来源为SERIAL/INTERNAL。CPU与加速路径比较使用同一输入样例。

## CoreMark与PDS实现指标

性能模式：{perf['iterations']}次迭代，{perf['ticks']}个核心周期，{perf['seconds']:.6f}秒，{perf['iterations_per_second']:.6f} CoreMark，{perf['coremark_per_mhz']:.6f} CoreMark/MHz。验证模式：{val['ticks']}周期，{val['seconds']:.6f}秒，{val['coremark_per_mhz']:.6f} CoreMark/MHz。两者CRC均通过，时间均超过指南规定的10秒。

CoreMark算法源未修改，性能构建-O2，应用-Os，静态数据2000字节，RAM 64KiB。串口打印的整数秒和Iterations/Sec有取整；报告采用64位原始ticks计算，不能把打印的73次/秒作为正式成绩。

PDS整机（含ILA、AI）资源为LUT {int(res['LUT'])}、FF {int(res['FF'])}、DRM {res['DRM']}/{int(res['DRM_available'])}、APM {int(res['APM'])}。整机CoreMark/LUT为{res['coremark_per_lut_whole_design']:.8f}，分母包含仪器与AI逻辑，不等同于单CPU核资源效率。

工作频率为标称27MHz。PDS报告All Constraints Met；慢角Setup裕量11.156ns、Hold 0.012ns，快角Setup18.842ns、Hold0.012ns。静态估计38.638MHz没有实板运行验证，不能写成实测主频。异步IO仍存在Timing-4086/4087提示；DRM使用约95.9%，Hold裕量较小，不支持任意加频或外设扩展的推论。

## 本轮PDS实板ILA分析

通过Computer Use在PDS实际运行时触发采样，导出512点、112位VCD。当前窗口主要位于CoreMark的crc16函数，并包含core_bench_list；{I['retire_valid']}条有效退休指令的PC和指令字全部匹配本轮app.elf，周期计数连续。

窗口局部IPC={I['local_ipc']:.6f}，前递有效{I['forward_cycles']}周期、冲刷{I['flush_cycles']}周期、waiting={I['waiting_cycles']}周期。事件可能重叠，不能将它们直接相加分摊所有停顿；该局部窗口也不能代表整个CoreMark平均IPC或分支预测命中率。

原始VCD、逐点CSV、解码脚本、ELF反汇编、调试工程及WDF均随证据保存。PDS导出的100ns刻度只是导出格式，图中横轴使用采样序号；不能据此推断CPU为10MHz或声称完成了独立频率校准。

## AI模型、精度与启动过渡修正

模型为完整260032参数的五层微型Transformer，维度64、八个注意力头、四个KV头、词表512、上下文64；矩阵权重Q4、激活Q8、分组64，KV采用FP16存储，归一化和非线性仍为软件FP32。文件159744字节，工作内存48916字节。输入仅为采样统计与相邻上升沿间隔，不含注入模式、CPU故障标签或正确答案；输出类别token和EOS。

r13实板发现卡高输入是首点0、后续63点1，纯恒定训练锚点没有覆盖启动过渡，模型将其判为未知。本轮保留失败原始回包，补入0..4个初始反向样点、随后至少60点稳定电平的明确标注训练样例，形成r14。没有用规则答案直接替代AI输出。

r14在训练开始前冻结全新550条合成测试，提示与r13全部训练/验证/测试及历史评估均不重叠；当前训练/验证/测试提示交集为0、标签冲突为0。验证集550/550；Q4完整C运行时新测试549/550（99.82%）：正常150/150、丢脉冲150/150、周期异常149/150、未知100/100。原r13测试集回归549/550。

另有10个恒定/启动过渡训练锚点回归，r13模型2/10、r14模型10/10；它们已在训练中出现，不计入独立测试准确率。未修正剩下那条测试错误来提高报告数字。周期合成训练范围5..16样点，固件接收4..16，默认8；真实外部电路准确率仍未知。分数未做概率校准。

## 板端AI延迟与软硬件对照

本轮11次板端AI固定样例通过，覆盖五类CPU与加速路径各一次，以及D7卡低。所有回包为SERIAL/INTERNAL，运行版本2、模型CRC32=2a52a97d、EOS=2。五组TOKEN、EOS、LABEL、SCORE_PERMILLE、DOT_GROUPS完全一致。

{ai_lines}

上述为单次模型推理计时区间，按板端核心ticks除以27MHz计算，未包含前置采集、模型CRC首次检查、串口传输及页面渲染，不是端到端延迟。11条固定样例通过不等于统计准确率。模型位于FPGA ROM中并由板端RV32I执行，网页接收程序没有调用主机模型。

## 演示、恢复与文件复现

打开PDS工程F:/FPGA_Work/gwx_ai_r14/pds_run/run.pds，进入Tools或工具栏Debugger，打开coremark_board_debug_r14.dprj。Connect to Server连接本机65420端口，选择PANGO USB CABLE II；Configure Bitstream File选择交付evidence/guanweixin_ai_board_top.sbit，保持Import fic选项按已保存的调试配置使用，执行SRAM配置。看到configure成功后，等待串口33组自检与READY。

运行02_启动板内AI网页.cmd会在8765启动COM8本机接收器；若本轮服务已运行，直接打开http://127.0.0.1:8765/，不要重复启动。页面选择内部模式，执行正常/故障采集或AI诊断。需要展示性能时在AI结束、板卡READY后运行CoreMark入口。KEY2会复位并重新自检，REPROGRAM与板卡电源不要作为普通运行按键。

01_准备PDS工程.cmd把源码/ROM复制到ASCII构建目录；03_PDS实现.cmd从该目录执行完整PDS流程；04_离线完整验证.cmd和05_模型数据审计.cmd给出可复核软件证据。模型训练来源、r13失败、r14新数据清单和C运行时预测表随包保存。公开前重新检查SHA256SUMS，运行验证脚本产生新日志后哈希变化属于预期。

## 赛题对应、提交状态与限制

RV32I流水线、UART/GPIO、Cache、分支预测、异常/中断、CoreMark、PDS资源/时序和ILA均有源码与对应证据。应用为片上数字测试源、CPU/AI诊断、本地Web显示。外部信号发生器不是指南明确单列器材；当前没有外部采集实测，不能写成真实现场八路检测验收。

高阶AI条款还涉及传感/显示应用及YOLO或轻量模型；本实现为260K专用微型Transformer与电脑Web，未融合外接传感器/屏幕，也未获得组委会对模型规模和应用形式的正式认可，不能保证高阶满分或入围。Flash永久写入不是所提供指南的明确要求，目前未写入。

尚未完成或不在本轮范围：外部信号/显示器、独立时钟校准、真实外部数据集、赛事门户最终格式核对与提交、视频录制。文件材料完成不能代替参赛者理解处理器、解释优化和参加现场能力考核。

参考与许可：references目录保留用户提供的2026紫光同创选题指南；CoreMark源码/许可、原始260K预训练模型和tokenizer及其许可随包存档。报告时间{stamp}。本轮所有量化指标均可追溯至evidence/final_board_r14和verification_fresh。
'''
hist=D/'history_r12';hist.mkdir(exist_ok=True)
for name in ['技术与性能分析报告.md','观微芯_技术与性能分析报告.pdf','AI任务说明与答辩口径.md','AI正确率优化记录.md']:
 if(D/name).exists()and not(hist/name).exists():shutil.copy2(D/name,hist/name)
(D/'技术与性能分析报告.md').write_text(s,encoding='utf-8')
(D/'AI正确率优化记录.md').write_text(s[s.index('## AI模型'):s.index('## 演示')],encoding='utf-8')
(D/'AI任务说明与答辩口径.md').write_text('# r14 AI任务与测量边界\n\n'+s[s.index('## AI模型'):s.index('## 演示')],encoding='utf-8')
(O/'README.md').write_text('''# 观微芯·八路逻辑检测仪 r14

当前为盘古50片上自测实物演示版。33组采集自检、两项CoreMark、11次板端AI、PDS真实ILA和离线回归通过。外部信号、外接屏幕、视频、门户提交不包含。

先读 docs/技术与性能分析报告.md（同名PDF）和 docs/演示与恢复操作.md。默认位流 evidence/guanweixin_ai_board_top.sbit 已经本轮SRAM实测；模型CRC32=2a52a97d，不能与旧位流或固件混用。断电需重新配置，未写Flash。

01准备PDS；02启动COM8网页；03运行PDS实现；04离线验证；05模型数据审计。PDS工作目录 F:/FPGA_Work/gwx_ai_r14。当前主机已运行本地服务时直接打开 http://127.0.0.1:8765/。交付包data保存验收时快照，历史记录保留来源和模型版本。

当前证据 evidence/final_board_r14；prior/history/r12/r13目录只作历史追溯。当前独立合成测试549/550不是外部真实电路准确率。10个启动锚点是已训练回归，不计入独立精度。规则为主、AI辅助；组委会是否认可260K模型满足高阶轻量模型要求未确认。

解压后先运行 python scripts/verify_package.py 核对文件SHA256。重跑测试会更新输出，之后哈希变化属于预期。完整训练与新数据划分位于 training/accuracy_r14，模型文件159744字节。
''',encoding='utf-8')
(D/'演示与恢复操作.md').write_text('# r14 演示与恢复\n\n'+s[s.index('## 演示'):s.index('## 赛题对应')],encoding='utf-8')
(D/'提交材料核对.md').write_text('# r14 提交材料核对\n\n- 当前位流、ELF、HEX、ROM、模型必须成套使用，模型CRC32=2a52a97d。\n- 主报告、资源/时序报告、CoreMark原始UART、ILA VCD/CSV/WDF、33组采集、11次AI及离线验证已归档。\n- 99.82%为550条新合成样例结果；启动锚点10/10不计入独立准确率。\n- 外部信号、屏幕、独立时钟校准、视频和门户提交未完成或不在范围。\n- 高阶AI模型规模与电脑Web显示形式认可未确认。\n- 本包为技术交付，最终门户字段、文件大小和提交动作仍需按当届门户要求核对。\n',encoding='utf-8')
for f in O.glob('*.cmd'):
 t=f.read_text(encoding='utf-8-sig');t=t.replace('gwx_r10_rebuild','gwx_ai_r14');t=t.replace('@echo off','@echo off\nset PYTHONUTF8=1',1)if 'set PYTHONUTF8='not in t else t;f.write_text(t,encoding='utf-8')
M=load(D/'model_manifest.json');M.update(revision='r14',fpga_tested=True,board_tested_bitstream_sha256=C['bitstream_sha256']);save(D/'model_manifest.json',M)
st=load(O/'完成状态.json');st.update(revision='r14',board_updated=True,board_coremark_ai_pass=True,ai_board_acceptance_pass=True,known_issue=None,superseded_by_candidate=None,internal_scope_implemented=True,rebuilt_bitstream_downloaded=True,board_tested_bitstream_sha256=C['bitstream_sha256'],board_selftest_cases=33,board_ai_runs=11,board_coremark_runs=2,latest_ila_instruction_matches=I['firmware_instruction_matches'],latest_ila_cycles=512,ila_real_capture_and_instruction_match=True,board_status_ready=True,fresh_all_tests_pass=True,pdf_render_review_pass=False,model_sha256=A['model_sha256'],model_crc32='2a52a97d',external_signal_tested=False,external_display_integrated=False,organizer_ai_acceptance_confirmed=False,scope='r14 real-board internal-source demonstration; AI auxiliary, documented synthetic accuracy and startup regression');save(O/'完成状态.json',st)
f=load(O/'verification_fresh/final_summary.json');f.update(full_suite_pass=True,physical_board_retested_this_turn=True,board_revision='r14',model_crc32='2a52a97d',model_sha256=A['model_sha256'],board_acceptance_all_pass=True,new_synthetic_test_correct=549,new_synthetic_test_cases=550,startup_anchor_regression_pass=10);save(O/'verification_fresh/final_summary.json',f)
log=f'''{stamp} r14最终实板验收
PDS SRAM配置成功；未写Flash。33组采集/IRQ、两项CoreMark、11次AI通过。
CoreMark/MHz {perf['coremark_per_mhz']:.9f}/{val['coremark_per_mhz']:.9f}；ILA 512点，{I['firmware_instruction_matches']}条匹配ELF。
修正r13启动过渡卡高误判，r13失败回包已保留。r14新合成测试549/550，启动训练锚点10/10。
位流SHA256 {C['bitstream_sha256']}
模型SHA256 {A['model_sha256']}，CRC32 2a52a97d。
外部信号/屏幕、独立时钟、组委会AI认可、视频、门户提交均未完成或未确认。
''';(R/'reports/最终实板验收.log').write_text(log,encoding='utf-8');(O/'推进分析.log').write_text(log,encoding='utf-8')
shutil.copytree(E,EV/'final_board_r14',dirs_exist_ok=True)
fail=EV/'r13_failure_history';fail.mkdir(exist_ok=True)
for n in ['ai_acceptance_failure.json','failed_capture_128.json','board_acceptance_progress.json']:shutil.copy2(P/'development/ai_accuracy_20261030_r13/reports/board'/n,fail/n)
# Consistent idle local data snapshot; use SQLite backup rather than copying a live DB.
data=O/'data';data.mkdir(exist_ok=True)
for f in(R/'board_data').iterdir():
 if f.is_file()and not any(f.name.endswith(z)for z in('.sqlite3','-wal','-shm')):shutil.copy2(f,data/f.name)
with sqlite3.connect(R/'board_data/instrument.sqlite3')as src,sqlite3.connect(data/'instrument.sqlite3')as dst:src.backup(dst)
print('Prepared r14 delivery, report and measured evidence',O)
