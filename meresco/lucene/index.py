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

from org.apache.lucene.index import IndexWriter, DirectoryReader, IndexWriterConfig
from org.apache.lucene.search import IndexSearcher
from org.apache.lucene.store import SimpleFSDirectory
from org.apache.lucene.analysis.standard import StandardAnalyzer
from org.apache.lucene.util import Version
from org.apache.lucene.facet.taxonomy.directory import DirectoryTaxonomyWriter, DirectoryTaxonomyReader
from org.apache.lucene.facet.index import FacetFields
from org.apache.lucene.facet.search import FacetsCollector

from java.io import File
from java.util import Arrays

from os.path import join

class Index(object):

    def __init__(self, path):
        indexDirectory = SimpleFSDirectory(File(join(path, 'index')))
        analyzer = StandardAnalyzer(Version.LUCENE_43)
        conf = IndexWriterConfig(Version.LUCENE_43, analyzer);
        self._indexWriter = IndexWriter(indexDirectory, conf)
        self._searcher = IndexSearcher(DirectoryReader.open(self._indexWriter, True))

        self._taxoDirectory = SimpleFSDirectory(File(join(path, 'taxo')))
        self._taxoWriter = DirectoryTaxonomyWriter(self._taxoDirectory)
        self._taxoWriter.commit()
        self._taxoReader = None
        self._openTaxonomyReader()

    def addDocument(self, document, categories=None):
        if categories:
            FacetFields(self._taxoWriter).addFields(document, Arrays.asList(categories))
        self._indexWriter.addDocument(document)
        self.commit()

    def search(self, *args):
        searcher = self._searcher
        indexReader = searcher.getIndexReader()
        if indexReader.tryIncRef():
            taxoReader = self._taxoReader
            if taxoReader.tryIncRef():
                try:
                    searcher.search(*args)
                finally:
                    taxoReader.decRef()
                    indexReader.decRef()
            else:
                indexReader.decRef()

    def commit(self):
        reader = DirectoryReader.open(self._indexWriter, True)
        currentReader = self._searcher.getIndexReader()
        if reader != currentReader:
            self._searcher = IndexSearcher(reader)
            currentReader.decRef()
        self._hardCommit()

    def _hardCommit(self):
        self._indexWriter.commit()
        self._commitFacet()

    def _commitFacet(self):
        self._taxoWriter.commit()
        self._openTaxonomyReader()

    def getDocument(self, docId):
        return self._searcher.doc(docId)

    def _openTaxonomyReader(self):
        taxonomyReader = DirectoryTaxonomyReader(self._taxoDirectory)
        if taxonomyReader != self._taxoReader:
            if self._taxoReader:
                self._taxoReader.decRef()
            self._taxoReader = taxonomyReader

    def createFacetCollector(self, facetSearchParams):
        if not self._taxoReader:
            return
        return FacetsCollector.create(facetSearchParams, self._searcher.getIndexReader(), self._taxoReader)
