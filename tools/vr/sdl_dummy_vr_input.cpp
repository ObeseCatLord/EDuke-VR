// SPDX-License-Identifier: GPL-2.0-only
// Test-only SDL2 event source for CPU-only native VR-shot tests.
#include <SDL.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

struct VRShotInput
{
    int16_t offset[3] {}, direction[3] {};
    uint8_t flags=0;
};

namespace
{
static_assert(sizeof(VRShotInput) == 14 && alignof(VRShotInput) == 2,
              "VRShotInput must match the native ABI");

using SetShotInput = void (*)(int, VRShotInput const &);

constexpr uint8_t kShotEnabled=1;
constexpr size_t kLineSize=128;

int (*realPollEvent)(SDL_Event *);
SetShotInput setShotInput;
int *myConnectIndex;
int fifoFd=-2;
char line[kLineSize];
size_t lineLength;
bool lineOverflow;
VRShotInput requestedPose;
bool havePose;
bool publishNotice;
bool helperActive;
bool helperChecked;

void logMessage(char const *message)
{
    std::fprintf(stderr, "sdl_dummy_vr_input: %s\n", message);
}

void logPose(char const *action, VRShotInput const &pose)
{
    std::fprintf(stderr,
                 "sdl_dummy_vr_input: pose %s flags=%u offset=%d,%d,%d direction=%d,%d,%d\n",
                 action, unsigned(pose.flags), int(pose.offset[0]), int(pose.offset[1]), int(pose.offset[2]),
                 int(pose.direction[0]), int(pose.direction[1]), int(pose.direction[2]));
}

bool safeFifo(char const *path, struct stat &before)
{
    if (lstat(path, &before) != 0 || !S_ISFIFO(before.st_mode) || before.st_uid != geteuid()
        || (before.st_mode & (S_IRWXG | S_IRWXO)) != 0)
        return false;
    return true;
}

bool resolveNativeInput()
{
    setShotInput=reinterpret_cast<SetShotInput>(dlsym(RTLD_DEFAULT, "_Z16G_VRSetShotInputiRK11VRShotInput"));
    myConnectIndex=reinterpret_cast<int *>(dlsym(RTLD_DEFAULT, "myconnectindex"));
    if (setShotInput && myConnectIndex) return true;
    logMessage("native VR input unavailable: export G_VRSetShotInput and myconnectindex in the CPU test build");
    return false;
}

void initialize()
{
    if (helperChecked) return;
    helperChecked=true;

    realPollEvent=reinterpret_cast<int (*)(SDL_Event *)>(dlsym(RTLD_NEXT, "SDL_PollEvent"));
    if (!realPollEvent)
    {
        logMessage("could not resolve the real SDL_PollEvent");
        return;
    }

    char const *path=std::getenv("EDUKE32_TEST_SDL_INPUT");
    char const *video=std::getenv("SDL_VIDEODRIVER");
    if (!path || !*path || !video || std::strcmp(video, "dummy") != 0) return;

    struct stat before;
    if (!safeFifo(path, before))
    {
        logMessage("refusing EDUKE32_TEST_SDL_INPUT: require an owner-only FIFO");
        return;
    }

    fifoFd=open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
    if (fifoFd < 0)
    {
        logMessage("could not open EDUKE32_TEST_SDL_INPUT");
        return;
    }

    struct stat after;
    if (fstat(fifoFd, &after) != 0 || !S_ISFIFO(after.st_mode) || after.st_uid != geteuid()
        || (after.st_mode & (S_IRWXG | S_IRWXO)) != 0 || after.st_dev != before.st_dev || after.st_ino != before.st_ino)
    {
        close(fifoFd);
        fifoFd=-1;
        logMessage("refusing EDUKE32_TEST_SDL_INPUT: FIFO changed or is unsafe");
        return;
    }

    if (!resolveNativeInput())
    {
        close(fifoFd);
        fifoFd=-1;
        return;
    }

    helperActive=true;
    logMessage("enabled owner-only FIFO input in SDL dummy mode");
}

void skipSpace(char const *&cursor)
{
    while (*cursor == ' ' || *cursor == '\t' || *cursor == '\r') ++cursor;
}

bool takeWord(char const *&cursor, char const *word)
{
    skipSpace(cursor);
    size_t const wordLength=std::strlen(word);
    if (std::strncmp(cursor, word, wordLength) != 0) return false;
    char const next=cursor[wordLength];
    if (next != '\0' && next != ' ' && next != '\t' && next != '\r') return false;
    cursor+=wordLength;
    return true;
}

bool takeLong(char const *&cursor, long &value)
{
    skipSpace(cursor);
    errno=0;
    char *end=nullptr;
    value=std::strtol(cursor, &end, 10);
    if (cursor == end || errno == ERANGE) return false;
    cursor=end;
    return true;
}

bool atEnd(char const *cursor)
{
    skipSpace(cursor);
    return *cursor == '\0';
}

bool takeInt16(char const *&cursor, int16_t &value)
{
    long number;
    if (!takeLong(cursor, number) || number < std::numeric_limits<int16_t>::min()
        || number > std::numeric_limits<int16_t>::max())
        return false;
    value=static_cast<int16_t>(number);
    return true;
}

void publishPose()
{
    if (!helperActive || !havePose) return;
    if (!(requestedPose.flags & kShotEnabled) && !publishNotice) return;

    int const player=*myConnectIndex;
    if (player <= 0 || player >= 16) return;

    setShotInput(player, requestedPose);
    if (publishNotice)
    {
        logPose("published", requestedPose);
        publishNotice=false;
    }
}

void parsePose(char const *cursor)
{
    long flags;
    VRShotInput pose;
    if (!takeLong(cursor, flags) || (flags != 0 && flags != 1 && flags != 3)) return;
    pose.flags=static_cast<uint8_t>(flags);
    for (int i=0; i<3; ++i)
        if (!takeInt16(cursor, pose.offset[i])) return;
    for (int i=0; i<3; ++i)
        if (!takeInt16(cursor, pose.direction[i])) return;
    if (!atEnd(cursor)) return;

    if (!havePose || requestedPose.flags!=pose.flags
        || std::memcmp(requestedPose.offset,pose.offset,sizeof(pose.offset))
        || std::memcmp(requestedPose.direction,pose.direction,sizeof(pose.direction)))
    {
        requestedPose=pose;
        havePose=true;
        publishNotice=true;
        logPose("received", requestedPose);
    }
}

bool makeKeyEvent(char const *cursor, SDL_Event *event)
{
    long scan;
    long held;
    if (!takeLong(cursor, scan) || !takeLong(cursor, held) || !atEnd(cursor)
        || scan <= 0 || scan >= SDL_NUM_SCANCODES || (held != 0 && held != 1))
        return false;

    std::memset(event, 0, sizeof(*event));
    event->type=held ? SDL_KEYDOWN : SDL_KEYUP;
    event->key.state=held ? SDL_PRESSED : SDL_RELEASED;
    event->key.keysym.scancode=static_cast<SDL_Scancode>(scan);
    event->key.keysym.sym=SDL_GetKeyFromScancode(event->key.keysym.scancode);
    return true;
}

bool readInput(SDL_Event *event)
{
    char character;
    while (read(fifoFd, &character, 1) == 1)
    {
        if (character != '\n')
        {
            if (lineLength < sizeof(line)-1) line[lineLength++]=character;
            else lineOverflow=true;
            continue;
        }

        line[lineLength]='\0';
        lineLength=0;
        if (lineOverflow)
        {
            lineOverflow=false;
            continue;
        }
        char const *cursor=line;
        if (takeWord(cursor, "pose"))
        {
            parsePose(cursor);
            continue;
        }
        if (takeWord(cursor, "key") && makeKeyEvent(cursor, event)) return true;
    }
    return false;
}
}

extern "C" int SDL_PollEvent(SDL_Event *event)
{
    initialize();
    if (!realPollEvent) return 0;

    int const result=realPollEvent(event);
    if (result || !event)
    {
        publishPose();
        return result;
    }

    int const injected=helperActive && readInput(event);
    publishPose();
    return injected ? 1 : 0;
}
