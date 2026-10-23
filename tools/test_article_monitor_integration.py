import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import monitor_editions,article_changes
class FullArticleMonitor(unittest.TestCase):
 def test_detect_compare_persist_repeat_and_source_outage(self):
  oldmeta=dict(editionId=1,editionDate='20261001',officialBodyReady=True,futureEditions=[])
  newmeta=dict(oldmeta,editionId=2,editionDate='20261023')
  before='<html><body><p class="H">Статья 1. А</p><p>Текст</p><p class="H">Статья 2. Б</p><p>Норма</p><p class="H">Статья 3. В</p><p>Без изменений</p></body></html>'
  after=before.replace('<p>Текст</p>','<p>Новый текст</p>').replace('<p>Норма</p>','<p>Утратила силу.</p>').replace('</body>','<p class="H">Статья 4. Г</p><p>Добавленная норма</p></body>')
  previous_cwd=Path.cwd()
  with tempfile.TemporaryDirectory() as tmp:
   try:
    os.chdir(tmp);folder=Path('.monitor');folder.mkdir()
    (folder/'edition-baseline.json').write_text(json.dumps(dict(documents=[dict(id='labour',officialHash='fixture',**oldmeta)])),'utf-8')
    (folder/'article-baseline.json').write_text(json.dumps(dict(contentRevision=18,documents={'labour':dict(editionId=1,sourceSha256='fixture',articles=article_changes.snapshot(before,'labour'))})),'utf-8')
    with patch.object(sys,'argv',['monitor']),patch.object(monitor_editions,'fetch',return_value=newmeta),patch.object(article_changes,'fetch_text',return_value=(after,'test-source-hash')),patch('builtins.print'):
     monitor_editions.main()
    report=json.loads((folder/'edition-review-queue.json').read_text('utf-8'));self.assertEqual(report['contentRevision'],18)
    row=next(iter(report['pending'].values()));self.assertEqual(row['articleChangeGroups'][0]['changes'],[dict(article='1',kind='changed'),dict(article='2',kind='repealed'),dict(article='4',kind='added')])
    with patch.object(sys,'argv',['monitor']),patch.object(monitor_editions,'fetch',return_value=newmeta),patch.object(article_changes,'fetch_text') as transport,patch('builtins.print'):
     monitor_editions.main();transport.assert_not_called()
    repeated=json.loads((folder/'edition-review-queue.json').read_text('utf-8'));self.assertEqual(repeated['pending'],report['pending'])
    state=(folder/'edition-state.json').read_bytes()
    with patch.object(sys,'argv',['monitor']),patch.object(monitor_editions,'fetch',side_effect=OSError('source down')),patch('builtins.print'):
     with self.assertRaises(SystemExit):monitor_editions.main()
    failed=json.loads((folder/'edition-review-queue.json').read_text('utf-8'));self.assertTrue(failed['errors']);self.assertEqual(failed['pending'],report['pending']);self.assertEqual((folder/'edition-state.json').read_bytes(),state)
   finally:os.chdir(previous_cwd)
