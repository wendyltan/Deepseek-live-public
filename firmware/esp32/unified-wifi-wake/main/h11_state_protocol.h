// H11 additive *display-state only* prototype. H10 firmware behavior unchanged
// until compiling with DF_H11_PREVIEW_STATES=1. No SD motion is claimed.
#ifndef DF_H11_STATE_PROTOCOL_H
#define DF_H11_STATE_PROTOCOL_H
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>

typedef struct { uint32_t last_seq; char phase[24]; } df_h11_state;
static const char* df_h11_allowed_phases[]={
 "idle","listening","transcribing","thinking","tool_pending",
 "approval_pending","voice_generating","speaking","error"
};
static int df_h11_parse_state(const char *line,df_h11_state *state,
                             uint32_t *seq_out,const char **phase_out){
    if (!line||!state||!seq_out||!phase_out) return -1;
    const char *pfx="@@DFSTATE1 SET seq=";
    size_t prefix_len=strlen(pfx);
    if(strncmp(line,pfx,prefix_len)!=0)return -1;
    const char *digits=line+prefix_len;
    if(*digits<'0'||*digits>'9')return -1;
    char *end=NULL;
    unsigned long long val=strtoull(digits,&end,10);
    if(!end||strncmp(end," phase=",7)!=0||val==0||val>999999999ULL||
       val<=state->last_seq)return -1;
    const char *phase=end+7;
    for(unsigned i=0;i<sizeof(df_h11_allowed_phases)/sizeof(df_h11_allowed_phases[0]);i++){
        if(strcmp(phase,df_h11_allowed_phases[i])==0){
            *seq_out=(uint32_t)val;*phase_out=df_h11_allowed_phases[i];return 0;
        }
    }
    return -1;
}
static void df_h11_commit_state(df_h11_state *state,uint32_t seq,const char*phase){
    state->last_seq=seq;
    snprintf(state->phase,sizeof(state->phase),"%s",phase);
}
#endif
