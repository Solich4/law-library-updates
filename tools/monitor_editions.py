"""Detect active/future edition changes. Never modify or approve legal content."""
import argparse,concurrent.futures,json,re,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
BASE='http://actual.pravo.gov.ru:8000/api/ebpi/redactions/'

def active_metadata(reply):
 if reply.get('error'):raise ValueError('Official bank returned an error')
 server=reply.get('serverdate','')[:10];datetime.fromisoformat(server)
 active=[e for e in reply['redactions'] if e.get('actual') is True]
 if len(active)!=1:raise ValueError('Ambiguous active edition')
 e=active[0]
 if not isinstance(e['redid'],int) or not re.fullmatch(r'\d{8}',e['reddate']):raise ValueError('Invalid edition identity')
 if e['reddate']>server.replace('-',''):raise ValueError('Future edition marked active')
 future=sorted({(x['redid'],x['reddate']) for x in reply['redactions'] if re.fullmatch(r'\d{8}',x.get('reddate','')) and x['reddate']>server.replace('-','')})
 return dict(editionId=e['redid'],editionDate=e['reddate'],officialBodyReady=all(e.get(k) is True for k in ['redofficial','redcompleted','contentcomplete','hascontent']),futureEditions=[dict(editionId=i,editionDate=d) for i,d in future])

def differences(baseline,observed):
 result=[]
 if (baseline['editionId'],baseline['editionDate'])!=(observed['editionId'],observed['editionDate']):result.append('active-edition-changed')
 if baseline.get('officialBodyReady')!=observed.get('officialBodyReady'):result.append('active-body-status-changed')
 before={(e['editionId'],e['editionDate']) for e in baseline.get('futureEditions',[])}
 if any((e['editionId'],e['editionDate']) not in before for e in observed['futureEditions']):result.append('new-deferred-edition')
 return result

def fetch(entry):
 query=urllib.parse.urlencode(dict(bpa='ebpi',t=json.dumps(dict(hash=entry['officialHash'],ttl=1))))
 request=urllib.request.Request(BASE+'?'+query,headers={'User-Agent':'LawLibrary-public-change-monitor/1.0'})
 with urllib.request.urlopen(request,timeout=25) as response:
  raw=response.read(4*1024*1024+1)
 if len(raw)>4*1024*1024:raise ValueError('Oversized edition metadata')
 reply=json.loads(raw)
 if reply.get('dochash')!=entry['officialHash']:raise ValueError('Unexpected official document identity')
 return active_metadata(reply)

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',default='.monitor/edition-baseline.json');parser.add_argument('--state',default='.monitor/edition-state.json');parser.add_argument('--queue',default='.monitor/edition-review-queue.json');a=parser.parse_args()
 baseline=json.loads(Path(a.baseline).read_text('utf-8'))['documents'];state_path=Path(a.state);previous=json.loads(state_path.read_text('utf-8')) if state_path.exists() else dict(observed={},pending={});pending=dict(previous.get('pending',{}));observed={};errors=[]
 def job(entry):
  try:return entry['id'],fetch(entry),None
  except Exception as error:return entry['id'],None,str(error)
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for identifier,current,error in pool.map(job,baseline):
   if error:errors.append(dict(document=identifier,error=error));continue
   observed[identifier]=current;old=previous.get('observed',{}).get(identifier) or next(d for d in baseline if d['id']==identifier)
   for reason in differences(old,current):
    key=identifier+':'+reason+':'+str(current['editionId'])+':'+','.join(str(e['editionId']) for e in current['futureEditions'])
    pending[key]=dict(document=identifier,reason=reason,baseline=old,observed=current,reviewRequired=True)
 report=dict(checkedAt=datetime.now(timezone.utc).isoformat(),scope='Detection only. No automatic legal interpretation, content replacement, signing or publication.',transport='Official legacy metadata endpoint uses HTTP; changes are untrusted review triggers until corroborated.',errors=errors,pending=pending,observed=observed)
 article_path=Path('.monitor/article-baseline.json')
 if article_path.exists():report['contentRevision']=json.loads(article_path.read_text('utf-8')).get('contentRevision',0)
 if article_path.exists() and pending:
  from article_changes import enrich
  article_baseline=json.loads(article_path.read_text('utf-8'))['documents']
  deadline=time.monotonic()+180
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   values=list(pool.map(lambda row:enrich(row,article_baseline,deadline=deadline),pending.values()))
  pending={key:value for key,value in zip(pending,values)};report['pending']=pending
 if errors:
  Path(a.queue).parent.mkdir(parents=True,exist_ok=True);Path(a.queue).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8');raise SystemExit('Official edition access failed; unchanged legislation cannot be inferred')
 state_path.parent.mkdir(parents=True,exist_ok=True);state_path.write_text(json.dumps(dict(observed=observed,pending=pending),ensure_ascii=False,indent=2)+'\n','utf-8');Path(a.queue).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8');print('Official editions checked:',len(observed),'; pending review:',len(pending))

if __name__=='__main__':main()
