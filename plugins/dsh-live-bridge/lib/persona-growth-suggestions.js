/**
 * R236 safe, LOCAL suggestion shortlist. Deterministic and non-generative.
 * Only offers pre-authored style suggestions; never saves raw conversation,
 * secrets, user facts, tools, model output, or conversation history.
 * Requires a direct, persistent, second-person style request in the user turn.
 * No implicit personality inference, and no additional model request.
 */
const PERSIST=/(以后|今后|平时|长期|一直|每次|往后)/
const DIRECT=/(你|大肥鱼|回答|回复|聊天|说话|语气|口吻|表达)/
const INTENT=/(请|希望|最好|能不能|可以|尽量|别|不要|想让|我更喜欢)/
const EXCLUDE=/(开玩笑|打个比方|假如|假设|举个例子|角色扮演|剧情|故事|临时|暂时|这次|本轮|今天|测试|模拟|不要记|别记住|不需要记)/
const PRIVATE=/(https?:\/\/|www\.|@|password|密码|口令|token|密钥|银行卡|手机号|身份证|住址|地址|病历|诊断|\d{5,})/i

const RULES=Object.freeze([
 {match:/(像朋友|别太官方|不要太官方|客服|自然一点|自然些|亲切)/,
  text:'日常聊天使用自然亲切的表达，减少模板化客服语气。'},
 {match:/(简短|精简|简洁|少啰嗦|不要啰嗦|别太长)/,
  text:'日常回答尽量简洁，复杂问题再展开必要的细节。'},
 {match:/(幽默|有趣|开朗|轻松|活泼)/,
  text:'非严肃话题可以适度轻松幽默，不影响事实准确性。'},
 {match:/(不要.{0,4}纠错|别纠正|少纠错|不必纠正|别打断|不要.{0,4}打断)/,
  text:'普通闲聊不要频繁打断纠错，确有理解障碍时再澄清。'},
 {match:/(技术问题|代码|开发|项目|编程).*(认真|详细|严谨|准确)/,
  text:'技术和项目讨论优先严谨、可验证且必要时详细说明。'},
])
// R669: explicit, user-directed, non-sensitive factual memory may create a
// reviewed *candidate*. No raw transcript saved; no silent memory acceptance.
const REMEMBER=/(?:请|麻烦|以后|今后|长期|帮我).{0,10}?(?:记住|记下来|记得)[：:,，\s]*(.+)$/u
const DO_NOT_REMEMBER=/(?:别|不要|不需要|禁止|千万别).{0,10}(?:记住|记下来|保存|记录)/u
const DANGEROUS_FACT=/(身份证|银行卡|账户|账号|密码|密钥|口令|手机号|真实姓名|住址|家庭地址|病历|诊断|信用卡|银行卡|电子邮箱|支付信息)/u
function explicitFact(prompt) {
 if(DO_NOT_REMEMBER.test(prompt)||DANGEROUS_FACT.test(prompt)||
    PRIVATE.test(prompt)||/(假如|假设|角色扮演|剧情|故事|开玩笑|举个例子)/.test(prompt))return null
 const m=prompt.match(REMEMBER)
 if(!m)return null
 let fact=m[1].trim().replace(/[。！!?！？]+$/u,'')
 if(fact.length<4||fact.length>110||
    /(?:不要记|不必记|别保存|不是真的)/.test(fact))return null
 // Self-reference in the user's voice must not become a fact about Dafeiyu.
 if(/^我的/.test(fact))fact='用户的'+fact.slice(2)
 else if(/^我/.test(fact))fact='用户'+fact.slice(1)
 return fact
}
export function suggestedGrowthFromUserTurn(prompt) {
 if(typeof prompt!=='string'||prompt.length<5||prompt.length>220||
    /[\r\n]/.test(prompt))return null
 const explicit=explicitFact(prompt)
 if(explicit)return explicit
 if(EXCLUDE.test(prompt)||PRIVATE.test(prompt)||
    !PERSIST.test(prompt)||!DIRECT.test(prompt)||!INTENT.test(prompt))return null
 const choices=RULES.filter(x=>x.match.test(prompt))
 if(choices.length!==1)return null // ambiguous or contradictory signals: no inference
 return choices[0].text
}
