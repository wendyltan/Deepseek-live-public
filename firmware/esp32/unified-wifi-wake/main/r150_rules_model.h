// R150 migration-safe 106-motion rule map; pure C, host-testable.
// No extra allocations, unchanged hardware legacy v1 map1 NVS schema.
#pragma once
#include <stdint.h>
#include <string.h>
#define R150_TOTAL 106u
#define R150_OLD_COUNT 35u
static const uint16_t r150_factory35_ids[R150_OLD_COUNT]={
    0,1,2,3,8,10,11,13,14,15,16,18,19,20,23,24,25,26,27,28,
    30,61,62,67,70,71,72,73,75,80,81,83,97,99,105
};
typedef struct {uint32_t magic;uint16_t version,n;
    uint8_t group[R150_OLD_COUNT];uint32_t crc;} r150_legacy_blob;
typedef struct {uint32_t magic;uint16_t version,n;
    uint8_t group[R150_TOTAL];uint32_t crc;} r150_map_blob;
static inline int r150_wellformed(const uint8_t *groups,unsigned n){
    if(!groups||n!=R150_TOTAL||groups[0]!=6)return 0;
    for(unsigned i=1;i<n;i++)if(groups[i]>5)return 0;
    return 1;
}
static inline void r150_from_legacy(uint8_t target[R150_TOTAL],
                                  const uint8_t legacy[R150_OLD_COUNT]){
    memset(target,0,R150_TOTAL);
    for(unsigned i=0;i<R150_OLD_COUNT;i++)
        target[r150_factory35_ids[i]]=legacy[i];
    target[0]=6;
}
static inline int r150_choose(const uint8_t map[R150_TOTAL],
            unsigned group,unsigned round,unsigned fallback){
    if(group<1||group>5)return (int)fallback;
    unsigned count=0;
    for(unsigned i=0;i<R150_TOTAL;i++)count+=(map[i]==group);
    if(!count)return (int)fallback;
    unsigned choice=round%count;
    for(unsigned i=0;i<R150_TOTAL;i++)
        if(map[i]==group && choice--==0)return (int)i;
    return (int)fallback;
}
