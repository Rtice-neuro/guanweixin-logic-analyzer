#ifndef GWX_AI_H
#define GWX_AI_H
#include <stdint.h>
#define GWX_AI_CONTEXT 64
#define GWX_AI_MODEL_BYTES 159744u
typedef int32_t (*gwx_dot64_fn)(const int8_t *,const uint8_t *);
struct gwx_ai_result {int token,eos,label;float score;uint32_t groups;};
int gwx_ai_init(const void *model,uint32_t bytes);
int gwx_ai_tokens(const char *text,uint16_t *tokens,int capacity);
int gwx_ai_summary(const uint8_t samples[64],unsigned channel,unsigned period,char text[160]);
int gwx_ai_run(const uint16_t *tokens,int count,gwx_dot64_fn accelerator,struct gwx_ai_result *result);
int32_t gwx_ai_dot_reference(const int8_t *x,const uint8_t *packed);
uint32_t gwx_ai_working_bytes(void);
uint32_t gwx_ai_quant_epoch(void);
#endif
