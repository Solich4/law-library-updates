"""Stage article boundaries and exact diagnostic comparisons of cached official HTML.

No source replacements or review approvals. Typography normalization is diagnostic
only; every differing provision remains available for reading in the report.
"""
import copy
import json
import re
from pathlib import Path
from lxml import html

ROOT = Path(__file__).resolve().parents[2]
ARTICLE = re.compile(r'^Статья\s+(\d+(?:\.\d+)*(?:-\d+)?)\.(?:\s|$)')


def _editorial_punctuation(parent):
    """Remove punctuation split outside an explicitly marked editorial group.

    Some public HTML closes `(В редакции ...)` outside its mark span, or
    splits the comma between two marked act references into an ed span.
    Never infer a correction from unbalanced normative punctuation.
    """
    depth = 0
    for child in list(parent):
        classes = set((child.get('class') or '').split())
        marked = bool(classes & {'mark', 'markx'})
        value = child.text_content()
        if marked:
            depth = max(0, depth + value.count('(') - value.count(')'))
        elif depth and re.fullmatch(r'[\s(),;]*', value):
            depth = max(0, depth + value.count('(') - value.count(')'))
            child.text = ''
            for nested in list(child):child.remove(nested)
        else:
            _editorial_punctuation(child)
            if value.strip():depth = 0
        if depth and child.tail:
            prefix = re.match(r'[\s),;]*', child.tail)[0]
            if prefix:
                closes = prefix.count(')')
                # Consume only a punctuation-only continuation of the marked
                # group, retaining any following normative words verbatim.
                if closes <= depth:
                    child.tail = child.tail[len(prefix):]
                    depth -= closes


def preceding_text(child):
    prefixes=[]
    while child.getparent() is not None:
        parent=child.getparent();parts=[parent.text or '']
        for sibling in parent:
            if sibling is child:break
            parts.extend([sibling.text_content(),sibling.tail or ''])
        prefixes.insert(0,''.join(parts))
        if parent.tag in {'p','td','th','body','div'}:break
        child=parent
    return ''.join(prefixes).rstrip()


def plain(node):
    node = copy.deepcopy(node)
    _editorial_punctuation(node)
    for child in node.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," mark ") or contains(concat(" ",normalize-space(@class)," ")," markx ")]'):
        child.drop_tree()
    for child in node.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," W9 ")]'):
        value = ''.join(child.itertext())
        if re.fullmatch(r'\d+(?:\.\d+)*(?:-\d+)*', value.strip()):
            # Provision indices also follow ordinal words and Roman chapter
            # numbers (третьей¹, V⁷). Only the explicit unit /м³ is treated as
            # a physical exponent here; do not infer from the last letter.
            prefix=preceding_text(child)
            child.text = (value.strip().translate(str.maketrans('0123456789','⁰¹²³⁴⁵⁶⁷⁸⁹'))
                          if re.search(r'(?:^|[\s/])(?:мкм|мм|см|км|м|m)$',prefix)
                          else '.'+value.strip())
            for nested in list(child):
                child.remove(nested)
    return ' '.join(node.text_content().split())


def parse(source, allow_historical_budget=False):
    tree = html.document_fromstring(source)
    bodies = tree.xpath('//body')
    if len(bodies) != 1:
        raise ValueError('Expected one body')
    articles = []
    current = None
    skipped = []
    for node_index, node in enumerate(bodies[0]):
        if not isinstance(node.tag, str):
            continue
        text = plain(node)
        classes = set((node.get('class') or '').split())
        images = [dict(src=image.get('src'), alt=image.get('alt'),
                       nodeIndex=node_index, anchor=node.get('id'))
                  for image in node.xpath('.//img | .//*[local-name()="imagedata"]')]
        if current is not None and images:
            current['sourceImages'].extend(images)
            current['unsupportedFormatting'].append('inline-image')
        if not text:
            if current is not None and node.text_content().strip():
                current['editorialNotes'].append(' '.join(node.text_content().split()))
            continue
        if 'T' in classes:
            current = None
            continue
        if classes & {'H', 'T'} and (re.match(r'^(Глава|Раздел|Подраздел|§)\s+[IVXLCDM\d]', text, re.I) or
                re.match(r'^ЧАСТЬ\s+(?:ПЕРВАЯ|ВТОРАЯ|ТРЕТЬЯ|ЧЕТВЕРТАЯ|ПЯТАЯ|ШЕСТАЯ)\.', text, re.I) or
                re.fullmatch(r'(?:Общая|Особенная)\s+часть|Часть\s+(?:первая|вторая|третья|четвертая|пятая|шестая)', text, re.I)):
            current = None
            continue
        if 'H' in classes:
            current = None
            match = ARTICLE.match(text)
            if match:
                current = dict(id=match[1], title=text, text=[],
                               officialAnchor=node.get('id'), editorialNotes=[],
                               unsupportedFormatting=[], sourceImages=[],textSources=[])
                articles.append(current)
            continue
        if current is None:
            continue
        original = ' '.join(node.text_content().split())
        if 'I' in classes and re.fullmatch(r'\d+\.\s*\(Статья\s+\d+\)', text):
            current['editorialNotes'].append(original)
            continue
        if node.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," mark ") or contains(concat(" ",normalize-space(@class)," ")," markx ")]') and re.fullmatch(r'(?:[\d.\s)–—-]+|[а-я]\s*\))', text, re.I):
            current['editorialNotes'].append(original)
            continue
        if classes & {'A', 'F', 'P'}:
            current['editorialNotes'].append(original)
            # Formatting annotations should not hide unmarked normative words.
            if text and classes & {'A', 'F'}:
                raise ValueError('Annotation has unmarked content: ' + current['id'])
            if not text:
                continue
        if re.match(r'^(Президент Российской Федерации|Председатель Верховного Совета|Москва, Кремль)', text) and not text.endswith(';'):
            current = None
            continue
        if not text:
            continue
        if node.tag == 'p':
            current['text'].append(text)
            current['textSources'].append(dict(anchor=node.get('id'),tag=node.tag,nodeIndex=node_index,hasImages=bool(images)))
        elif node.tag == 'table':
            current['text'].append(text)
            current['textSources'].append(dict(anchor=node.get('id'),tag=node.tag,nodeIndex=node_index,hasImages=bool(images)))
            current['unsupportedFormatting'].append('table-to-compare')
        else:
            skipped.append(dict(articleId=current['id'], tag=node.tag, text=original[:500]))
    ids = [a['id'] for a in articles]
    historical = []
    if allow_historical_budget:
        rows = [a for a in articles if a['id'] == '242.1']
        if len(rows) == 2:
            retired = [a for a in rows if not a['text'] and any('Утратила силу' in n for n in a['editorialNotes'])]
            live = [a for a in rows if a['text']]
            if len(retired) == 1 and len(live) == 1:
                historical = retired
                articles = [a for a in articles if a is not retired[0]]
                ids = [a['id'] for a in articles]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate official article headings')
    if not articles:
        raise ValueError('No official article headings')
    return dict(articles=articles, unparsedNodes=skipped, historicalDuplicateArticles=historical)

