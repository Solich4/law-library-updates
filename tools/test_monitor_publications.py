import unittest
import json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
from monitor_publications import parse_feed,update_feed


class Monitor(unittest.TestCase):
    def test_http_fallback_is_marked_as_untrusted_trigger(self):
        import monitor_publications as monitor
        data=self.feed()
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return data
        with patch.object(monitor.urllib.request,'urlopen',side_effect=[OSError('TLS unavailable'),Reply()]) as request:
            returned,transport=monitor.fetch_feed(monitor.FEEDS['president'])
        self.assertEqual(returned,data)
        self.assertEqual(transport,'http-untrusted-trigger-only')
        self.assertTrue(request.call_args_list[1].args[0].full_url.startswith('http://publication.pravo.gov.ru/api/rss?'))

    def test_partial_outage_retains_queue_without_advancing_baseline(self):
        import monitor_publications as monitor
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return self_data
        self_data=self.feed()
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)/'state.json';report=Path(tmp)/'report.json'
            original={'feeds':{},'pending':{}}
            state.write_text(json.dumps(original),'utf-8')
            args=['monitor','--state',str(state),'--report',str(report),'--since','2026-10-20']
            with patch.object(sys,'argv',args),patch.object(monitor.urllib.request,'urlopen',side_effect=[Reply(),OSError('test HTTPS outage'),OSError('test HTTP outage')]),patch('builtins.print'):
                with self.assertRaises(SystemExit):monitor.main()
            saved=json.loads(state.read_text('utf-8'))
            self.assertEqual(saved['feeds'],original['feeds'])
            self.assertIn('0001202610210001',saved['pending'])
            self.assertTrue(json.loads(report.read_text('utf-8'))['problems'])

    def feed(self,url='http://publication.pravo.gov.ru/document/0001202610210001'):
        return ('<rss><channel><item><title>Закон</title><link>'+url+'</link>'
                '<pubDate>Wed, 21 Oct 2026 00:00:00 +03:00</pubDate></item></channel></rss>').encode()

    def test_parse_official_feed_and_normalize_timezone(self):
        row=parse_feed(self.feed())[0]
        self.assertEqual(row['publishedAt'],'2026-10-20T21:00:00+00:00')
        self.assertTrue(row['url'].startswith('https://publication.pravo.gov.ru/'))

    def test_reject_error_html_or_empty_feed(self):
        for data in [b'<html>Access denied</html>',b'<rss><channel/></rss>']:
            with self.assertRaises(ValueError):parse_feed(data)

    def test_reject_foreign_link(self):
        with self.assertRaises(ValueError):parse_feed(self.feed('https://publication.pravo.gov.ru.evil.test/document/0001202610210001'))

    def test_unchanged_is_quiet_and_metadata_change_queues(self):
        items=parse_feed(self.feed());since=datetime(2026,10,21,tzinfo=timezone.utc)
        state,_,_=update_feed({},items,since)
        self.assertEqual(update_feed(state,items,since)[1],[])
        changed=[items[0]|{'metadataHash':'changed'}]
        self.assertEqual(update_feed(state,changed,since)[1][0]['reason'],'publication-metadata-changed')

    def test_lost_overlap_is_not_reported_as_no_changes(self):
        items=parse_feed(self.feed());since=datetime(2026,10,19,tzinfo=timezone.utc)
        self.assertTrue(update_feed({'known':{'old-id':'hash'}},items,since)[2])
