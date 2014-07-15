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

from meresco.core import Observable
from org.apache.lucene.document import Document
from org.apache.lucene.facet.taxonomy import FacetLabel

from time import time

from utils import createField, createTimestampField, IDFIELD, KEY_PREFIX


class Fields2LuceneDoc(Observable):
    def __init__(self, transactionName, drilldownFieldnames, addTimestamp=False, identifierRewrite=None, rewriteFields=None):
        Observable.__init__(self)
        self._transactionName = transactionName
        self._drilldownFieldnames = drilldownFieldnames
        self._addTimestamp = addTimestamp
        self._identifierRewrite = (lambda identifier: identifier) if identifierRewrite is None else identifierRewrite
        self._rewriteFields = (lambda fields: fields) if rewriteFields is None else rewriteFields

    def begin(self, name):
        if name != self._transactionName:
            return
        tx = self.ctx.tx
        tx.join(self)

    def addField(self, name, value):
        tx = self.ctx.tx
        valueList = tx.objectScope(self).setdefault(name, [])
        valueList.append(value)

    def commit(self, id):
        tx = self.ctx.tx
        fields = tx.objectScope(self)
        if not fields:
            return
        identifier = self._identifierRewrite(tx.locals['id'])
        fields = self._rewriteFields(fields)
        yield self.all.addDocument(
                identifier=identifier,
                document=self._createDocument(fields),
                categories=self._createFacetCategories(fields)
            )

    def _createDocument(self, fields):
        doc = Document()
        for field, values in fields.items():
            for value in values:
                if field.startswith(KEY_PREFIX):
                    value = self.call.numerateTerm(value)
                if field == IDFIELD:
                    raise ValueError("Field '%s' is protected and created by Lucene(..)")
                else:
                    if hasattr(value, 'extend'):
                        for v in ['/'.join(value[:i]) for i in xrange(1,len(value)+1)]:
                            doc.add(createField(field, v))
                    else:
                        doc.add(createField(field, value))
        if self._addTimestamp:
            doc.add(createTimestampField(self._time()))
        return doc

    def _time(self):
        return int(time()*1000000)

    def _createFacetCategories(self, fields):
        categoryPaths = []
        for f, vs in fields.items():
            if not f in self._drilldownFieldnames:
                continue
            for v in vs:
                path = [f]
                if hasattr(v, 'extend'):
                    path.extend(str(category) for category in v)
                else:
                    path.append(str(v))
                categoryPaths.append(FacetLabel(path))
        return categoryPaths
