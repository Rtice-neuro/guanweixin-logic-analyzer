/* Pure data helpers; no synthetic records, network, or board controls. */
(function(root){'use strict';const names={NONE:'正常',MISSING_PULSE:'丢脉冲',PERIOD:'周期异常',STUCK:'电平卡死'};
function channel(samples,ch){if(!Number.isInteger(ch)||ch<0||ch>7)throw Error('invalid channel');return (samples||[]).map(v=>(v>>ch)&1);}
function difference(a,b,ch){if(!a?.samples?.length||a.samples.length!==b?.samples?.length)return null;const x=channel(a.samples,ch),y=channel(b.samples,ch);return x.reduce((n,v,i)=>n+(v!==y[i]),0);}
function byte(value){if(!Number.isInteger(value)||value<0||value>255)throw Error('invalid sample');return {hex:value.toString(16).toUpperCase().padStart(2,'0'),bits:Array.from({length:8},(_,i)=>(value>>(7-i))&1)};}
function channelState(record,ch){if(!record?.samples?.length)return {text:'无样本',fault:false};if(record.status!=='PASS')return {text:record.status,fault:true};const f=(record.faults||[]).find(f=>f.channel===ch);return {text:f?(names[f.code]||f.code):'未检出异常',fault:!!f,index:f?.index??null};}
const api={channel,difference,byte,channelState};root.GwxApplication=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
