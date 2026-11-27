#include "status_model.h"
#include <assert.h>
#include <string.h>

int main(void)
{
    memory_status_t s={0};
    assert(memory_status_parse("{\"version\":1,\"queued\":2,\"printer_online\":false,\"simulated\":true,\"state\":\"queued\",\"job\":\"a\"}",123,&s));
    assert(s.queued==2 && !s.printer_online && s.simulated && s.received_us==123);
    assert(!strcmp(s.state,"queued"));
    assert(!memory_status_parse("{\"version\":1,\"queued\":-1,\"printer_online\":false,\"simulated\":true,\"state\":\"queued\",\"job\":\"a\"}",456,&s));
    assert(!memory_status_parse("{\"version\":1,\"queued\":2,\"printer_online\":true,\"simulated\":true,\"state\":\"garbage\",\"job\":\"a\"}",456,&s));
    assert(!memory_status_parse("{}",456,&s));
    assert(!memory_status_parse("not json",456,&s));
    assert(s.received_us==123 && s.queued==2); // Bad packets cannot keep an offline server 'fresh'.
    return 0;
}
