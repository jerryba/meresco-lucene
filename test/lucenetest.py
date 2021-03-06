# -*- encoding: utf-8 -*-
## begin license ##
#
# "Meresco Lucene" is a set of components and tools to integrate Lucene (based on PyLucene) into Meresco
#
# Copyright (C) 2013-2014 Seecr (Seek You Too B.V.) http://seecr.nl
# Copyright (C) 2013-2014 Stichting Bibliotheek.nl (BNL) http://www.bibliotheek.nl
#
# This file is part of "Meresco Lucene"
#
# "Meresco Lucene" is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# "Meresco Lucene" is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with "Meresco Lucene"; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#
## end license ##


from os.path import join
import gc

from cqlparser import parseString as parseCql

from weightless.core import consume, retval

from meresco.lucene import Lucene, VM, DrilldownField, LuceneSettings
from meresco.lucene._lucene import IDFIELD
from meresco.lucene.hit import Hit
from meresco.lucene.fieldregistry import NO_TERMS_FREQUENCY_FIELDTYPE, FieldRegistry
from meresco.lucene.lucenequerycomposer import LuceneQueryComposer

from org.apache.lucene.search import MatchAllDocsQuery, TermQuery, TermRangeQuery, BooleanQuery, BooleanClause
from org.apache.lucene.document import Document, TextField, Field, NumericDocValuesField
from org.apache.lucene.index import Term
from org.apache.lucene.facet import FacetField
from org.meresco.lucene.analysis import MerescoDutchStemmingAnalyzer

from seecr.test import SeecrTestCase, CallTrace
from seecr.test.io import stdout_replaced
from seecr.utils.generatorutils import returnValueFromGenerator


class LuceneTest(SeecrTestCase):
    def __init__(self, *args):
        super(LuceneTest, self).__init__(*args)
        self._multithreaded = True

    def setUp(self):
        super(LuceneTest, self).setUp()
        self._javaObjects = self._getJavaObjects()
        self._reactor = CallTrace('reactor')
        self._defaultSettings = LuceneSettings(commitCount=1, commitTimeout=1, multithreaded=self._multithreaded, verbose=False, fieldRegistry=FieldRegistry(
                drilldownFields=[
                    DrilldownField(name='field1'),
                    DrilldownField(name='field2'),
                    DrilldownField('field3'),
                    DrilldownField('fieldHier', hierarchical=True),
                    DrilldownField('cat'),
                ]
            ))
        self.lucene = Lucene(
            join(self.tempdir, 'lucene'),
            reactor=self._reactor,
            settings=self._defaultSettings,
        )

    def tearDown(self):
        try:
            self._reactor.calledMethods.reset() # don't keep any references.
            self.lucene.close()
            self.lucene = None
            gc.collect()
            diff = self._getJavaObjects() - self._javaObjects
            self.assertEquals(0, len(diff), diff)
        finally:
            SeecrTestCase.tearDown(self)

    def _getJavaObjects(self):
        refs = VM._dumpRefs(classes=True)
        return set(
                [(c, refs[c])
                for c in refs.keys()
                if c != 'class java.lang.Class' and
                    c != 'class org.apache.lucene.document.Field' and # Fields are kept in FieldRegistry for reusing
                    c != 'class org.apache.lucene.facet.FacetsConfig'
            ])

    def hitIds(self, hits):
        return [hit.id for hit in hits]

    def testCreate(self):
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(0, result.total)

    def testAdd1Document(self):
        document = Document()
        document.add(TextField('title', 'The title', Field.Store.NO))
        returnValueFromGenerator(self.lucene.addDocument(identifier="identifier", document=document))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(1, result.total)
        self.assertEquals(['identifier'], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("title", 'title'))))
        self.assertEquals(1, result.total)
        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("title", 'the'))))
        self.assertEquals(1, result.total)
        self.assertTrue(result.queryTime > 0.0001, result.asJson())

    def testAdd1DocumentWithReadonlyLucene(self):
        settings = LuceneSettings(commitTimeout=1, multithreaded=self._multithreaded, verbose=False, readonly=True)
        readOnlyLucene = Lucene(
            join(self.tempdir, 'lucene'),
            reactor=self._reactor,
            settings=settings,
        )
        self.assertEquals(['addTimer'], self._reactor.calledMethodNames())
        timer = self._reactor.calledMethods[0]
        document = Document()
        document.add(TextField('title', 'The title', Field.Store.NO))
        returnValueFromGenerator(self.lucene.addDocument(identifier="identifier", document=document))
        result = returnValueFromGenerator(readOnlyLucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(0, result.total)
        timer.kwargs['callback']()
        result = returnValueFromGenerator(readOnlyLucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(1, result.total)

        readOnlyLucene.close()
        readOnlyLucene = None


    def testAddAndDeleteDocument(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=Document()))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=Document()))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=Document()))
        returnValueFromGenerator(self.lucene.delete(identifier="id:1"))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(2, result.total)
        self.assertEquals(set(['id:0', 'id:2']), set(self.hitIds(result.hits)))

    def testAddCommitAfterTimeout(self):
        self.lucene.close()
        self._defaultSettings.commitTimeout = 42
        self._defaultSettings.commitCount = 3
        self.lucene = Lucene(join(self.tempdir, 'lucene'), reactor=self._reactor, settings=self._defaultSettings)
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=Document()))
        self.assertEquals(['addTimer'], self._reactor.calledMethodNames())
        self.assertEquals(42, self._reactor.calledMethods[0].kwargs['seconds'])
        commit = self._reactor.calledMethods[0].kwargs['callback']
        self._reactor.calledMethods.reset()
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(0, result.total)
        commit()
        self.assertEquals([], self._reactor.calledMethodNames())
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(1, result.total)

    def testAddAndCommitCount3(self):
        self.lucene.close()
        self._defaultSettings.commitTimeout = 42
        self._defaultSettings.commitCount = 3
        self.lucene = Lucene(join(self.tempdir, 'lucene'), reactor=self._reactor, settings=self._defaultSettings)
        token = object()
        self._reactor.returnValues['addTimer'] = token
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=Document()))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(0, result.total)
        self.assertEquals(['addTimer'], self._reactor.calledMethodNames())
        self.assertEquals(42, self._reactor.calledMethods[0].kwargs['seconds'])

        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=Document()))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(0, result.total)
        self.assertEquals(['addTimer'], self._reactor.calledMethodNames())
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=Document()))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(3, result.total)
        self.assertEquals(['addTimer', 'removeTimer'], self._reactor.calledMethodNames())
        self.assertEquals(token, self._reactor.calledMethods[1].kwargs['token'])

    def testAddTwiceUpdatesDocument(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([
                ('field0', 'value0'),
                ('field1', 'value1'),
            ])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([
                ('field1', 'value1'),
            ])))
        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term('field1', 'value1'))))
        self.assertEquals(1, result.total)
        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term('field0', 'value0'))))
        self.assertEquals(0, result.total)

    def testSorting(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([
                ('field0', 'AA'),
                ('field1', 'ZZ'),
                ('field2', 'AA'),
            ])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([
                ('field0', 'BB'),
                ('field1', 'AA'),
                ('field2', 'ZZ'),
            ])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([
                ('field0', 'CC'),
                ('field1', 'ZZ'),
            ])))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), sortKeys=[dict(sortBy='field0', sortDescending=False)]))
        self.assertEquals(3, result.total)
        self.assertEquals(['id:0', 'id:1', 'id:2'], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), sortKeys=[dict(sortBy='field0', sortDescending=True)]))
        self.assertEquals(['id:2', 'id:1', 'id:0'], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), sortKeys=[dict(sortBy='field1', sortDescending=True), dict(sortBy='field0', sortDescending=True)]))
        self.assertEquals(['id:2', 'id:0', 'id:1'], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), sortKeys=[dict(sortBy='field2', sortDescending=True)]))
        self.assertEquals(['id:1', 'id:0', 'id:2'], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), sortKeys=[dict(sortBy='field2', sortDescending=False)]))
        self.assertEquals(['id:0', 'id:1', 'id:2'], self.hitIds(result.hits))

    def testStartStop(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field1', 'ishallnotbetokenizedA')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([('field1', 'ishallnotbetokenizedB')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([('field1', 'ishallnotbetokenizedC')])))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), start=1, stop=10, sortKeys=[dict(sortBy='field1', sortDescending=False)]))
        self.assertEquals(3, result.total)
        self.assertEquals(['id:1', 'id:2'], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), start=0, stop=2, sortKeys=[dict(sortBy='field1', sortDescending=False)]))
        self.assertEquals(['id:0', 'id:1'], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), start=0, stop=0, sortKeys=[dict(sortBy='field1', sortDescending=False)]))
        self.assertEquals(3, result.total)
        self.assertEquals([], self.hitIds(result.hits))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), start=2, stop=2, sortKeys=[dict(sortBy='field1', sortDescending=False)]))
        self.assertEquals(3, result.total)
        self.assertEquals([], self.hitIds(result.hits))

        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), start=1, stop=2, sortKeys=[dict(sortBy='field1', sortDescending=False)]))
        self.assertEquals(3, result.total)
        self.assertEquals(['id:1'], self.hitIds(result.hits))

    def testFacets(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field1', 'id:0')], facets=[('field2', 'first item0'), ('field3', 'second item')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([('field1', 'id:1')], facets=[('field2', 'first item1'), ('field3', 'other value')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([('field1', 'id:2')], facets=[('field2', 'first item2'), ('field3', 'second item')])))

        # does not crash!!!
        returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='field2')]))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals([], result.drilldownData)
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='field2')]))

        self.assertEquals([{
                'fieldname': 'field2',
                'path': [],
                'terms': [
                    {'term': 'first item0', 'count': 1},
                    {'term': 'first item1', 'count': 1},
                    {'term': 'first item2', 'count': 1},
                ],
            }],result.drilldownData)
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='field3')]))
        self.assertEquals([{
                'fieldname': 'field3',
                'path': [],
                'terms': [
                    {'term': 'second item', 'count': 2},
                    {'term': 'other value', 'count': 1},
                ],
            }],result.drilldownData)

    def testFacetsWithUnsupportedSortBy(self):
        try:
            returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='field2', sortBy='incorrectSort')]))
        except ValueError, e:
            self.assertEquals("""Value of "sortBy" should be in ['count']""", str(e))

    def testFacetsOnUnknownField(self):
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='fieldUnknonw')]))
        self.assertEquals([{'terms': [], 'path': [], 'fieldname': 'fieldUnknonw'}], result.drilldownData)

    def testFacetsMaxTerms0(self):
        self.lucene._index._commitCount = 3
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field1', 'id:0')], facets=[('field2', 'first item0'), ('field3', 'second item')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([('field1', 'id:1')], facets=[('field2', 'first item1'), ('field3', 'other value')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([('field1', 'id:2')], facets=[('field2', 'first item2'), ('field3', 'second item')])))

        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=0, fieldname='field3')]))
        self.assertEquals([{
                'fieldname': 'field3',
                'path': [],
                'terms': [
                    {'term': 'second item', 'count': 2},
                    {'term': 'other value', 'count': 1},
                ],
            }],result.drilldownData)

    def testFacetsWithCategoryPathHierarchy(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field1', 'id:0')], facets=[('fieldHier', ['item0', 'item1'])])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([('field1', 'id:1')], facets=[('fieldHier', ['item0', 'item2'])])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([('field1', 'id:2')], facets=[('fieldHier', ['item3', 'item4'])])))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, path=[], fieldname='fieldHier')]))
        self.assertEquals([{
                'fieldname': 'fieldHier',
                'path': [],
                'terms': [
                    {
                        'term': 'item0',
                        'count': 2,
                        'subterms': [
                            {'term': 'item1', 'count': 1},
                            {'term': 'item2', 'count': 1},
                        ]
                    },
                    {
                        'term': 'item3',
                        'count': 1,
                        'subterms': [
                            {'term': 'item4', 'count': 1},
                        ]
                    }
                ],
            }], result.drilldownData)

        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='fieldHier', path=['item0'])]))
        self.assertEquals([{
                'fieldname': 'fieldHier',
                'path': ['item0'],
                'terms': [
                    {'term': 'item1', 'count': 1},
                    {'term': 'item2', 'count': 1},
                ],
            }], result.drilldownData)

    def XX_testFacetsWithIllegalCharacters(self):
        categories = createCategories([('field', 'a/b')])
        # The following print statement causes an error to be printed to stderr.
        # It keeps on working.
        self.assertEquals('[<CategoryPath: class org.apache.lucene.facet.taxonomy.CategoryPath>]', str(categories))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([]), categories=categories))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='field')]))
        self.assertEquals([{
                'fieldname': 'field',
                'terms': [
                    {'term': 'a/b', 'count': 1},
                ],
            }],result.drilldownData)

    def testEscapeFacets(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field1', 'id:0')], facets=[('field2', 'first/item0')])))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), facets=[dict(maxTerms=10, fieldname='field2')]))
        self.assertEquals([{
                'terms': [{'count': 1, 'term': u'first/item0'}],
                'path': [],
                'fieldname': u'field2'
            }],result.drilldownData)

    def testDiacritics(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier='hendrik', document=createDocument([('title', 'Waar is Morée vandaag?')])))
        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term('title', 'moree'))))
        self.assertEquals(1, result.total)
        query = LuceneQueryComposer(unqualifiedTermFields=[], luceneSettings=LuceneSettings()).compose(parseCql("title=morée"))
        result = returnValueFromGenerator(self.lucene.executeQuery(query))
        self.assertEquals(1, result.total)

    def testFilterQueries(self):
        for i in xrange(10):
            returnValueFromGenerator(self.lucene.addDocument(identifier="id:%s" % i, document=createDocument([
                    ('mod2', 'v%s' % (i % 2)),
                    ('mod3', 'v%s' % (i % 3))
                ])))
        # id     0  1  2  3  4  5  6  7  8  9
        # mod2  v0 v1 v0 v1 v0 v1 v0 v1 v0 v1
        # mod3  v0 v1 v2 v0 v1 v2 v0 v1 v2 v0
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), filterQueries=[TermQuery(Term('mod2', 'v0'))]))
        self.assertEquals(5, result.total)
        self.assertEquals(set(['id:0', 'id:2', 'id:4', 'id:6', 'id:8']), set(self.hitIds(result.hits)))
        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), filterQueries=[
                TermQuery(Term('mod2', 'v0')),
                TermQuery(Term('mod3', 'v0')),
            ]))
        self.assertEquals(2, result.total)
        self.assertEquals(set(['id:0', 'id:6']), set(self.hitIds(result.hits)))

    def testPrefixSearch(self):
        response = returnValueFromGenerator(self.lucene.prefixSearch(fieldname='field1', prefix='valu'))
        self.assertEquals([], response.hits)
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field1', 'value0')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([('field1', 'value1')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([('field1', 'value1')])))
        response = returnValueFromGenerator(self.lucene.prefixSearch(fieldname='field1', prefix='valu'))
        self.assertEquals(['value1', 'value0'], response.hits)
        self.assertTrue(response.queryTime > 0, response.asJson())

    def testSuggestions(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field1', 'value0'), ('field2', 'value2'), ('field3', 'value2')])))
        response = returnValueFromGenerator(self.lucene.executeQuery(luceneQuery=MatchAllDocsQuery(), suggestionRequest=dict(count=2, query="value0 and valeu", field="field3")))
        self.assertEquals(['id:0'], self.hitIds(response.hits))
        self.assertEquals({'value0': (0, 6, ['value2']), 'valeu': (11, 16, ['value2'])}, response.suggestions)

    def testRangeQuery(self):
        for f in ['aap', 'noot', 'mies', 'vis', 'vuur', 'boom']:
            returnValueFromGenerator(self.lucene.addDocument(identifier="id:%s" % f, document=createDocument([('field', f)])))
        # (field, lowerTerm, upperTerm, includeLower, includeUpper)
        luceneQuery = TermRangeQuery.newStringRange('field', None, 'mies', False, False) # <
        response = returnValueFromGenerator(self.lucene.executeQuery(luceneQuery=luceneQuery))
        self.assertEquals(set(['id:aap', 'id:boom']), set(self.hitIds(response.hits)))
        luceneQuery = TermRangeQuery.newStringRange('field', None, 'mies', False, True) # <=
        response = returnValueFromGenerator(self.lucene.executeQuery(luceneQuery=luceneQuery))
        self.assertEquals(set(['id:aap', 'id:boom', 'id:mies']), set(self.hitIds(response.hits)))
        luceneQuery = TermRangeQuery.newStringRange('field', 'mies', None, False, True) # >
        response = returnValueFromGenerator(self.lucene.executeQuery(luceneQuery=luceneQuery))
        self.assertEquals(set(['id:noot', 'id:vis', 'id:vuur']), set(self.hitIds(response.hits)))
        luceneQuery = LuceneQueryComposer([], luceneSettings=LuceneSettings()).compose(parseCql('field >= mies'))
        response = returnValueFromGenerator(self.lucene.executeQuery(luceneQuery=luceneQuery))
        self.assertEquals(set(['id:mies', 'id:noot', 'id:vis', 'id:vuur']), set(self.hitIds(response.hits)))

    def testFieldnames(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field0', 'value0')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([('field1', 'value0')])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([('field1', 'value0')])))
        response = returnValueFromGenerator(self.lucene.fieldnames())
        self.assertEquals(set([IDFIELD, 'field0', 'field1']), set(response.hits))
        self.assertEquals(3, response.total)

    def testDrilldownFieldnames(self):
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:0", document=createDocument([('field0', 'value0')], facets=[("cat", "cat-A"), ("cat", "cat-B")])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:1", document=createDocument([('field1', 'value0')], facets=[("cat", "cat-A"), ("cat2", "cat-B")])))
        returnValueFromGenerator(self.lucene.addDocument(identifier="id:2", document=createDocument([('field1', 'value0')], facets=[("cat2", "cat-A"), ("cat3", "cat-B")])))
        response = returnValueFromGenerator(self.lucene.drilldownFieldnames())
        self.assertEquals(set(['cat', 'cat2', 'cat3']), set(response.hits))
        self.assertEquals(3, response.total)
        response = returnValueFromGenerator(self.lucene.drilldownFieldnames(['cat']))
        self.assertEquals(set(['cat-A', 'cat-B']), set(response.hits))

    def testFilterCaching(self):
        for i in range(10):
            returnValueFromGenerator(self.lucene.addDocument(identifier="id:%s" % i, document=createDocument([('field%s' % i, 'value0')])))
        query = BooleanQuery()
        [query.add(TermQuery(Term("field%s" % i, "value0")), BooleanClause.Occur.SHOULD) for i in range(100)]
        response = returnValueFromGenerator(self.lucene.executeQuery(luceneQuery=MatchAllDocsQuery(), filterQueries=[query]))
        responseWithCaching = returnValueFromGenerator(self.lucene.executeQuery(luceneQuery=MatchAllDocsQuery(), filterQueries=[query]))
        self.assertTrue(responseWithCaching.queryTime < response.queryTime)

    def testHandleShutdown(self):
        document = Document()
        document.add(TextField('title', 'The title', Field.Store.NO))
        returnValueFromGenerator(self.lucene.addDocument(identifier="identifier", document=document))
        with stdout_replaced():
            self.lucene.handleShutdown()
        lucene = Lucene(join(self.tempdir, 'lucene'), reactor=self._reactor, settings=self._defaultSettings)
        response = returnValueFromGenerator(lucene.executeQuery(luceneQuery=MatchAllDocsQuery()))
        self.assertEquals(1, response.total)

    def testResultsFilterCollector(self):
        doc = document(field0='v0')
        doc.add(NumericDocValuesField("__key__", long(42)))
        doc.add(FacetField("cat", ["cat-A"]))
        consume(self.lucene.addDocument("urn:1", doc))
        doc = document(field0='v1')
        doc.add(NumericDocValuesField("__key__", long(42)))
        doc.add(FacetField("cat", ["cat-A"]))
        consume(self.lucene.addDocument("urn:2", doc))
        self.lucene.commit()
        result = retval(self.lucene.executeQuery(MatchAllDocsQuery(),
                        dedupField="__key__", facets=facets(cat=10)))
        self.assertEquals(1, result.total)
        hit = result.hits[0]
        #self.assertEquals('urn:1', hit.id) # this is no longer deterministic since threading
        self.assertEquals({'__key__': 2}, hit.duplicateCount)
        self.assertEquals({'count': 2, 'term': u'cat-A'}, result.drilldownData[0]['terms'][0])

    def testDedupFilterCollectorSortedByField(self):
        doc = document(field0='v0')
        doc.add(NumericDocValuesField("__key__", long(42)))
        doc.add(NumericDocValuesField("__key__.date", long(2012)))
        doc.add(FacetField("cat", ["cat-A"]))
        consume(self.lucene.addDocument("urn:1", doc))

        doc = document(field0='v1')
        doc.add(NumericDocValuesField("__key__", long(42)))
        doc.add(NumericDocValuesField("__key__.date", long(2013))) # first hit of 3 duplicates
        doc.add(FacetField("cat", ["cat-A"]))
        consume(self.lucene.addDocument("urn:2", doc))

        doc = document(field0='v2')
        doc.add(NumericDocValuesField("__key__", long(42)))
        doc.add(FacetField("cat", ["cat-A"]))
        consume(self.lucene.addDocument("urn:3", doc))

        doc = document(field0='v3')
        doc.add(FacetField("cat", ["cat-A"]))
        consume(self.lucene.addDocument("urn:4", doc))

        self.lucene.commit()
        result = retval(self.lucene.executeQuery(MatchAllDocsQuery(),
                        dedupField="__key__", dedupSortField='__key__.date', facets=facets(cat=10)))
        # expected two hits: "urn:2" (3x) and "urn:4" in no particular order
        self.assertEquals(2, result.total)
        self.assertEquals(4, result.totalWithDuplicates)
        expectedHits = set([Hit(score=1.0, id=u'urn:4', duplicateCount={u'__key__': 0}),
                            Hit(score=1.0, id=u'urn:2', duplicateCount={u'__key__': 3})])
        self.assertEquals(expectedHits, set(hit for hit in result.hits))
        self.assertEquals({'count': 4, 'term': u'cat-A'}, result.drilldownData[0]['terms'][0])

    def testDutchStemming(self):
        self.lucene.close()
        settings = LuceneSettings(commitCount=1, analyzer=MerescoDutchStemmingAnalyzer(), verbose=False)
        self.lucene = Lucene(join(self.tempdir, 'lucene'), reactor=self._reactor, settings=settings)
        doc = document(field0='katten en honden')
        consume(self.lucene.addDocument("urn:1", doc))
        self.lucene.commit()

        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("field0", 'katten'))))
        self.assertEquals(0, result.total)

        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("field0", 'kat'))))
        self.assertEquals(1, result.total)

    def testDrilldownQuery(self):
        doc = createDocument(fields=[("field0", 'v1')], facets=[("cat", "cat-A")])
        consume(self.lucene.addDocument("urn:1", doc))
        doc = createDocument(fields=[("field0", 'v2')], facets=[("cat", "cat-B")])
        consume(self.lucene.addDocument("urn:2", doc))

        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(2, result.total)

        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), drilldownQueries=[("cat", ["cat-A"])]))
        self.assertEquals(1, result.total)

        result = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("field0", "v2")), drilldownQueries=[("cat", ["cat-A"])]))
        self.assertEquals(0, result.total)

    def testMultipleDrilldownQueryOnSameField(self):
        doc = createDocument(fields=[("field0", 'v1')], facets=[("cat", "cat-A"), ("cat", "cat-B")])
        consume(self.lucene.addDocument("urn:1", doc))
        doc = createDocument(fields=[("field0", 'v1')], facets=[("cat", "cat-B",)])
        consume(self.lucene.addDocument("urn:2", doc))
        doc = createDocument(fields=[("field0", 'v1')], facets=[("cat", "cat-C",)])
        consume(self.lucene.addDocument("urn:3", doc))

        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery()))
        self.assertEquals(3, result.total)

        result = returnValueFromGenerator(self.lucene.executeQuery(MatchAllDocsQuery(), drilldownQueries=[("cat", ["cat-A"]), ("cat", ["cat-B"])]))
        self.assertEquals(1, result.total)

    def testNoTermFrequency(self):
        factory = FieldRegistry()
        factory.register("no.term.frequency", NO_TERMS_FREQUENCY_FIELDTYPE)
        factory.register("no.term.frequency2", NO_TERMS_FREQUENCY_FIELDTYPE)
        doc = Document()
        doc.add(factory.createField("no.term.frequency", "aap noot noot noot vuur"))
        consume(self.lucene.addDocument("no.term.frequency", doc))

        doc = createDocument(fields=[('term.frequency', "aap noot noot noot vuur")])
        consume(self.lucene.addDocument("term.frequency", doc))

        doc = Document()
        doc.add(factory.createField("no.term.frequency2", "aap noot"))
        doc.add(factory.createField("no.term.frequency2", "noot noot"))
        doc.add(factory.createField("no.term.frequency2", "vuur"))
        consume(self.lucene.addDocument("no.term.frequency2", doc))

        result1 = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("no.term.frequency", "aap"))))
        result2 = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("no.term.frequency", "noot"))))
        self.assertEquals(result1.hits[0].score, result2.hits[0].score)

        result1 = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("term.frequency", "aap"))))
        result2 = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("term.frequency", "noot"))))
        self.assertNotEquals(result1.hits[0].score, result2.hits[0].score)
        self.assertTrue(result1.hits[0].score < result2.hits[0].score)

        result1 = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("no.term.frequency2", "aap"))))
        result2 = returnValueFromGenerator(self.lucene.executeQuery(TermQuery(Term("no.term.frequency2", "noot"))))
        self.assertEquals(result1.hits[0].score, result2.hits[0].score)

        bq = BooleanQuery()
        bq.add(TermQuery(Term('no.term.frequency', 'aap')),BooleanClause.Occur.MUST)
        bq.add(TermQuery(Term('no.term.frequency', 'noot')),BooleanClause.Occur.MUST)
        self.assertEquals(1, len(returnValueFromGenerator(self.lucene.executeQuery(bq)).hits))

    def testUpdateReaderSettings(self):
        settings = self.lucene.readerSettingsWrapper.get()
        self.assertEquals({'numberOfConcurrentTasks': 6, 'similarity': u'BM25(k1=1.2,b=0.75)'}, settings)

        self.lucene.readerSettingsWrapper.set(similarity=dict(k1=1.0, b=2.0), numberOfConcurrentTasks=10)
        settings = self.lucene.readerSettingsWrapper.get()
        self.assertEquals({'numberOfConcurrentTasks': 10, 'similarity': u'BM25(k1=1.0,b=2.0)'}, settings)

        self.lucene.readerSettingsWrapper.set()
        settings = self.lucene.readerSettingsWrapper.get()
        self.assertEquals({'numberOfConcurrentTasks': 6, 'similarity': u'BM25(k1=1.2,b=0.75)'}, settings)

class LuceneSingleThreadedTest(LuceneTest):
    def __init__(self, *args):
        super(LuceneTest, self).__init__(*args)
        self._multithreaded = False

def facets(**fields):
    return [dict(fieldname=name, maxTerms=max_) for name, max_ in fields.items()]

def document(**fields):
    return createDocument(fields.items())

DEFAULT_FACTORY = FieldRegistry()

def createDocument(fields, facets=None):
    document = Document()
    for name, value in fields:
        document.add(DEFAULT_FACTORY.createField(name, value))
    for facet, value in facets or []:
        if hasattr(value, 'extend'):
            path = [str(category) for category in value]
        else:
            path = [str(value)]
        document.add(FacetField(facet, path))
    return document
