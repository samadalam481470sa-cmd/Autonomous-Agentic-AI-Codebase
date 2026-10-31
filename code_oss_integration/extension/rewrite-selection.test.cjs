'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {digest,unchanged}=require('./rewrite-selection.js');
test('SHA-256 original selection is stable',()=>{
  assert.match(digest('hello'),/^[0-9a-f]{64}$/);
  assert.notEqual(digest('hello'),digest('Hello'));
});
test('file versions and selections must match',()=>{
  const sel={start:0,end:2};
  const doc={isClosed:false,version:4,getText:()=> 'hi'};
  assert.equal(unchanged(doc,sel,4,'hi'),true);
  assert.equal(unchanged(doc,sel,3,'hi'),false);
  assert.equal(unchanged(doc,sel,4,'bye'),false);
  doc.isClosed=true;
  assert.equal(unchanged(doc,sel,4,'hi'),false);
});
