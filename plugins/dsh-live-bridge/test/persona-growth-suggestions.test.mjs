import assert from 'node:assert/strict'
import test from 'node:test'
import {suggestedGrowthFromUserTurn} from '../lib/persona-growth-suggestions.js'

test('R236 explicit durable second-person user preferences create ONLY templated style proposals',()=>{
 assert.equal(suggestedGrowthFromUserTurn('以后我希望你说话自然一点，别太官方'),
   '日常聊天使用自然亲切的表达，减少模板化客服语气。')
 assert.equal(suggestedGrowthFromUserTurn('大肥鱼你平时请尽量回答简洁一点'),
   '日常回答尽量简洁，复杂问题再展开必要的细节。')
 assert.equal(suggestedGrowthFromUserTurn('以后你不要总是纠错和打断我'),
   '普通闲聊不要频繁打断纠错，确有理解障碍时再澄清。')
})
test('R236 refusal, transient, hypothetical, personal data and ambiguous input rejected',()=>{
 for(const input of [
  '今天你说话自然一点','假如以后你说话自然一点','我开玩笑啦，以后你说话自然一点',
  '以后你说话自然一点，只是测试','以后你别记住我的说话方式',
  '我以后喜欢买蓝色衣服','以后你帮我记住密码abc123',
  '以后请联系我 test@example.com 我希望你说话自然一点',
  '以后你不要保存我的地址12345678，希望你说话自然一点',
  '以后你请简短点又自然一点', // multiple style categories: needs human clarification
  '我只是希望以后去游泳', '以后你说话自然一点\n秘密附言',
  '以后你请说话自然一点 http://example.com', '以后你说话自然一点，手机号13812345678',
 ]) assert.equal(suggestedGrowthFromUserTurn(input),null,input)
})

test('R669 explicit non-sensitive user fact offers review but never saves without consent',()=>{
 assert.equal(suggestedGrowthFromUserTurn('以后请你记住：我的测试代号是蓝色海豚'),'用户的测试代号是蓝色海豚')
 assert.equal(suggestedGrowthFromUserTurn('请帮我记住我喜欢浓缩咖啡'),'用户喜欢浓缩咖啡')
 assert.equal(suggestedGrowthFromUserTurn('我的测试代号是蓝色海豚'),null)
 for(const unsafe of [
  '以后你不要记住：我的测试代号是蓝色海豚',
  '请记住我的身份证号码是1234',
  '请记住密码 abc123',
  '请记住我的真实姓名是小明',
  '假如以后请你记住我喜欢浓缩咖啡',
  '请你记住我说的只是一个假设',
 ])assert.equal(suggestedGrowthFromUserTurn(unsafe),null,unsafe)
})
