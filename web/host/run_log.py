"""Live UART transcript. TX is emitted only after SerialPort.Write succeeds."""
import collections,threading,time,uuid,json,hashlib
from datetime import datetime

class RunLog:
    def __init__(self,path,capacity=4000):
        self.path=path;self.lock=threading.Lock();self.rows=collections.deque(maxlen=capacity)
        self.session=uuid.uuid4().hex;self.seq=0
        self.append('HOST','Receiver session started; waiting for an actual device connection.')
    def append(self,kind,text,port=None):
        text=str(text)
        if not text:return
        with self.lock:
            self.seq+=1
            row=dict(seq=self.seq,session=self.session,received_at=datetime.now().astimezone().isoformat(timespec='milliseconds'),kind=kind,port=port,text=text,sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
            self.rows.append(row)
            with self.path.open('a',encoding='utf-8')as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    def snapshot(self,after=0,limit=300):
        if not 0<=after<=10**12 or not 1<=limit<=4000:raise ValueError('invalid transcript cursor')
        with self.lock:
            rows=[dict(x) for x in self.rows if x['seq']>after][:limit]
            first=self.rows[0]['seq'] if self.rows else 0
            return dict(session=self.session,items=rows,cursor=rows[-1]['seq'] if rows else min(after,self.seq),head=self.seq,gap=bool(after and after<first-1),first_available=first,source='live_uart_transport')
