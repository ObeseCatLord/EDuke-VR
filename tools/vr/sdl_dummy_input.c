// SPDX-License-Identifier: GPL-2.0-only
// Test-only SDL2 event source. Runs only in the GPU-denied dummy-video sandbox.
#include <SDL.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
int SDL_PollEvent(SDL_Event *event)
{
    static int (*real_poll)(SDL_Event *);
    static int fd=-2;static char line[96];static unsigned pos;
    if (!real_poll) real_poll=dlsym(RTLD_NEXT,"SDL_PollEvent");
    int result=real_poll(event);
    if (result || !event) return result;
    if (fd==-2)
    {
        const char *path=getenv("EDUKE32_TEST_SDL_INPUT");
        const char *video=getenv("SDL_VIDEODRIVER");
        fd=path && video && !strcmp(video,"dummy") ? open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC) : -1;
    }
    char ch;
    while (fd>=0 && read(fd,&ch,1)==1)
    {
        if (ch!='\n') { if (pos<sizeof(line)-1) line[pos++]=ch;continue; }
        line[pos]=0;pos=0;int scan,held;
        if (sscanf(line,"key %d %d",&scan,&held)!=2 || scan<=0 || scan>=SDL_NUM_SCANCODES || (held!=0 && held!=1)) continue;
        memset(event,0,sizeof(*event));event->type=held ? SDL_KEYDOWN : SDL_KEYUP;
        event->key.state=held ? SDL_PRESSED : SDL_RELEASED;
        event->key.keysym.scancode=scan;event->key.keysym.sym=SDL_GetKeyFromScancode(scan);
        return 1;
    }
    return 0;
}
