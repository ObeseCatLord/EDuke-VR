// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors

#pragma once

#include <cstdint>
#include <string>

struct SDL_Window;

namespace eduke_xr
{

// A deliberately small OpenXR diagnostic runtime.  It consumes the current
// SDL OpenGL context and does not own the window or graphics context.
class Runtime
{
  public:
    enum class TickResult
    {
        Idle,
        Submitted,
        Exit,
        Error,
    };

    Runtime();
    ~Runtime();
    Runtime(Runtime const &)            = delete;
    Runtime &operator=(Runtime const &) = delete;

    bool       initialize(SDL_Window *window, std::string &error);
    void       shutdown();
    TickResult diagnosticFrame(bool verifyPixels, char const *outputPrefix, std::string &error);
    uint64_t   submittedFrames() const;

  private:
    struct Impl;
    Impl *m_impl;
};

}  // namespace eduke_xr
