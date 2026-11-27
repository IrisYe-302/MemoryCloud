#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../main/transfer.h"
static uint8_t source[48*700],received[48*700];
struct test {size_t written,fail_at;unsigned attempts,backoff,elapsed,calls;bool permanent;};
static enum transfer_write send(const uint8_t *p,size_t n,void *ctx){
    struct test *t=ctx;assert(n==48);t->calls++;
    if(t->written>=t->fail_at && (t->permanent||t->attempts++<3))return TRANSFER_RETRY;
    assert(p==source+t->written);memcpy(received+t->written,p,n);t->written+=n;return TRANSFER_ACCEPTED;
}
static void pause_ms(unsigned ms,void *ctx){struct test *t=ctx;t->elapsed+=ms;if(ms>t->backoff)t->backoff=ms;}
int main(void){
    for(size_t i=0;i<sizeof source;i++)source[i]=i%251;
    struct test t={.fail_at=sizeof source};
    assert(transfer_image(source,sizeof source,send,pause_ms,NULL,&t));
    assert(t.calls==700 && t.elapsed==7200);
    assert(!memcmp(source,received,sizeof source));
    t=(struct test){.fail_at=48*320};
    assert(transfer_image(source,sizeof source,send,pause_ms,NULL,&t));
    assert(t.written==sizeof source);assert(!memcmp(source,received,sizeof source));assert(t.backoff>=80);
    t=(struct test){.fail_at=48*100,.permanent=true};
    assert(!transfer_image(source,sizeof source,send,pause_ms,NULL,&t));assert(t.written<sizeof source);
    puts("Long raster survives transient stalls without duplicate bytes; persistent stalls stop.");
}
