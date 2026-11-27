#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum transfer_write { TRANSFER_ACCEPTED, TRANSFER_RETRY, TRANSFER_FAILED };
typedef enum transfer_write (*transfer_sender)(const uint8_t *,size_t,void *);
typedef void (*transfer_pause)(unsigned,void *);
typedef void (*transfer_progress)(size_t,size_t,void *);

/* One 384-dot row per write (requires ATT MTU >= 51).
 * Retry only a write rejected locally, never bytes already accepted by BLE. */
static inline bool transfer_image(const uint8_t *data,size_t size,transfer_sender send,
                                 transfer_pause pause,transfer_progress progress,void *context){
    unsigned delay=10;size_t next_report=48*64;
    for(size_t offset=0;offset<size;){
        size_t chunk=size-offset;if(chunk>48)chunk=48;
        unsigned retries=0;
        for(;;){
            enum transfer_write result=send(data+offset,chunk,context);
            if(result==TRANSFER_ACCEPTED)break;
            if(result==TRANSFER_FAILED || ++retries>8)return false;
            if(delay<160)delay*=2;
            pause(delay,context);
        }
        offset+=chunk;
        if(progress && (offset>=next_report || offset==size)){
            progress(offset,size,context);next_report=offset+48*64;
        }
        pause(delay,context);
    }
    /* Allow the last queued data packet to drain before the control flush. */
    pause(200,context);
    return true;
}
