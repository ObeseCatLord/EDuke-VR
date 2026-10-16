// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors

#include "eduke_xr.h"

#include <SDL2/SDL.h>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

namespace
{
bool parsePositive(char const *text, unsigned &value)
{
    char *end            = nullptr;
    errno                = 0;
    unsigned long parsed = std::strtoul(text, &end, 10);
    if (errno || !text[0] || *end || parsed == 0 || parsed > 1000000)
        return false;
    value = static_cast<unsigned>(parsed);
    return true;
}
}  // namespace

int main(int argc, char **argv)
{
    unsigned    wantedFrames = 1, timeoutSeconds = 20;
    char const *prefix = nullptr;
    for (int i = 1; i < argc; ++i)
    {
        if (!std::strcmp(argv[i], "--frames") && i + 1 < argc && parsePositive(argv[++i], wantedFrames))
            continue;
        if (!std::strcmp(argv[i], "--output") && i + 1 < argc)
        {
            prefix = argv[++i];
            continue;
        }
        if (!std::strcmp(argv[i], "--timeout") && i + 1 < argc && parsePositive(argv[++i], timeoutSeconds))
            continue;
        std::fprintf(stderr, "usage: %s [--frames N] [--output PREFIX] [--timeout SECONDS]\n", argv[0]);
        return 2;
    }
    if (SDL_Init(SDL_INIT_VIDEO) != 0)
    {
        std::fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 2;
    }
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_COMPATIBILITY);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 4);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 1);
    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
    SDL_Window *window = SDL_CreateWindow("EDuke32 OpenXR smoke", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED, 64, 64, SDL_WINDOW_OPENGL | SDL_WINDOW_HIDDEN);
    if (!window)
    {
        std::fprintf(stderr, "SDL_CreateWindow: %s\n", SDL_GetError());
        SDL_Quit();
        return 2;
    }
    SDL_GLContext context = SDL_GL_CreateContext(window);
    if (!context)
    {
        std::fprintf(stderr, "SDL_GL_CreateContext: %s\n", SDL_GetError());
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 2;
    }
    eduke_xr::Runtime xr;
    std::string       error;
    if (!xr.initialize(window, error))
    {
        std::fprintf(stderr, "OpenXR initialize: %s\n", error.c_str());
        xr.shutdown();
        SDL_GL_DeleteContext(context);
        SDL_DestroyWindow(window);
        SDL_Quit();
        return 3;
    }
    uint64_t deadline = SDL_GetTicks64() + uint64_t(timeoutSeconds) * 1000;
    uint64_t target   = xr.submittedFrames() + wantedFrames;
    while (SDL_GetTicks64() < deadline && xr.submittedFrames() < target)
    {
        auto result = xr.diagnosticFrame(true, prefix, error);
        if (result == eduke_xr::Runtime::TickResult::Error)
        {
            std::fprintf(stderr, "OpenXR diagnostic: %s\n", error.c_str());
            xr.shutdown();
            SDL_GL_DeleteContext(context);
            SDL_DestroyWindow(window);
            SDL_Quit();
            return 4;
        }
        if (result == eduke_xr::Runtime::TickResult::Exit)
        {
            std::fprintf(stderr, "OpenXR runtime exited before a diagnostic frame was submitted\n");
            xr.shutdown();
            SDL_GL_DeleteContext(context);
            SDL_DestroyWindow(window);
            SDL_Quit();
            return 5;
        }
        if (result == eduke_xr::Runtime::TickResult::Idle)
            SDL_Delay(5);
    }
    uint64_t submitted = xr.submittedFrames();
    std::printf("OpenXR submitted %llu frame(s); each rendered with one multiview glDrawArrays call.\n", static_cast<unsigned long long>(submitted));
    xr.shutdown();
    SDL_GL_DeleteContext(context);
    SDL_DestroyWindow(window);
    SDL_Quit();
    if (submitted < target)
    {
        std::fprintf(stderr, "OpenXR timed out without %u submission(s)\n", wantedFrames);
        return 6;
    }
    return 0;
}
