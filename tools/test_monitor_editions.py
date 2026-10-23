import copy,unittest
from monitor_editions import active_metadata,differences
class EditionTests(unittest.TestCase):
 def reply(self):return dict(error=None,serverdate='2026-10-23T00:00:00',redactions=[dict(actual=True,redid=10,reddate='20261001',redofficial=True,redcompleted=True,contentcomplete=True,hascontent=True)])
 def test_unchanged(self):
  m=active_metadata(self.reply());self.assertEqual(differences(m,m),[])
 def test_deferred_transition_detected_without_new_rss_publication(self):
  old=active_metadata(self.reply());r=self.reply();r['redactions'][0].update(redid=11,reddate='20261023');self.assertEqual(differences(old,active_metadata(r)),['active-edition-changed'])
 def test_new_future_edition_is_queued(self):
  old=active_metadata(self.reply());r=self.reply();r['redactions'].append(dict(actual=False,redid=12,reddate='20270101'));self.assertEqual(differences(old,active_metadata(r)),['new-deferred-edition'])
 def test_unready_active_edition_is_not_certified_and_status_change_is_detected(self):
  r=self.reply();old=active_metadata(r);r['redactions'][0]['redcompleted']=False;new=active_metadata(r);self.assertFalse(new['officialBodyReady']);self.assertEqual(differences(old,new),['active-body-status-changed'])
 def test_ambiguous_or_future_active_edition_rejected(self):
  for mutation in [lambda r:r['redactions'].append(copy.deepcopy(r['redactions'][0])),lambda r:r['redactions'][0].update(reddate='20270101')]:
   r=self.reply();mutation(r)
   with self.assertRaises(ValueError):active_metadata(r)
