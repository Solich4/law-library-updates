import unittest
from article_changes import snapshot,compare,enrich
class ArticleChanges(unittest.TestCase):
 def source(self,rows):return '<html><body>'+''.join('<p class="H">Статья '+i+'. Заголовок</p><p>'+text+'</p>' for i,text in rows)+'</body></html>'
 def test_added_changed_and_explicit_repeal(self):
  a=snapshot(self.source([('1','Текст'),('2','Действующая норма'),('3','Без изменений')]),'test')
  b=snapshot(self.source([('1','Новый текст'),('2','Утратила силу.'),('3','Без изменений'),('4','Новая норма')]),'test')
  self.assertEqual(compare(a,b),[dict(article='1',kind='changed'),dict(article='2',kind='repealed'),dict(article='4',kind='added')])
 def test_missing_heading_is_not_automatically_repeal(self):
  a={str(i):dict(hash=str(i),retired=False) for i in range(1,11)};b=dict(a);del b['3']
  self.assertEqual(compare(a,b),[dict(article='3',kind='not-found')])
 def test_repealed_part_is_not_repealed_article(self):
  source=self.source([('1','<span class="mark">Часть 1 утратила силу.</span>')]);self.assertFalse(snapshot(source,'test')['1']['retired'])
 def test_already_retired_article_is_not_announced_again(self):
  old={'1':dict(hash='one',retired=True),'2':dict(hash='same',retired=False)}
  new={'1':dict(hash='different annotation',retired=True),'2':old['2']};self.assertEqual(compare(old,new),[])
 def test_reject_mass_heading_loss(self):
  with self.assertRaises(ValueError):compare({str(i):dict(hash=str(i),retired=False) for i in range(10)},{'1':dict(hash='1',retired=False)})
 def test_no_baseline_does_not_invent_changes(self):
  r=enrich(dict(document='constitution'),{});self.assertEqual(r['articleChangesStatus'],'unavailable');self.assertNotIn('articleChangeGroups',r)
 def test_inline_amendment_annotation_does_not_change_norm(self):
  a=self.source([('1','Текст нормы')]);b=self.source([('1','Текст нормы<span class="mark"> (В редакции закона)</span>')]);self.assertEqual(compare(snapshot(a,'test'),snapshot(b,'test')),[])
 def test_table_cell_spans_and_image_are_compared(self):
  a='<html><body><p class="H">Статья 1. Норма</p><table><tr><td>1</td></tr></table><p><img src="one.png"></p></body></html>'
  b=a.replace('src="one.png"','src="two.png"');self.assertEqual(compare(snapshot(a,'test'),snapshot(b,'test')),[dict(article='1',kind='changed')])
