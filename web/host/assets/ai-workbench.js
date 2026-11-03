(()=>{
  'use strict';
  const $=id=>document.getElementById(id),api=window.gwxAI;
  let offset=0,query='',total=0,lastCount=-1,loading=false;
  const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e;};
  function detail(row){
    const box=$('aiDetail');box.replaceChildren();
    box.append(text('h3',row.label),text('p',`D${row.channel} · 对应采集 #${row.capture_id} · ${row.origin==='SERIAL'?'板端串口返回':row.origin==='RTL_SIMULATION'?'RTL 离线仿真':row.origin==='ARCHIVED_SERIAL'?'历史串口归档':'离线导入记录'}`));
    const f=row.frame;
    if(row.rule_label)box.append(text('p',`规则检测：${row.rule_label} · AI 辅助诊断：${row.label} · ${row.ai_rule_agreement===true?'两者一致':row.ai_rule_agreement===false?'存在分歧，以规则检测为主':'AI 未给出有效结果'}`));
    if(row.origin==='RTL_SIMULATION')box.append(text('p','数据来源：RTL 仿真。'));
    box.append(text('p',`执行：${f.ACCEL?'硬件点积加速':'纯 RV32I CPU'} · 状态：${f.STATUS}`));
    if(f.STATUS==='PASS')box.append(text('p',`板端计数折算 ${f.nominal_inference_seconds.toFixed(2)} 秒 · 模型分数 ${f.SCORE_PERMILLE}/1000（未经概率校准）`));
    box.append(text('p',`模型CRC ${f.MODEL_CRC.toString(16).toUpperCase()} · 原始数据在本机保存`));
    const view=text('button','查看对应波形');view.onclick=async()=>{try{api.showRecord(await api.request('/api/record?id='+row.capture_id));$('live').checked=false;}catch(e){api.message(e.message,true);}};
    const download=text('button','导出本条结果');download.onclick=async()=>{try{const result=await api.request('/api/ai/result?id='+row.id),blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`gwx_board_ai_${row.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){api.message(e.message,true);}};
    const buttons=document.createElement('div');buttons.className='row';buttons.append(view,download);box.append(buttons);
  }
  async function refresh(){
    const data=await api.request(`/api/ai/results?offset=${offset}&limit=20&q=${encodeURIComponent(query)}`);total=data.total;$('aiTotal').textContent=`共 ${total} 条`;$('aiRows').replaceChildren();
    for(const r of data.items){const tr=document.createElement('tr');tr.append(text('td',new Date(r.received_at).toLocaleString('zh-CN')),text('td',`D${r.channel} / ${r.source==='INTERNAL'?'内部':'外部'}`),text('td',r.label),text('td',r.frame.STATUS==='PASS'?r.frame.nominal_inference_seconds.toFixed(2)+' 秒':'—'));const td=document.createElement('td'),b=text('button','查看');b.onclick=()=>detail(r);td.append(b);tr.append(td);$('aiRows').append(tr);}
    if(!data.items.length){const tr=document.createElement('tr'),td=text('td','暂无匹配的板端诊断记录');td.colSpan=5;tr.append(td);$('aiRows').append(tr);}
    $('aiPrev').disabled=offset===0;$('aiNext').disabled=offset+20>=total;
    if(data.items.length&&offset===0&&!query)detail(data.items[0]);
  }
  async function poll(){
    if(loading)return;loading=true;
    try{const s=await api.request('/api/status');$('aiRun').disabled=!(s.connected&&s.ready&&!s.pending&&!window.gwxScopeAcquiring&&!window.gwxFiveRunning);
      $('aiStatus').textContent=s.ai_running?`盘古50正在推理 · 已等待 ${Math.floor(s.ai_elapsed_seconds||0)} 秒 · 请保持连接`:s.error?'设备提示：'+s.error:s.connected?(s.ready?'设备就绪，可采集并诊断':'等待设备完成当前命令或同步'):'当前未连接板卡，可浏览已保存结果';
      if(s.ai_count!==lastCount){lastCount=s.ai_count;await refresh();}
      const external=$('source').querySelector('option[value="1"]');if(external){external.disabled=!s.external_enabled;external.textContent=s.external_enabled?'外部输入 · 接线核对后使用':'外部输入 · 尚未启用';}
    }catch(e){$('aiStatus').textContent='本地服务连接中断：'+e.message;$('aiRun').disabled=true;}finally{loading=false;}
  }
  $('aiRun').onclick=async()=>{
    if(window.gwxScopeAcquiring)return api.message('请先停止连续采集，再运行AI',true);
    $('aiRun').disabled=true;
    try{const cfg=api.config(false);cfg.mode=Number($('aiScenario').value);cfg.channel=Number($('aiChannel').value);await api.request('/api/ai/command',{config:cfg,software:$('aiPath').value==='cpu'});$('live').checked=true;api.message('已发送板端AI命令；等待完整模型结果，不重复发送。');}catch(e){api.message(e.message,true);}finally{await poll();}
  };
  $('aiSearch').onclick=()=>{query=$('aiQuery').value.trim();offset=0;refresh().catch(e=>api.message(e.message,true));};
  $('aiPrev').onclick=()=>{offset=Math.max(0,offset-20);refresh().catch(e=>api.message(e.message,true));};
  $('aiNext').onclick=()=>{if(offset+20<total)offset+=20;refresh().catch(e=>api.message(e.message,true));};
  poll();setInterval(poll,1500);
})();
