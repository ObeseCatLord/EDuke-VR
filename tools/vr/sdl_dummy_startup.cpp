// SPDX-License-Identifier: GPL-2.0-only
// Test-only, owner-only SDL_QUIT source for CPU-only startup-wait coverage.
#include <SDL.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace
{
int (*realPollEvent)(SDL_Event *);
int fifoFd=-2;
char line[32];
size_t lineLength;
bool checked;

bool safeFifo(char const *path, struct stat &before)
{
    return lstat(path, &before) == 0 && S_ISFIFO(before.st_mode) && before.st_uid == geteuid()
        && (before.st_mode & (S_IRWXG | S_IRWXO)) == 0;
}

void initialize()
{
    if (checked) return;
    checked=true;
    realPollEvent=reinterpret_cast<int (*)(SDL_Event *)>(dlsym(RTLD_NEXT, "SDL_PollEvent"));
    char const *path=std::getenv("EDUKE32_TEST_STARTUP_EVENTS");
    char const *video=std::getenv("SDL_VIDEODRIVER");
    char const *privateMode=std::getenv("EDUKE32_TEST_PRIVATE_STARTUP");
    if (!realPollEvent || !path || !*path || !video || std::strcmp(video,"dummy")
        || !privateMode || std::strcmp(privateMode,"1")) return;
    struct stat before, after;
    if (!safeFifo(path,before))
    {
        std::fprintf(stderr,"sdl_dummy_startup: refusing non-owner-only FIFO\n");
        return;
    }
    fifoFd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);
    if (fifoFd < 0 || fstat(fifoFd,&after) || !S_ISFIFO(after.st_mode) || after.st_uid != geteuid()
        || (after.st_mode & (S_IRWXG | S_IRWXO)) || before.st_dev != after.st_dev || before.st_ino != after.st_ino)
    {
        if (fifoFd >= 0) close(fifoFd);
        fifoFd=-1;
        std::fprintf(stderr,"sdl_dummy_startup: FIFO changed or unsafe\n");
        return;
    }
    std::fprintf(stderr,"sdl_dummy_startup: enabled owner-only SDL dummy FIFO\n");
}

bool quitRequested()
{
    char character;
    while (fifoFd >= 0 && read(fifoFd,&character,1) == 1)
    {
        if (character != '\n')
        {
            if (lineLength < sizeof(line)-1) line[lineLength++]=character;
            else lineLength=0;
            continue;
        }
        line[lineLength]='\0';
        lineLength=0;
        if (!std::strcmp(line,"quit")) return true;
    }
    return false;
}
}

extern "C" int SDL_PollEvent(SDL_Event *event)
{
    initialize();
    if (!realPollEvent) return 0;
    int const result=realPollEvent(event);
    if (result || !event || !quitRequested()) return result;
    std::memset(event,0,sizeof(*event));
    event->type=SDL_QUIT;
    std::fprintf(stderr,"sdl_dummy_startup: injected SDL_QUIT\n");
    return 1;
}
