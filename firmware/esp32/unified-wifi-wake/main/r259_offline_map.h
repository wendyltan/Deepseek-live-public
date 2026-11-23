/* Auto-generated from firmware/esp32/offline_command_map.json. */
#pragma once
#include <stddef.h>
typedef struct {int command_id,clip_id;const char *ask,*pinyin,*reply;} r259_command_t;
static const r259_command_t R259_COMMANDS[] = {
 {1,1,"你在吗","ni zai ma","你好呀，我在这儿。"},
 {2,2,"你离线了吗","ni li xian le ma","我现在离线啦，不过简单的小互动还能陪你玩。"},
 {3,3,"你在吃什么","ni zai chi shen me","我在吃白饭呢，等我吃完这一口。"},
 {4,4,"你怎么样","ni zen me yang","我的状态不错，随时可以叫我。"},
 {5,5,"我想睡觉了","wo xiang shui jiao le","晚安，做个好梦，明天见。"},
 {6,8,"和我说再见","he wo shuo zai jian","下次见！"},
 {7,9,"你今天开心吗","ni jin tian kai xin ma","今天心情不错，想和你聊聊天。"},
};
#define R259_COMMAND_COUNT (sizeof(R259_COMMANDS)/sizeof(R259_COMMANDS[0]))
