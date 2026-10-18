// SPDX-License-Identifier: GPL-2.0-only
// Test-only native SDL event injection into an owned hidden X11 process.
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
    static int fd=-2;
    static unsigned window_id;
    if (!real_poll) real_poll=dlsym(RTLD_NEXT,"SDL_PollEvent");
    int result=real_poll(event);
    if (result && event && event->type==SDL_WINDOWEVENT) window_id=event->window.windowID;
    if (result || !event) return result;
    if (fd==-2)
    {
        char const *path=getenv("EDUKE32_TEST_WINDOW_EVENTS");
        char const *private_mode=getenv("EDUKE32_TEST_PRIVATE_WINDOW");
        fd=path && private_mode && !strcmp(private_mode,"1") ? open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC) : -1;
    }
    char command;
    if (!window_id)
        for (unsigned id=1; id<=32; ++id)
            if (SDL_GetWindowFromID(id)) { window_id=id; break; }
    while (fd>=0 && window_id && read(fd,&command,1)==1)
    {
        if (command!='m' && command!='r') continue;
        memset(event,0,sizeof(*event));event->type=SDL_WINDOWEVENT;
        event->window.windowID=window_id;
        event->window.event=command=='m' ? SDL_WINDOWEVENT_MINIMIZED : SDL_WINDOWEVENT_RESTORED;
        fprintf(stderr,"Private SDL event helper: %c window=%u.\n",command,window_id);
        return 1;
    }
    return 0;
}
