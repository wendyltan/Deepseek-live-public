#pragma once
#include <stdbool.h>
#include <stddef.h>
bool r225_voice_upload_active(void);
void r225_voice_upload_handle(const char *command,bool(*send_line)(const char*,size_t));
