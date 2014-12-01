/* begin license *
 *
 * "Meresco Lucene" is a set of components and tools to integrate Lucene (based on PyLucene) into Meresco
 *
 * Copyright (C) 2013-2014 Seecr (Seek You Too B.V.) http://seecr.nl
 * Copyright (C) 2013-2014 Stichting Bibliotheek.nl (BNL) http://www.bibliotheek.nl
 *
 * This file is part of "Meresco Lucene"
 *
 * "Meresco Lucene" is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * "Meresco Lucene" is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with "Meresco Lucene"; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 *
 * end license */

package org.meresco.lucene.queries;

import java.io.IOException;
import java.util.Collections;
import java.util.Map;
import java.util.WeakHashMap;

import org.apache.lucene.index.AtomicReaderContext;
import org.apache.lucene.index.NumericDocValues;
import org.apache.lucene.search.DocIdSet;
import org.apache.lucene.search.DocIdSetIterator;
import org.apache.lucene.search.Filter;
import org.apache.lucene.util.Bits;


public class KeyFilter extends Filter {
	private String keyName;
	public Bits keySet;
	private static Map<SegmentFieldKey, int[]> keyValuesCache = Collections
			.synchronizedMap(new WeakHashMap<SegmentFieldKey, int[]>());

	public KeyFilter(DocIdSet keySet, String keyName) throws IOException {
		this.keySet = keySet.bits();
		this.keyName = keyName;
	}

	@Override
	public DocIdSet getDocIdSet(final AtomicReaderContext context,
			Bits acceptDocs) throws IOException {
		return new DocIdSet() {
			@Override
			public DocIdSetIterator iterator() throws IOException {
				return new DocIdSetIterator() {
					private NumericDocValues keyValues = context.reader()
							.getNumericDocValues(keyName);
					private int[] keyValuesArray = keyValuesCache.get(new SegmentFieldKey(context.reader().getCoreCacheKey(), keyName));
					private int maxDoc = context.reader().maxDoc();
					int docId = keyValues == null ? DocIdSetIterator.NO_MORE_DOCS
							: 0;

					{
						if (keyValuesArray == null) {
							keyValuesArray = new int[maxDoc];
							keyValuesCache.put(new SegmentFieldKey(context.reader().getCoreCacheKey(), keyName), keyValuesArray);
						}
					}
					
					@Override
					public int docID() {
						throw new UnsupportedOperationException();
					}

					@Override
					public int nextDoc() throws IOException {
						try {
							while (this.docId < this.maxDoc) {
								int key = this.keyValuesArray[this.docId];
								if (key == 0) {
									key = this.keyValuesArray[this.docId] = (int) keyValues.get(this.docId);
								}
								if (keySet.get(key)) {
									return this.docId++;
								}
								docId++;
							}
						} catch (IndexOutOfBoundsException e) {
						}
						this.docId = DocIdSetIterator.NO_MORE_DOCS;
						return this.docId;
					}

					@Override
					public int advance(int target) throws IOException {
						this.docId = target;
						return nextDoc();
					}

					@Override
					public long cost() {
						throw new UnsupportedOperationException();
					}
				};
			}
		};
	}
}