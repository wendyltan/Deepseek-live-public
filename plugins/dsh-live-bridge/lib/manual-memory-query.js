/** Opt-in E1b lookup over already user-approved facts. Never auto-save. */
export function normalizeManualQuery(query) {
  if(typeof query!=='string'||!query.trim()||query.length>200)throw new Error('manual_query_invalid')
  const text=query.toLocaleLowerCase().normalize('NFKC').trim()
  // 2-character CJK n-grams; do not expose query, log or persist it.
  const terms=new Set(text.match(/[\p{Script=Han}]{2,}|[a-z0-9]{3,}/gu)?.flatMap(part=>{
    if(/[\p{Script=Han}]/u.test(part))return Array.from({length:part.length-1},(_,i)=>part.slice(i,i+2))
    return [part]
  })??[])
  if(terms.size===0)throw new Error('manual_query_too_short')
  return terms
}
export function queryUserApprovedMemory(vault,query,{limit=3}={}) {
  if(!Number.isInteger(limit)||limit<1||limit>5)throw new Error('manual_query_limit')
  const terms=normalizeManualQuery(query)
  const records=vault.list()
  // The current source of truth is only the E1b vault. Never query external
  // ReMe or DSH sessions, even when the directory happens to be empty.
  const matches=[]
  for(const entry of records.items){
    if(entry.source!=='user_explicit')continue
    const item=vault.read(entry.id) // verifies SHA256 and revision
    const words=normalizeFact(item.text)
    const score=[...terms].reduce((n,w)=>n+(words.includes(w)?1:0),0)
    if(score>0)matches.push({id:item.id,revision:item.revision,source:entry.source,
                             text:item.text.trim().slice(0,1024),score})
  }
  matches.sort((a,b)=>b.score-a.score || a.id.localeCompare(b.id))
  return {schema:1,origin:'explicit_e1b_user_facts_only',auto_extraction:false,
          items:matches.slice(0,limit).map(({score,...item})=>item)}
}
function normalizeFact(text){return text.toLocaleLowerCase().normalize('NFKC')}
