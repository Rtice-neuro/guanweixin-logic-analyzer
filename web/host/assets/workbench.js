function originName(origin){return {SERIAL:'串口实板',IMPORTED:'文件导入',RTL_SIMULATION:'RTL 离线仿真',ARCHIVED_SERIAL:'历史串口归档'}[origin]||origin;}
(function(){'use strict';
const $=id=>document.getElementById(id),M=GwxWave,colors=Array(8).fill('var(--wave)');
const labels={NONE:'正常',MISSING_PULSE:'丢脉冲',PERIOD:'周期异常',STUCK:'电平卡死',TIMEOUT:'触发超时',CONFIG_ERROR:'配置错误',FAIL:'校验失败'};
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let record=bootstrap.record,history=bootstrap.history,view={start:0,end:64},a=null,b=null,busy=false,lastBenchmark=-1,lastLatest=-1,lastStatus=null,polling=false;
let channels=Array.from({length:8},(_,i)=>({name:'D'+i,visible:true}));
try{const saved=JSON.parse(localStorage.getItem('gwx.channels'));if(Array.isArray(saved)&&saved.length===8)channels=saved.map((c,i)=>({name:typeof c.name==='string'?c.name.slice(0,24):'D'+i,visible:c.visible!==false}));}catch(e){}
function message(text,error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
async function request(path,body){const emit=d=>document.dispatchEvent(new CustomEvent('gwx:request',{detail:{path,...d}}));if(body!==undefined)emit({body,stage:'request'});let httpStatus;try{const r=await fetch(path,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json','X-GWX-Control':token},body:JSON.stringify(body)});httpStatus=r.status;let data;try{data=await r.json();}catch{throw Error('\u672c\u5730\u670d\u52a1\u8fd4\u56de\u65e0\u6548\u6570\u636e');}if(!r.ok)throw Error(data.error||'HTTP '+r.status);if(body!==undefined)emit({stage:'accepted',status:r.status});return data;}catch(e){if(body!==undefined)emit({stage:'error',status:httpStatus??'NETWORK',error:e.message});throw e;}}
function persistChannels(){try{localStorage.setItem('gwx.channels',JSON.stringify(channels));}catch(e){message('浏览器未允许保存显示设置；当前显示可用，刷新后可能恢复默认。',true);}renderWave();updateStudio();}
function renderChannels(){const wrap=$('channels');wrap.replaceChildren();channels.forEach((c,i)=>{const row=document.createElement('div');row.className='channel-row';row.style.setProperty('--channel-color',colors[i]);const check=document.createElement('input');check.type='checkbox';check.checked=c.visible;check.setAttribute('aria-label','显示 D'+i);check.onchange=()=>{c.visible=check.checked;persistChannels();};const badge=document.createElement('span');badge.className='channel-index';badge.textContent='D'+i;const name=document.createElement('input');name.value=c.name;name.maxLength=24;name.className='channel-name';name.setAttribute('aria-label','D'+i+' 通道名称');name.oninput=()=>{c.name=name.value||'D'+i;persistChannels();};name.onchange=()=>{c.name=name.value.trim()||'D'+i;name.value=c.name;persistChannels();};row.append(check,badge,name);wrap.append(row);});}
function renderWave(){
 const data=record?.samples||[],dt=M.samplePeriod(record),visible=channels.map((c,i)=>c.visible?i:-1).filter(i=>i>=0);
 if(!data.length){$('wave').innerHTML='<p class="empty">'+(record?'此记录无有效采样数据：'+esc(labels[record.status]||record.status):'等待采集，或在采集记录中导入串口文件。')+'</p>';updateMeasurement();return;}
 const width=Math.max(550,$('wave').clientWidth),left=36,right=18,plotWidth=width-left-right,rowHeight=44,top=50,height=430,span=view.end-view.start;
 let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="八通道数字波形，可点击设置游标" tabindex="0"><defs><clipPath id="plotClip"><rect x="${left}" y="${top-8}" width="${plotWidth}" height="${height-top}"/></clipPath></defs>`;
 const ticks=10;
 for(let j=0;j<=ticks;j++){const sample=view.start+span*j/ticks,x=left+plotWidth*j/ticks;svg+=`<line x1="${x}" x2="${x}" y1="30" y2="${height}" stroke="var(--grid)"/>`;if(plotWidth>=720||j%2===0)svg+=`<text x="${x}" y="20" text-anchor="${j===0?'start':j===ticks?'end':'middle'}" fill="var(--muted)" font-size="14">${esc(dt?M.formatTime(sample*dt):sample.toFixed(0)+' 点')}</text>`;}
 visible.forEach((ch,row)=>{const y=top+row*rowHeight;svg+=`<text x="6" y="${y+26}" fill="${colors[ch]}" font-size="16">D${ch}</text><line x1="${left}" x2="${width-right}" y1="${y+rowHeight}" y2="${y+rowHeight}" stroke="var(--grid)"/><g clip-path="url(#plotClip)"><polyline transform="translate(${left},${y})" points="${M.points(data,ch,view.start,view.end,plotWidth,rowHeight)}" fill="none" stroke="${colors[ch]}" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
 for(const f of record.faults||[])if(f.channel===ch&&f.index>=view.start&&f.index<view.end){const x=left+(f.index-view.start)/span*plotWidth;svg+=`<line x1="${x}" x2="${x}" y1="${y+3}" y2="${y+46}" stroke="var(--ink)" stroke-width="2" stroke-dasharray="3 3"><title>${esc(labels[f.code])} · 样点 ${f.index}</title></line><circle cx="${x}" cy="${y+5}" r="3" fill="var(--ink)"/>`;}
 svg+='</g>';});
 for(const [name,index,color]of[['A',a,'var(--ink)'],['B',b,'var(--muted)']])if(index!==null&&index>=view.start&&index<view.end){const x=left+(index-view.start)/span*plotWidth;svg+=`<line x1="${x}" x2="${x}" y1="28" y2="${height}" stroke="${color}" stroke-width="1.5" stroke-dasharray="${name==='B'?'5 4':'none'}"/><rect x="${x-8}" y="26" width="16" height="17" rx="3" fill="${color}"/><text x="${x}" y="39" fill="var(--surface)" text-anchor="middle" font-size="16">${name}</text>`;}
 if(!visible.length)svg+='<text x="500" y="100" text-anchor="middle" fill="var(--muted)">全部通道已隐藏，请在左侧打开通道</text>';
 $('wave').innerHTML=svg+'</svg>';
 const element=$('wave').querySelector('svg'),position=e=>new DOMPoint(e.clientX,e.clientY).matrixTransform(element.getScreenCTM().inverse());element.onclick=e=>{const p=position(e),x=p.x;if(x<left||x>width-right||p.y<top||p.y>height)return;const index=M.sampleAt(x-left,plotWidth,view.start,view.end,data.length);if(e.shiftKey)b=index;else a=index;renderWave();};
 element.onwheel=e=>{e.preventDefault();const anchor=M.clamp((position(e).x-left)/plotWidth,0,1);if(e.shiftKey)view=M.pan(view,(e.deltaY>0?1:-1)*span*.15,data.length);else view=M.zoom(view,e.deltaY>0?1.25:.8,data.length,anchor);renderWave();};
 $('scaleLabel').textContent=`样点 ${view.start.toFixed(1)}–${view.end.toFixed(1)} / ${data.length}`;
 updateMeasurement();renderOverview();document.dispatchEvent(new CustomEvent('gwx:view',{detail:{...view,A:a,B:b}}));
}
function updateMeasurement(){const dt=M.samplePeriod(record),clock=record?.clock_hz||27000000;for(const [id,value]of[['markerA',a],['markerB',b]])$(id).textContent=value===null?'未设置':`#${value} · ${dt?M.formatTime(value*dt):'无时间基准'}`;const m=M.measurement(record,a,b);$('deltaTime').textContent=m?M.formatTime(m.seconds)+` / ${m.samples} 点`:'—';$('deltaFreq').textContent=m?.frequency?formatHz(m.frequency):'—';$('sampleInfo').textContent=dt?record?.source==='INJECTED'?`样点间隔 ${M.formatTime(dt)} · UART 波形输入`:`间隔 ${M.formatTime(dt)} · 时钟 ${clock/1e6} MHz`:'本记录无采样时间基准';$('divider').oninput?.();}
function formatHz(value){return value>=1e6?(value/1e6).toFixed(3)+' MHz':value>=1e3?(value/1e3).toFixed(3)+' kHz':value.toFixed(2)+' Hz';}
function panel(name){for(const button of document.querySelectorAll('[data-panel]'))button.classList.toggle('active',button.dataset.panel===name);for(const content of document.querySelectorAll('.panel-content'))content.hidden=content.id!=='panel-'+name;document.dispatchEvent(new CustomEvent('gwx:panel',{detail:{panel:name}}));}
function showRecord(r,reset=true){record=r;if(reset){view={start:0,end:r?.samples?.length||64};a=b=null;}$('recordTitle').textContent=r?`采集 #${r.id} · ${r.status==='PASS'?(r.faults.length?'检出故障':'正常'):labels[r.status]||r.status}`:'未选择采集';$('provenance').textContent=r?`${originName(r.origin)} / ${r.source==='INTERNAL'?'板内信号':r.source==='EXTERNAL'?'外部输入':r.source==='INJECTED'?'串口注入 / 板端分析':r.source}`:'等待记录';$('rawRecord').hidden=!r;if(r)$('rawRecord').href='/record/'+r.id+'.txt';$('faultCount').textContent=r?.faults?.length||0;
 $('recordMeta').textContent=r?`电脑接收：${r.received_at}`+(r.config?` · 本条配置：分频 ${r.config.divider} / ${r.source==='INJECTED'?'网页输入 / CPU分析':['正常','丢脉冲','周期异常','卡低','卡高'][r.config.mode]} / D${r.config.channel} · 右侧为下次采集设置`:' · 此记录无有效采样配置'):'尚未选择记录';
 $('faults').replaceChildren();if(!r)$('faults').innerHTML='<p class="empty">尚无记录</p>';else if(!r.faults.length)$('faults').innerHTML='<div class="result-note">'+esc(r.status==='PASS'?'当前窗口未检出符合规则的故障':(labels[r.status]||r.status)+' · '+(r.error||''))+'</div>';else for(const f of r.faults){const button=document.createElement('button');button.className='fault-item';button.innerHTML=`<span class="fault-badge">D${f.channel}</span><b>${esc(labels[f.code]||f.code)}</b><span>样点 #${f.index} · 间隔 ${f.gap} 点</span><span class="hint">定位 →</span>`;button.onclick=()=>{channels[f.channel].visible=true;renderChannels();const n=r.samples.length,start=M.clamp(f.index-8,0,Math.max(0,n-20));view={start,end:Math.min(n,start+20)};a=f.index;renderWave();};$('faults').append(button);}
 const pmu=r?.analysis;const metrics=pmu?[['周期',pmu.cycles],['退休指令',pmu.retired],['检测区间 CPI',pmu.retired?(pmu.cycles/pmu.retired).toFixed(3):'—'],['分支',pmu.branches],['数据等待',pmu.data_stalls],['取指等待',pmu.fetch_stalls],['前递事件',pmu.forward_events],['重定向',pmu.flush_events]]:[];
 $('pmu').innerHTML=metrics.length?metrics.map(([name,value])=>`<div class="metric"><span>${name}</span><strong>${esc(value)}</strong></div>`).join(''):'<p class="empty">本记录没有处理器计数</p>';
 const hex=v=>Number(v).toString(16).toUpperCase().padStart(8,'0');$('trace').innerHTML=(r?.trace||[]).map(t=>`<tr><td class="mono">${hex(t.pc)}</td><td class="mono">${hex(t.instruction)}</td><td class="mono">${t.write?'x'+t.rd+' ← '+hex(t.data):'—'}</td></tr>`).join('');renderWave();updateStudio();document.dispatchEvent(new CustomEvent('gwx:record',{detail:r}));}
function renderHistory(){loadHistory().catch(e=>message(e.message,true));}
async function refreshHistory(){await loadHistory();}
async function refreshEvents(){const rows=await request('/api/events');$('events').replaceChildren();for(const r of rows){const div=document.createElement('div');div.className='event-row';const time=document.createElement('time');time.textContent=r.received_at;const text=document.createElement('span');text.textContent=r.message;div.append(time,text);$('events').append(div);}if(!rows.length)$('events').innerHTML='<p class="empty">暂无运行日志</p>';}
async function refreshBenchmarks(){const rows=await request('/api/benchmarks');$('benchmarks').innerHTML=rows.length?rows.map(r=>`<div class="benchmark-card"><div class="row"><b>#${r.id} · ${r.mode===0?'性能组':'校验组'}</b><span class="tag">${originName(r.origin)}</span><span>${r.valid?'有效完整记录':'校验待通过'}</span></div><p>${esc(r.received_at)} · ${r.iterations} 次 · ${Number(r.seconds).toFixed(6)} s · CRC ${r.crc_ok?'通过':'失败'}</p><strong>${r.valid?Number(r.iterations_per_second).toFixed(4)+' 次/秒 · '+Number(r.coremark_per_mhz).toFixed(6)+' / MHz':'请查看校验结果与原始输出'}</strong><p><a href="/benchmark/${r.id}.txt">下载完整原始输出</a></p></div>`).join(''):'<p class="empty">尚无完整跑分记录</p>';}
function config(suite=false){const cfg={cmd:suite?3:Number($('source').value)};for(const k of['divider','trigger','pmin','pmax','missing','mode','channel']){cfg[k]=Number($(k).value);if(!Number.isInteger(cfg[k]))throw Error('配置必须为整数');}for(const k of['mask','value','monitor']){if(!/^[0-9a-fA-F]{1,2}$/.test($(k).value))throw Error('掩码与匹配值须为 00–FF');cfg[k]=parseInt($(k).value,16);}if(cfg.divider<1||cfg.divider>65535||cfg.monitor===0||cfg.pmin<2||cfg.pmin>cfg.pmax||cfg.pmax>=cfg.missing||cfg.missing>63)throw Error('请检查分频和规则：2 ≤ 最短 ≤ 最长 < 丢脉冲间隔 ≤ 63，检测掩码非零');return cfg;}
async function command(body,label,owner){if(busy)return false;if(window.gwxScopeAcquiring&&owner!=='scope'){message('请先停止连续采集，再执行其他设备任务',true);return false;}busy=true;updateControls();try{await request('/api/command',body);message(label+'已发送，等待完整记录和 READY');$('live').checked=true;return true;}catch(e){message(e.message,true);return false;}finally{busy=false;await poll();}}
function updateControls(){const s=lastStatus||{},available=s.connected&&s.ready&&!s.pending&&!busy&&!window.gwxScopeAcquiring&&!window.gwxFiveRunning;for(const id of['capture','suite','benchPerf','benchValid'])$(id).disabled=!available||(id.startsWith('bench')&&!benchmarkEnabled);$('config').querySelector('[type="submit"]').disabled=!available;$('sync').disabled=!s.connected||s.pending||busy||!!window.gwxScopeAcquiring;$('reconnect').disabled=!s.port||s.port==='未指定'||s.pending||busy||!!window.gwxScopeAcquiring;}
async function poll(){if(polling)return;polling=true;try{const s=await request('/api/status');lastStatus=s;document.dispatchEvent(new CustomEvent('gwx:status',{detail:s}));updateSession(s);$('divider').oninput?.();$('connectionDot').className=s.connected?'connected':'';$('status').textContent=s.connected?s.port+' · '+(s.pending?'处理中':s.ready?'就绪':'等待同步'):'离线分析';$('footerState').textContent=s.error||'波形分析 · 故障定位 · 日志导出';$('recordCount').textContent=`${s.count} 条采集 · ${s.benchmark_count} 条跑分`;updateControls();if(s.latest!==lastLatest){await refreshHistory();renderRecent(await request('/api/records'));if($('live').checked&&s.latest&&s.latest!==record?.id)showRecord(await request('/api/record?id='+s.latest));lastLatest=s.latest;}if(s.benchmark_latest!==lastBenchmark){await refreshBenchmarks();lastBenchmark=s.benchmark_latest;}}catch(e){lastStatus=null;$('connectionDot').className='';$('status').textContent='本地服务连接中断';$('footerState').textContent=e.message;updateControls();}finally{polling=false;}}
function download(name,text,type){const url=URL.createObjectURL(new Blob(['\uFEFF'+text],{type})),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
for(const button of document.querySelectorAll('[data-panel]'))button.onclick=()=>{panel(button.dataset.panel);if(button.dataset.panel==='events')refreshEvents().catch(e=>message(e.message,true));};
$('config').onsubmit=e=>{e.preventDefault();try{if(!$('config').reportValidity())return;command(config(),'采集配置');}catch(error){message(error.message,true);}};
$('capture').onclick=()=>$('config').requestSubmit();$('suite').onclick=()=>{try{command(config(true),'33 组板内自检');}catch(e){message(e.message,true);}};
$('benchPerf').onclick=()=>command({cmd:4,mode:0},'CoreMark 性能组');$('benchValid').onclick=()=>command({cmd:4,mode:1},'CoreMark 校验组');
for(const[id,path]of[['sync','/api/sync'],['reconnect','/api/reconnect']])$(id).onclick=async()=>{busy=true;updateControls();try{await request(path,{});message(id==='sync'?'已发送板内同步采集，请等待 READY':'正在重新打开串口，成功后请点击同步设备');}catch(e){message(e.message,true);}finally{busy=false;poll();}};
$('divider').oninput=()=>{const d=Number($('divider').value),clock=lastStatus?.connected?lastStatus.last_serial_clock_hz:null;$('sampleRate').textContent=!clock?'未连接设备':Number.isInteger(d)&&d>=1&&d<=65535?formatHz(clock/d).replace('Hz','S/s'):'分频超出范围';};
$('zoomIn').onclick=()=>{if(record?.samples.length){view=M.zoom(view,.65,record.samples.length);renderWave();}};$('zoomOut').onclick=()=>{if(record?.samples.length){view=M.zoom(view,1.5,record.samples.length);renderWave();}};$('fit').onclick=()=>{view={start:0,end:record?.samples.length||64};renderWave();};
for(const[id,direction]of[['panLeft',-1],['panRight',1]])$(id).onclick=()=>{if(record?.samples.length){view=M.pan(view,direction*(view.end-view.start)*.25,record.samples.length);renderWave();}};
$('clearCursors').onclick=()=>{a=b=null;renderWave();};$('resetView').onclick=()=>{channels=Array.from({length:8},(_,i)=>({name:'D'+i,visible:true}));renderChannels();persistChannels();$('fit').click();};
$('searchHistory').onclick=()=>{historyOffset=0;renderHistory();};$('historyQuery').oninput=()=>{clearTimeout(historyTimer);historyTimer=setTimeout(()=>{historyOffset=0;renderHistory();},260);};$('historyQuery').value=bootstrap.query||'';$('refreshEvents').onclick=()=>refreshEvents().catch(e=>message(e.message,true));
$('importButton').onclick=()=>$('file').click();$('file').onchange=async()=>{try{const f=$('file').files[0];if(!f)return;if(f.size>1000000)throw Error('文件请小于 1 MB');const result=await request('/api/import',{raw:await f.text()});await refreshHistory();if(result.id){$('live').checked=false;showRecord(await request('/api/record?id='+result.id));}message(`导入 ${result.count} 条采集、${result.benchmarks} 条跑分；标记为 IMPORTED`);}catch(e){message(e.message,true);}finally{$('file').value='';}};
$('exportSamples').onclick=()=>{if(!record?.samples?.length)return message('本记录没有有效样本',true);const dt=M.samplePeriod(record),rows=[['record_id','sample_index','nominal_time_s','byte_hex',...Array.from({length:8},(_,i)=>'D'+i)].join(',')];record.samples.forEach((v,i)=>rows.push([record.id,i,dt===null?'':(i*dt).toPrecision(12),v.toString(16).toUpperCase().padStart(2,'0'),...Array.from({length:8},(_,ch)=>(v>>ch)&1)].join(',')));download(`gwx_capture_${record.id}.csv`,rows.join('\r\n'),'text/csv;charset=utf-8');};
document.addEventListener('keydown',e=>{if(/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)||e.ctrlKey||e.altKey||e.metaKey||$('helpDialog').open||$('settingsDialog').open)return;if(e.key==='?'){e.preventDefault();$('helpButton').click();return;}if(e.key.toLowerCase()==='t'){e.preventDefault();$('themeToggle').click();return;}if(e.key.toLowerCase()==='w'){e.preventDefault();$('focusWave').click();return;}if(e.key==='Escape'&&document.body.classList.contains('waveform-focus')){$('focusWave').click();return;}const id={'+':'zoomIn','=':'zoomIn','-':'zoomOut','f':'fit','F':'fit','ArrowLeft':'panLeft','ArrowRight':'panRight'}[e.key];if(id){e.preventDefault();$(id).click();}});
let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(renderWave,100);});

let historyOffset=0,historyTotal=0,historyTimer=null,historyEpoch=0;
const noteKey=()=>record?'gwx.note.'+record.id+'.'+record.received_at:null;
function noteText(){try{return noteKey()?localStorage.getItem(noteKey())||'':'';}catch(e){return '';}}
function updateStudio(){
 const dt=M.samplePeriod(record),n=record?.samples?.length||0;
 $('summarySource').textContent=record?(originName(record.origin)):'尚无记录';
 $('summarySourceSub').textContent=record?(record.source==='INTERNAL'?'板内信号 / 历史来源':record.source==='EXTERNAL'?'外部信号 / 历史来源':record.source==='INJECTED'?'网页数据 → FPGA CPU → 串口回读':'无有效信号'):'等待有效数据';
 $('summaryRateLabel').textContent=record?.source==='INJECTED'?'虚拟采样率':'采样率';
 $('summaryRate').textContent=dt?formatHz(1/dt).replace('Hz','S/s'):'—';
 $('summaryClock').textContent=dt?(record.source==='INJECTED'?'UART 波形时基':`名义 ${(record.clock_hz||27000000)/1e6} MHz`):'本条记录无时间基准';
 $('summaryWindow').textContent=dt&&n?M.formatTime(n*dt):'—';
 $('summaryFaults').textContent=record?(record.status==='PASS'?(record.faults.length?record.faults.length+' 处异常':'未检出异常'):labels[record.status]||record.status):'—';
 $('summaryFaultSub').textContent=n?`${n} 点 × 8 通道`:'无有效采样点';
 $('measurements').innerHTML=n?Array.from({length:8},(_,ch)=>{
  const st=M.channelStats(record,ch);return `<tr><td>D${ch} · ${esc(channels[ch].name)}</td><td>${st.rising.length} / ${st.falling.length}</td><td>${(100*st.highRatio).toFixed(1)}%</td><td>${st.meanPeriodSamples===null?'—':st.meanPeriodSamples.toFixed(2)}</td><td>${st.minPeriodSamples===null?'—':st.minPeriodSamples+'–'+st.maxPeriodSamples}</td><td>${st.frequency===null?'—':formatHz(st.frequency)}</td></tr>`;
 }).join(''):'<tr><td colspan="6" class="empty">本记录没有有效样本</td></tr>';
 for(const row of document.querySelectorAll('.channel-row')){
  const ch=Number(row.querySelector('.channel-index').textContent.slice(1));let meter=row.querySelector('.channel-meter');if(!meter){meter=document.createElement('div');meter.className='channel-meter';row.append(meter);}
  const st=M.channelStats(record,ch);meter.innerHTML=n?`<span>${st.edges.length} 跳变</span><i title="窗口高电平占比 ${(100*st.highRatio).toFixed(1)}%"><em style="width:${100*st.highRatio}%"></em></i>`:'<span>无样本</span>';
 }
 $('recordNote').disabled=!record;$('exportAnalysis').disabled=!record;$('recordNote').value=noteText();
 $('noteRecord').textContent=record?`采集 #${record.id} · 分析备注`:'选择记录后可添加备注。';
 $('noteStatus').textContent='支持为采集记录添加和保存分析备注。';
 renderOverview();
 for(const tr of $('history').querySelectorAll('tr'))tr.classList.toggle('selected',Number(tr.dataset.id)===record?.id);
}
function renderOverview(){
 const data=record?.samples||[];if(!data.length){$('overview').innerHTML='';return;}
 const width=1000,height=52;
 let content='';for(let ch=0;ch<8;ch++)content+=`<polyline transform="translate(0,${ch*6})" points="${M.points(data,ch,0,data.length,width,6)}" fill="none" stroke="var(--wave)" stroke-opacity=".35" stroke-width="1"/>`;
 const x=view.start/data.length*width,w=(view.end-view.start)/data.length*width;
 $('overview').innerHTML=`<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="全采集窗口总览，当前显示样点${view.start.toFixed(0)}至${view.end.toFixed(0)}">${content}<rect x="${x}" y="1" width="${w}" height="50" fill="var(--ink)" fill-opacity=".05" stroke="var(--ink)" stroke-width="1.5"/></svg>`;
 $('overview').onclick=e=>{const box=$('overview').getBoundingClientRect(),center=M.clamp((e.clientX-box.left)/box.width,0,1)*data.length,span=view.end-view.start,start=M.clamp(center-span/2,0,data.length-span);view={start,end:start+span};renderWave();};
}
function updateSession(s){
 const offline=!s.connected;$('offlineBadge').textContent=offline?'离线':'在线';$('workspaceState').textContent=offline?'离线分析':'设备已连接';$('sessionMode').textContent=offline?'离线分析':'设备工作空间';
 $('sessionDescription').textContent=offline?'板卡未连接，可查看、测量和导出已保存记录。':'记录来自串口，采集操作由设备执行。';
 $('connectionGuide').textContent=offline?'当前为离线模式。采集和跑分已禁用，已有记录可正常分析。':s.ready?'设备就绪，可配置并开始采集。':'等待设备完成当前操作。';
}
async function loadHistory(){
 const epoch=++historyEpoch,params=new URLSearchParams({q:$('historyQuery').value.trim(),origin:$('historyOrigin').value,result:$('historyResult').value,offset:String(historyOffset),limit:'50'});
 const result=await request('/api/records/search?'+params);if(epoch!==historyEpoch)return;
 history=result.items;historyTotal=result.total;if(historyOffset>=historyTotal&&historyOffset>0){historyOffset=Math.max(0,Math.floor((historyTotal-1)/50)*50);return loadHistory();}
 $('history').replaceChildren();for(const r of history){
  const tr=document.createElement('tr');tr.dataset.id=r.id;tr.classList.toggle('selected',r.id===record?.id);
  const td=document.createElement('td'),button=document.createElement('button');button.className='text-button';button.textContent='#'+r.id;button.onclick=async()=>{try{$('live').checked=false;showRecord(await request('/api/record?id='+r.id));}catch(e){message(e.message,true);}};td.append(button);tr.append(td);
  for(const value of[r.received_at,`${originName(r.origin)} / ${r.source==='INTERNAL'?'板内信号':r.source==='EXTERNAL'?'外部信号':r.source==='INJECTED'?'串口注入':r.source}`,r.faults.length?r.faults.map(f=>'D'+f.channel+' '+(labels[f.code]||f.code)).join('，'):r.status==='PASS'?'正常':labels[r.status]||r.status]){const cell=document.createElement('td');cell.textContent=value;tr.append(cell);}$('history').append(tr);
 }
 if(!history.length)$('history').innerHTML='<tr><td colspan="4" class="empty">没有匹配记录，试试更换关键词或筛选条件。</td></tr>';
 $('historyRange').textContent=historyTotal?`${historyOffset+1}–${Math.min(historyOffset+50,historyTotal)} / 共 ${historyTotal} 条`:'共 0 条';$('historyPrev').disabled=historyOffset===0;$('historyNext').disabled=historyOffset+50>=historyTotal;
}
$('historyOrigin').onchange=$('historyResult').onchange=()=>{historyOffset=0;renderHistory();};
$('historyPrev').onclick=()=>{historyOffset=Math.max(0,historyOffset-50);renderHistory();};$('historyNext').onclick=()=>{historyOffset+=50;renderHistory();};
$('quickImport').onclick=()=>$('importButton').click();
$('recordNote').oninput=()=>{if(!record)return;try{localStorage.setItem(noteKey(),$('recordNote').value);$('noteStatus').textContent='已保存到当前浏览器 · '+new Date().toLocaleTimeString('zh-CN');}catch(e){$('noteStatus').textContent='浏览器存储不可用，请使用“导出分析 JSON”保留备注。';}};
$('exportAnalysis').onclick=()=>{if(record)download(`gwx_analysis_${record.id}.json`,JSON.stringify({record_id:record.id,received_at:record.received_at,origin:record.origin,source:record.source,clock_hz:record.clock_hz||27000000,samples:record.samples,config:record.config,faults:record.faults,measurements:Array.from({length:8},(_,ch)=>M.channelStats(record,ch)),note:$('recordNote').value,cursors:{A:a,B:b},nominal_clock_not_calibrated:true},null,2),'application/json;charset=utf-8');};
for(const[id,dir]of[['prevEdge',-1],['nextEdge',1]])$(id).onclick=()=>{if(!record?.samples?.length)return message('本记录没有有效样本',true);const st=M.channelStats(record,Number($('edgeChannel').value)),edge=M.nextEdge(st.edges,a===null?(dir>0?-1:record.samples.length):a,dir);if(edge===null)return message('当前方向没有更多跳变沿');a=edge;const n=record.samples.length,span=Math.min(20,n),start=M.clamp(edge-8,0,n-span);view={start,end:start+span};channels[st.channel].visible=true;renderChannels();renderWave();updateStudio();message(`D${st.channel} · 已定位到样点 #${edge}`);};
$('themeToggle').onclick=()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('gwx.theme.black-default',theme);}catch(e){}renderWave();};
try{document.documentElement.dataset.theme=localStorage.getItem('gwx.theme.black-default')==='light'?'light':'dark';}catch(e){document.documentElement.dataset.theme='dark';}
$('focusWave').onclick=()=>{const focused=document.body.classList.toggle('waveform-focus');$('focusWave').textContent=focused?'退出专注':'专注波形';requestAnimationFrame(renderWave);};
$('helpButton').onclick=()=>$('helpDialog').showModal();$('closeHelp').onclick=()=>$('helpDialog').close();
$('exportSvg').onclick=()=>{const original=$('wave').querySelector('svg');if(!original)return message('没有可导出的波形',true);const svg=original.cloneNode(true),style=getComputedStyle(document.documentElement);svg.setAttribute('xmlns','http://www.w3.org/2000/svg');const background=document.createElementNS('http://www.w3.org/2000/svg','rect');background.setAttribute('width','100%');background.setAttribute('height','100%');background.setAttribute('fill',style.getPropertyValue('--surface').trim());svg.prepend(background);const markup=new XMLSerializer().serializeToString(svg).replace(/var\(--([a-z-]+)\)/g,(_,key)=>style.getPropertyValue('--'+key).trim());download(`gwx_waveform_${record.id}.svg`,markup,'image/svg+xml;charset=utf-8');};


$('openSettings').onclick=()=>$('settingsDialog').showModal();$('closeSettings').onclick=()=>$('settingsDialog').close();
$('overviewToggle').onclick=()=>{const visible=$('overviewWrap').hidden;$('overviewWrap').hidden=!visible;$('overviewToggle').textContent=visible?'隐藏总览':'显示总览';renderOverview();};
$('recordDetails').onclick=()=>{$('recordMeta').hidden=!$('recordMeta').hidden;};
$('sidebarToggle').onclick=()=>{document.body.classList.toggle(matchMedia('(max-width:900px)').matches?'sidebar-expanded':'sidebar-collapsed');};
$('sidebarClose').onclick=()=>$('sidebarToggle').click();
$('sidebarImport').onclick=()=>$('importButton').click();
for(const[id,name]of[['sidebarHistory','history'],['sidebarNotes','notes'],['sidebarEvents','events']])$(id).onclick=()=>{panel(name);if(name==='events')refreshEvents().catch(e=>message(e.message,true));document.body.classList.remove('sidebar-expanded');};
function renderRecent(rows){$('recentRecords').replaceChildren();for(const r of rows.slice(0,6)){const button=document.createElement('button');button.className='recent-record';button.innerHTML=`<span>采集 #${r.id}</span><small>${r.faults.length?r.faults.map(f=>'D'+f.channel+' '+(labels[f.code]||f.code)).join('，'):r.status==='PASS'?'正常信号':labels[r.status]||r.status}</small>`;button.onclick=async()=>{try{$('live').checked=false;showRecord(await request('/api/record?id='+r.id));document.body.classList.remove('sidebar-expanded');}catch(e){message(e.message,true);}};$('recentRecords').append(button);}}
renderRecent(bootstrap.history);
document.addEventListener('click',e=>{if(e.target.closest('.tools-dropdown button,.tools-dropdown a'))document.querySelector('.tools-menu').open=false;});

if(new URLSearchParams(location.search).has('id'))$('live').checked=false;
renderChannels();showRecord(record);renderHistory();poll();setInterval(poll,1200);
window.gwxAI = {request, config, showRecord, message, panel, command, getRecord:()=>record, getStatus:()=>lastStatus,getView:()=>({...view,A:a,B:b}),setView:(start,end)=>{const n=record?.samples?.length||0;if(n<4||!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return;const span=M.clamp(end-start,4,n);start=M.clamp(start,0,n-span);view={start,end:start+span};renderWave();},setCursors:(aa,bb)=>{const n=record?.samples?.length||0;a=Number.isInteger(aa)&&aa>=0&&aa<n?aa:null;b=Number.isInteger(bb)&&bb>=0&&bb<n?bb:null;renderWave();},setChannelVisible:(ch,on)=>{if(Number.isInteger(ch)&&ch>=0&&ch<8){channels[ch].visible=!!on;renderChannels();persistChannels();}},getChannels:()=>channels.map(c=>({...c})),updateControls,focusChannel:(ch)=>{channels.forEach(c=>c.visible=true);renderChannels();const f=record?.faults?.find(f=>f.channel===ch);if(f){a=f.index;view={start:Math.max(0,f.index-10),end:Math.min(record.samples.length,f.index+22)};}else view={start:0,end:record?.samples?.length||64};renderWave();}};
})();





