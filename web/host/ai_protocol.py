"""Strict, bounded board-AI frames; EXEC text alone is not proof of real hardware."""
import re
CODES=(447,445,457,455,459,453)
MODEL_REVISIONS={0x58a3be16:'r12',0xb3889358:'r13', 0x2a52a97d: 'r14'}
OPTIONAL_NUMBERS=('RUNTIME_VERSION',)
NUMBERS=('RECORD','CHANNEL','CLOCK_HZ','MODEL_CRC','ACCEL','EXPECTED_PERIOD','PROMPT_TOKENS','WORKING_BYTES',
         'INFERENCE_TICKS_LOW','INFERENCE_TICKS_HIGH','TOKEN','EOS','LABEL','SCORE_PERMILLE','DOT_GROUPS')
ERRORS={'MODEL_ERROR','ACCEL_ID_ERROR','OUT_OF_DOMAIN','CONTEXT_ERROR','INFERENCE_ERROR','INVALID_OUTPUT'}
def parse_ai_frame(raw):
 if not isinstance(raw,str)or len(raw)>8192:raise ValueError('AI frame size')
 lines=raw.replace('\r\n','\n').splitlines()
 if not lines or lines[0]!='GWX AI BEGIN'or lines[-1]!='GWX AI END':raise ValueError('AI frame boundary')
 fields={}
 for line in lines[1:-1]:
  if '='not in line:raise ValueError('AI frame line')
  k,v=line.split('=',1)
  if k in fields:raise ValueError('Duplicate AI field')
  if k not in (*NUMBERS,*OPTIONAL_NUMBERS,'STATUS','EXEC'):raise ValueError('Unknown AI field')
  fields[k]=v
 if fields.get('EXEC')!='FPGA_RV32I':raise ValueError('Unexpected execution declaration')
 status=fields.get('STATUS')
 if status!='PASS'and status not in ERRORS:raise ValueError('AI status')
 for k in (*NUMBERS,*OPTIONAL_NUMBERS):
  if k not in fields:
   if status=='PASS' and k in NUMBERS:raise ValueError('Missing AI field '+k)
   continue
  if not re.fullmatch('[0-9A-F]{8}',fields[k]):raise ValueError('Invalid AI number')
  fields[k]=int(fields[k],16)
 for k in ('CHANNEL','ACCEL','EXPECTED_PERIOD','MODEL_CRC','CLOCK_HZ'):
  if k not in fields:raise ValueError('Missing AI identity')
 if not 0<=fields['CHANNEL']<8 or fields['ACCEL']not in (0,1):raise ValueError('AI channel/path')
 if fields['MODEL_CRC']not in MODEL_REVISIONS or fields['CLOCK_HZ']!=27000000:raise ValueError('Unknown model/clock')
 if status=='PASS':
  if not 4<=fields['EXPECTED_PERIOD']<=16 or not 0<fields['PROMPT_TOKENS']<64:raise ValueError('AI input domain')
  if not 40000<fields['WORKING_BYTES']<65536 or not 0<=fields['SCORE_PERMILLE']<=1000:raise ValueError('AI runtime bounds')
  if fields['LABEL']>=6 or fields['TOKEN']!=CODES[fields['LABEL']]or fields['EOS']!=2:raise ValueError('Invalid diagnostic token')
  version=fields.get('RUNTIME_VERSION',1)
  if version not in (1,2):raise ValueError('Unknown runtime version')
  expected=(fields['PROMPT_TOKENS']+1)*4352 if version==1 else (fields['PROMPT_TOKENS']+1)*3840+1024
  if fields['DOT_GROUPS']!=expected:raise ValueError('Incomplete model computation count')
  fields['inference_ticks']=(fields['INFERENCE_TICKS_HIGH']<<32)|fields['INFERENCE_TICKS_LOW']
  if fields['inference_ticks']==0:raise ValueError('Zero inference duration')
  fields['nominal_inference_seconds']=fields['inference_ticks']/fields['CLOCK_HZ']
 fields['model_revision']=MODEL_REVISIONS[fields['MODEL_CRC']]
 fields['execution_is_self_declared']=True
 fields['physical_hardware_proven_by_frame_alone']=False
 fields['score_is_calibrated_probability']=False
 return fields

def complete_frames(text):
 return re.findall(r'GWX AI BEGIN\r?\n(?:(?!GWX AI BEGIN).)*?GWX AI END\r?\n',text,re.S)

def command_packet(*,external=False,accelerated=True,divider=270,mode=3,channel=0):
 if type(divider)is not int or not 1<=divider<=65535 or type(mode)is not int or not 0<=mode<=4 or type(channel)is not int or not 0<=channel<8:raise ValueError('Command parameters')
 cmd=(6 if external else 5)+(0 if accelerated else 2)
 data=bytearray([0xa5,0x5a,1,cmd,divider&255,divider>>8,255,16,0,255,6,10,14,mode,channel])
 check=0
 for v in data:check^=v
 data.append(check);return bytes(data)
