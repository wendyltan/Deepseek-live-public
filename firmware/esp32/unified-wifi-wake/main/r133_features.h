// R133 isolated experimental capabilities; R121 legacy remains intact.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
// kind 1=tap,2=idle,3=bonus,4=work,5=finger_drag,0=manual.
void r133_rules_init(void);
unsigned r133_rules_pick(unsigned kind,unsigned round,unsigned fallback);
void r133_rules_command(const char *cmd,bool busy,bool (*send)(const char*,size_t));
bool r133_rules_arm_tap(void);
void r133_screen_command(const char *cmd,bool audio_busy,bool (*send)(const char*,size_t));
void r133_screen_abort_requested(void);
void r133_screen_tick(bool audio_busy);
