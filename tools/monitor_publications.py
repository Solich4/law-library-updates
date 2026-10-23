"""Detect new official publications. Never approve, sign or publish legal text.

The RSS window is finite. A failed download or lost overlap is an error, not a
statement that laws did not change. Unknown-scope publications stay in the queue.
"""
import argparse
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

FEEDS={name:'https://publication.pravo.gov.ru/api/rss?block='+name+'&pageSize=200'
       for name in ('president','court')}

def fetch_feed(url):
    failures=[]
    # Plain HTTP is only a fallback for an untrusted change-detection trigger.
    # It never approves text or supplies any APK/content signing decision.
    for endpoint,timeout in ((url,8),(url.replace('https://','http://',1),25)):
        try:
            req=urllib.request.Request(endpoint,headers={'User-Agent':'LawLibrary-publication-monitor/1.0','Accept':'application/rss+xml, application/xml'})
            with urllib.request.urlopen(req,timeout=timeout) as response:data=response.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError('RSS exceeds size limit')
            parse_feed(data)
            return data,'https' if endpoint.startswith('https:') else 'http-untrusted-trigger-only'
        except Exception as error:failures.append(str(error))
    raise OSError('; '.join(failures))


def parse_feed(data):
    root=ET.fromstring(data)
    if root.tag!='rss':raise ValueError('Expected official RSS, not an HTML/error page')
    channel=root.find('channel')
    if channel is None:raise ValueError('Missing RSS channel')
    items=[]
    for node in channel.findall('item'):
        title=' '.join(node.findtext('title','').split())
        link=node.findtext('link','').strip()
        parsed=urlsplit(link)
        if parsed.hostname!='publication.pravo.gov.ru' or parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.port not in (None,80,443):
            raise ValueError('RSS contains an unexpected publication URL')
        if not re.fullmatch(r'/document/\d{16}',parsed.path):raise ValueError('Invalid official publication identifier')
        date_text=re.sub(r'([+-]\d{2}):(\d{2})$',r'\1\2',node.findtext('pubDate',''))
        published=parsedate_to_datetime(date_text)
        if published.tzinfo is None:raise ValueError('RSS date lacks timezone')
        if not title:raise ValueError('Publication without title')
        normalized_link='https://publication.pravo.gov.ru'+parsed.path
        items.append(dict(id=parsed.path.rsplit('/',1)[1],title=title,url=normalized_link,
            publishedAt=published.astimezone(timezone.utc).isoformat(),
            metadataHash=hashlib.sha256((title+'\n'+normalized_link).encode()).hexdigest()))
    if not items:raise ValueError('Empty RSS cannot establish absence of amendments')
    if len({a['id'] for a in items})!=len(items):raise ValueError('Duplicate publication IDs')
    return items


def update_feed(previous,items,since):
    known=previous.get('known',{})
    oldest=min(datetime.fromisoformat(a['publishedAt']) for a in items)
    ids={a['id'] for a in items}
    overlap=bool(ids & set(known))
    # If the entire old window disappeared, a period may have fallen out of RSS.
    gap=bool(known) and not overlap
    if not known and oldest>since:gap=True
    changes=[]
    for item in items:
        old=known.get(item['id'])
        if old and old!=item['metadataHash']:
            changes.append(item|dict(reason='publication-metadata-changed'))
        elif not old and datetime.fromisoformat(item['publishedAt'])>=since:
            changes.append(item|dict(reason='new-publication'))
    return dict(known={a['id']:a['metadataHash'] for a in items}),changes,gap


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',default='.monitor/state.json')
    parser.add_argument('--report',default='.monitor/review-queue.json')
    parser.add_argument('--since',required=True,help='First date for monitoring; does not certify earlier law')
    parser.add_argument('--fixture-dir',help='Offline transport test using saved official feeds')
    args=parser.parse_args()
    since=datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    state_path,report_path=Path(args.state),Path(args.report)
    state=json.loads(state_path.read_text('utf-8')) if state_path.exists() else dict(feeds={},pending={})
    new_feeds={};pending=dict(state.get('pending',{}));problems=[];transports={}
    for name,url in FEEDS.items():
        try:
            if args.fixture_dir:data=(Path(args.fixture_dir)/(name+'-rss.xml')).read_bytes();transports[name]='offline-fixture'
            else:
                data,transports[name]=fetch_feed(url)
            items=parse_feed(data)
            new_feed,changes,gap=update_feed(state.get('feeds',{}).get(name,{}),items,since)
            if gap:problems.append(name+': finite RSS window does not cover the monitoring gap')
            new_feeds[name]=new_feed
            for row in changes:
                row['sourceGroup']=name
                row['reviewStatus']='scope-and-legal-effect-not-reviewed'
                # Retain unknown-scope acts too: titles may say only "other laws".
                pending[row['id']]=row
            print(name,':',len(items),'items,',len(changes),'new/changed publications')
        except Exception as error:
            problems.append(name+': '+str(error))
    report=dict(checkedAt=datetime.now(timezone.utc).isoformat(),mode='offline-feed-test' if args.fixture_dir else 'live-official-trigger',transports=transports,
                lawCurrentnessConfirmed=False,contentPublished=False,monitoringSince=args.since,
                problems=problems,pendingReview=sorted(pending.values(),key=lambda r:r['publishedAt'],reverse=True))
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    # A partial outage must not advance the baseline and silently lose changes.
    if problems:
        # Preserve successfully observed publications without advancing either
        # feed's overlap baseline. A later outage must not erase the queue.
        state['pending']=pending
        state_path.parent.mkdir(parents=True,exist_ok=True)
        state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n','utf-8')
        print('\n'.join(problems));raise SystemExit(1)
    state.update(feeds=new_feeds,pending=pending)
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n','utf-8')


if __name__=='__main__':main()
