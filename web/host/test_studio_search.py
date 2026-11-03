import json,tempfile,threading,sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from instrument_web import Store,make_handler
from instrument_protocol import Framer

def main():
    raw=Path(sys.argv[1]).read_bytes().decode('ascii')
    frames=[v for k,v in Framer().feed(raw) if k=='record']
    assert len(frames)==33
    with tempfile.TemporaryDirectory() as folder:
        s=Store(folder)
        for i in range(210):
            s.add(frames[i%33],'SERIAL' if i%2 else 'IMPORTED')
        assert len(s.records())==200
        assert s.search('#1')['items'][0]['id']==1
        assert s.search(limit=50)['total']==210
        assert s.search(offset=200,limit=50)['items'][-1]['id']==1
        assert s.search(origin='SERIAL')['total']==105
        for result in ('FAULT','NORMAL','ERROR'):
            found=s.search(result=result)
            assert all((bool(r['faults']) if result=='FAULT' else r['status']=='PASS' and not r['faults'] if result=='NORMAL' else r['status']!='PASS') for r in found['items'])
        assert s.search(query="%' OR 1=1 --")['total']==0
        assert s.search(query='%')['total']==0
        assert all(any(f['channel']==3 for f in r['faults']) for r in s.search(query='D3')['items'])
        assert s.search(query='周期异常')['total']>0
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(s,None,'test'))
        th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/records/search?q=%231&limit=50') as r:
                body=json.load(r)
                assert body['items'][0]['id']==1 and 'raw' not in body['items'][0] and 'samples' not in body['items'][0]
            for q in ('offset=-1','limit=99999','limit=oops','origin=EXTERNAL','result=nope','q='+'a'*81):
                try:
                    urlopen(base+'/api/records/search?'+q)
                    raise AssertionError('invalid query accepted')
                except HTTPError as e: assert e.code==400
        finally:
            server.shutdown();server.server_close();th.join()
    print('PASS full-history search, filters, literal SQL-safe query, pagination bounds and summary-only payload')

if __name__=='__main__': main()
