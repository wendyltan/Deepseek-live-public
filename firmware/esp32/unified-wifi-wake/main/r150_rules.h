#pragma once
#include <stdbool.h>
#include <stddef.h>
void r150_rules_init(void);
bool r150_rules_arm_tap(void);
unsigned r150_rules_pick(unsigned group,unsigned round,unsigned fallback);
void r150_rules_command(const char *cmd,bool busy,bool (*send)(const char*,size_t));
bool r150_rules_v2_active(void);
