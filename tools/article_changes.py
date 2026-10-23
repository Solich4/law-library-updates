"""Technical article comparison against the shipped, source-bound baseline.

Never changes application content or certifies a legal interpretation. Missing
headings are not described as repealed articles without an explicit marker.
"""
import hashlib,json,re,sys,time,urllib.parse,urllib.request
from pathlib import Path
from official_article_parser import parse,plain
from lxml import html

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def constitution_snapshot(source):
 nodes=html.document_fromstring(source).xpath('//div[@class="doc"]/*');articles={};current=None
 if not nodes:raise ValueError('Constitution source container unavailable')
 for node in nodes:
  text=' '.join(node.text_content().split())
  if text.startswith('КонсультантПлюс: примечание.'):continue
  match=re.fullmatch(r'Статья\s+(\d+(?:\.\d+)?)\s*(?:<\*>)?',text)
  if match:
   current=match[1]
   if current in articles:raise ValueError('Duplicate Constitution heading')
   articles[current]=[];continue
  if re.match(r'РАЗДЕЛ|Раздел|ГЛАВА|Глава',text):current=None;continue
  if text.startswith('---') or re.match(r'^<(?:\*|\d+)>',text):continue
  if current and text:articles[current].append(text)
 if len(articles)<137:raise ValueError('Incomplete Constitution extraction')
 result={}
 for identifier,parts in articles.items():
  text=re.sub(r'\s+',' ',re.sub(r'\s*<(?:\*|\d+)>','',' '.join(parts))).strip()
  result[identifier]=dict(hash=digest(text),retired=bool(re.match(r'^(?:исключена|утратила\s+силу)\b',text,re.I)) and len(text)<350)
 return result

def snapshot(source,document):
 parsed=parse(source,allow_historical_budget=document=='budget')
 if parsed['unparsedNodes']:raise ValueError('Unparsed normative source nodes')
 nodes=list(html.document_fromstring(source).xpath('//body')[0]);result={}
 for a in parsed['articles']:
  body=' '.join(a['text']).strip();notes=' '.join(a['editorialNotes'])
  # A repealed paragraph/part is not a repeal of its entire article.
  marker=re.compile(r'^\(?\s*(?:Статья\s+'+re.escape(a['id'])+r'\.?\s*)?(?:утратила\s+силу|исключена)\b',re.I)
  candidates=a['text']+a['editorialNotes']+[re.sub(r'^Статья\s+'+re.escape(a['id'])+r'\.?\s*','',a['title'])]
  retired=any(marker.match(value.strip()) for value in candidates) and (not a['text'] or all(marker.match(p.strip()) and len(p)<350 for p in a['text']))
  tables=[]
  for text_source in a['textSources']:
   if text_source['tag']=='table':
    table=nodes[text_source['nodeIndex']];tables.append([[plain(cell),cell.get('rowspan','1'),cell.get('colspan','1')] for cell in table.xpath('.//th|.//td')])
  images=[dict(src=i.get('src'),alt=i.get('alt')) for i in a['sourceImages']]
  fingerprint=digest(' '.join(body.split())) if document=='constitution' else digest(dict(title=a['title'],text=a['text'],tables=tables,images=images))
  result[a['id']]=dict(hash=fingerprint,retired=retired)
 return result

def compare(before,after):
 if len(after)<max(1,len(before)*.85):raise ValueError('Large unexplained loss of article headings')
 changes=[]
 def key(identifier):return tuple(int(p) for p in re.split(r'[.-]',identifier))
 for identifier in sorted(set(before)|set(after),key=key):
  old,new=before.get(identifier),after.get(identifier)
  if old is None:kind='added' if not new['retired'] else None
  elif new is None:kind=None if old['retired'] else 'not-found'
  elif old['retired'] and new['retired']:kind=None
  elif not old['retired'] and new['retired']:kind='repealed'
  elif old['hash']!=new['hash']:kind='changed'
  else:kind=None
  if kind:changes.append(dict(article=identifier,kind=kind))
 return changes

def fetch_text(edition,deadline=None):
 url='http://actual.pravo.gov.ru:8000/api/ebpi/redtext/?'+urllib.parse.urlencode(dict(bpa='ebpi',t=edition,ttl=1))
 request=urllib.request.Request(url,headers={'User-Agent':'LawLibrary-article-change-detector/1.0'})
 deadline=min(time.monotonic()+90,deadline or float('inf'))
 if deadline<=time.monotonic():raise TimeoutError('Article comparison run budget exhausted')
 with urllib.request.urlopen(request,timeout=min(25,max(1,deadline-time.monotonic()))) as response:
  chunks=[];size=0
  while True:
   if time.monotonic()>deadline:raise TimeoutError('Article source total timeout')
   part=response.read1(65536)
   if not part:break
   size+=len(part)
   if size>32*1024*1024:raise ValueError('Article source too large')
   chunks.append(part)
 raw=b''.join(chunks);reply=json.loads(raw)
 if reply.get('error') or not isinstance(reply.get('redtext'),str):raise ValueError('Official article text unavailable')
 return reply['redtext'],hashlib.sha256(raw).hexdigest()

def enrich(row,baseline,deadline=None):
 # No baseline means no invented article list (notably the Constitution when
 # the legacy bank has no completed body available).
 identifier=row['document'];base=baseline.get(identifier)
 if not base:return dict(row,articleChangesStatus='unavailable',articleChangeError='No comparable official article baseline')
 current=row['observed'];reason=row['reason']
 targets=[dict(editionId=current['editionId'],editionDate=current['editionDate'],future=False)]
 if reason=='new-deferred-edition':
  previous={e['editionId'] for e in row['baseline'].get('futureEditions',[])}
  targets=[dict(e,future=True) for e in current['futureEditions'] if e['editionId'] not in previous]
 identity=[t['editionId'] for t in targets]
 if row.get('articleChangesStatus')=='compared' and row.get('comparedEditionIds')==identity:return row
 groups=[]
 try:
  for target in targets:
   if target['editionId']==base['editionId']:changes=[];source_hash=base['sourceSha256']
   else:
    source,source_hash=fetch_text(target['editionId'],deadline=deadline);changes=compare(base['articles'],snapshot(source,identifier))
   groups.append(dict(target,changes=changes,sourceSha256=source_hash))
  return dict(row,articleChangesStatus='compared',comparedEditionIds=identity,articleChangeGroups=groups,comparisonBasis='technical-source-comparison-unreviewed',baselineEditionId=base['editionId'])
 except Exception as error:
  clean={k:v for k,v in row.items() if k not in ('articleChangeGroups','comparedEditionIds')}
  return dict(clean,articleChangesStatus='unavailable',articleChangeError=str(error)[:300])
