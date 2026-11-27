// Developed with OpenAI Codex assistance; review and explain during the EE250 demo.
#include "status_model.h"
#include "cJSON.h"
#include <stdio.h>
#include <string.h>

bool memory_status_parse(const char *json, int64_t now_us, memory_status_t *out)
{
    cJSON *root = cJSON_ParseWithOpts(json, NULL, true);
    if (!root) return false;
    const cJSON *version = cJSON_GetObjectItemCaseSensitive(root, "version");
    const cJSON *queued = cJSON_GetObjectItemCaseSensitive(root, "queued");
    const cJSON *online = cJSON_GetObjectItemCaseSensitive(root, "printer_online");
    const cJSON *simulation = cJSON_GetObjectItemCaseSensitive(root, "simulated");
    const cJSON *state = cJSON_GetObjectItemCaseSensitive(root, "state");
    const cJSON *job = cJSON_GetObjectItemCaseSensitive(root, "job");
    bool valid = cJSON_IsObject(root) && cJSON_IsNumber(version) && version->valuedouble == 1 &&
        cJSON_IsNumber(queued) && queued->valuedouble >= 0 && queued->valuedouble <= 9999 &&
        queued->valuedouble == queued->valueint && cJSON_IsBool(online) &&
        cJSON_IsBool(simulation) && cJSON_IsString(state) && cJSON_IsString(job) &&
        strlen(job->valuestring) < sizeof(out->job);
    if (valid) {
        valid = !strcmp(state->valuestring,"idle") || !strcmp(state->valuestring,"queued") ||
            !strcmp(state->valuestring,"sending") || !strcmp(state->valuestring,"printed") ||
            !strcmp(state->valuestring,"uncertain") || !strcmp(state->valuestring,"error");
    }
    if (valid) {
        memory_status_t next = {.queued=queued->valueint, .printer_online=cJSON_IsTrue(online),
            .simulated=cJSON_IsTrue(simulation), .received_us=now_us};
        snprintf(next.state,sizeof(next.state),"%s",state->valuestring);
        snprintf(next.job,sizeof(next.job),"%s",job->valuestring);
        *out = next;
    }
    cJSON_Delete(root);
    return valid;
}
