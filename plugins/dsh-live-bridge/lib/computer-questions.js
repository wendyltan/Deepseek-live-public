/** Validate one exact, native DSH computer-use human question.
 * No inferred intent, arbitrary tool routes, automatic allow or content logs.
 */
export function boundedComputerQuestion(request) {
  if(!request || !Array.isArray(request.questions) ||
     request.questions.length!==1)return null
  const q=request.questions[0]
  if(!q || typeof q.id!=='string' || !/^[\w.-]{1,128}$/.test(q.id) ||
     typeof q.question!=='string' || !q.question.trim() ||
     q.question.length>350 ||
     (q.detail!==undefined && (typeof q.detail!=='string'||q.detail.length>1600)) ||
     (q.header!==undefined && (typeof q.header!=='string'||q.header.length>100)) ||
     q.multiSelect===true || !Array.isArray(q.options) ||
     q.options.length<2 || q.options.length>5)return null
  const choices=q.options.map(o=>o?.label)
  if(!choices.every(s=>typeof s==='string' && s.length>=1 && s.length<=96)
     || new Set(choices).size!==choices.length)return null
  return {
    question_id:q.id,question:q.question,detail:q.detail??'',
    header:q.header??'Mac 电脑操作授权',
    options:choices,
  }
}
