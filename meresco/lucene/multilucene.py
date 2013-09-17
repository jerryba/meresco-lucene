## begin license ##
#
# "Meresco Lucene" is a set of components and tools to integrate Lucene (based on PyLucene) into Meresco
#
# Copyright (C) 2013 Seecr (Seek You Too B.V.) http://seecr.nl
# Copyright (C) 2013 Stichting Bibliotheek.nl (BNL) http://www.bibliotheek.nl
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

from meresco.core import Observable
from org.apache.lucene.search import MatchAllDocsQuery
from weightless.core import DeclineMessage
from _lucene import millis
from time import time
from org.meresco.lucene import KeyCollector, KeyFilterCollector
from cache import KeyCollectorCache
from seecr.utils.generatorutils import consume, generatorReturn

class MultiLucene(Observable):
    def __init__(self, defaultCore):
        Observable.__init__(self)
        self._defaultCore = defaultCore
        self._collectorCache = KeyCollectorCache(createCollectorFunction=lambda core: KeyCollector(core))

    def executeQuery(self, core=None, **kwargs):
        coreName = self._defaultCore if core is None else core
        response = yield self.any[coreName].executeQuery(**kwargs)
        generatorReturn(response)

    def executeMultiQuery(self, multiQuery):
        multiQuery.validate()
        t0 = time()

        primaryCoreName, foreignCoreName = multiQuery.cores()
        primaryKeyName, foreignKeyName = multiQuery.keyNames(primaryCoreName, foreignCoreName)
        foreignQuery = multiQuery.queryFor(core=foreignCoreName)
        primaryQuery = multiQuery.queryFor(core=primaryCoreName)
        if primaryQuery is None:
            primaryQuery = MatchAllDocsQuery()

        if foreignQuery:
            foreignKeyCollector = KeyCollector(foreignKeyName)
            consume(self.any[foreignCoreName].search(query=foreignQuery, collector=foreignKeyCollector))
            keySet = foreignKeyCollector.getKeySet()
            # if foreignFacets: # Optimization?????
            primaryKeyCollector = KeyCollector(primaryKeyName)
            consume(self.any[primaryCoreName].search(query=primaryQuery, collector=primaryKeyCollector))
            keySet.intersect(primaryKeyCollector.getKeySet())

            primaryKeyFilterCollector = KeyFilterCollector(keySet, primaryKeyName)
            primaryResponse = yield self.any[primaryCoreName].executeQuery(luceneQuery=primaryQuery, filterCollector=primaryKeyFilterCollector, facets=multiQuery.facetsFor(primaryCoreName))
        else:
            primaryKeyCollector = KeyCollector(primaryKeyName)
            primaryResponse = yield self.any[primaryCoreName].executeQuery(luceneQuery=primaryQuery, extraCollector=primaryKeyCollector, facets=multiQuery.facetsFor(primaryCoreName))
            keySet = primaryKeyCollector.getKeySet()
            foreignQuery = MatchAllDocsQuery()

        if multiQuery.facetsFor(foreignCoreName):
            foreignKeyFilterCollector = KeyFilterCollector(keySet, foreignKeyName)
            foreignReponse = yield self.any[foreignCoreName].executeQuery(foreignQuery, filterCollector=foreignKeyFilterCollector, facets=multiQuery.facetsFor(foreignCoreName))
            primaryResponse.drilldownData.extend(foreignReponse.drilldownData)

        primaryResponse.queryTime = millis(time() - t0)
        generatorReturn(primaryResponse)

    def any_unknown(self, message, core=None, **kwargs):
        if message in ['prefixSearch', 'fieldnames']:
            core = self._defaultCore if core is None else core
            result = yield self.any[core].unknown(message=message, **kwargs)
            raise StopIteration(result)
        raise DeclineMessage()

    def coreInfo(self):
        yield self.all.coreInfo()


