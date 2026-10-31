'use strict';
const {test} = require('node:test');
const assert=require('node:assert/strict');
const {parseAvailable,localEndpoint,validProject}=require('./sse.js');
test('splits SSE events across network chunks',()=>{
 let rest='',events=[];
 for(const fragment of ['event: delta\r','\ndata: {"text":"hi"}\r\n','\r\n','event: done\n','data: {"saved":true}\n\n']){
  const result=parseAvailable(rest+fragment);rest=result.rest;events.push(...result.events);
 }
 assert.deepEqual(events,[{kind:'delta',payload:{text:'hi'}},{kind:'done',payload:{saved:true}}]);
 assert.equal(rest,'');
});
test('never interprets model content as separate event',()=>{
 const parsed=parseAvailable('event: delta\ndata: {"text":"hi\\n\\nevent: done"}\n\n');
 assert.equal(parsed.events.length,1);
 assert.equal(parsed.events[0].payload.text,'hi\n\nevent: done');
});
test('validates local-only endpoint and project name',()=>{
 for(const url of ['http://127.0.0.1:8000','http://localhost:8000']){
  assert.equal(localEndpoint(url),url);
 }
 for(const url of ['https://127.0.0.1:8000','http://evil.example.com','http://127.0.0.1.evil.com:8000','http://user:pw@127.0.0.1:8000','http://127.0.0.1:8000/remote']){
  assert.throws(()=>localEndpoint(url));
 }
 assert.equal(validProject('repo_1-test'),true);
 assert.equal(validProject('../outside'),false);
 assert.equal(validProject(''),false);
});
test('refuses malformed and excessive SSE frames',()=>{
 assert.throws(()=>parseAvailable('event: delta\ndata: {}\n\n'+'x'.repeat(512001)));
 assert.throws(()=>parseAvailable('event: delta\ndata: not-json\n\n'));
});
