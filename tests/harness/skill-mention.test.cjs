const test=require('node:test');
const assert=require('node:assert/strict');
const {loadModule}=require('./helpers.cjs');
const {skillMention,insertSkillMention}=loadModule('skill-mention');

test('slash detects a skill at caret, including after Persian text',()=>{
 assert.deepEqual(skillMention('/',1),{query:'',start:0,end:1});
 assert.deepEqual(skillMention('کمک /review',11),{query:'review',start:4,end:11});
 for(const text of ['src/main','https://example','C:/work','/name/child','/سلام'])assert.equal(skillMention(text,text.length),null);
 assert.equal(skillMention('/review',3),null);
});
test('insertion replaces only the mention and preserves the surrounding request',()=>{
 const text='کمک /rev ادامه';const mention=skillMention(text,8);
 assert.deepEqual(insertSkillMention(text,mention,'review-code'),{text:'کمک /review-code  ادامه',caret:17});
});
