// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors

#pragma once

#include <cstdint>
#include <openxr/openxr.h>
#include <string>

struct SDL_Window;

namespace eduke_xr
{
// Save the currently drawn framebuffer without changing its rendering state.
// Used for native-versus-stereo regression captures at the world boundary.
bool captureFramebuffer(char const *path, uint32_t width, uint32_t height, std::string &error);


// Shared OpenXR frame lifecycle.  The caller owns the current SDL OpenGL
// context and must retain it through shutdown.  Native rendering between
// bindEye/bindMultiview and finishFrame owns its ordinary GL state; the runtime
// restores only its framebuffer bindings at the frame boundary.
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

    enum class FrameResult
    {
        Idle,
        Ready,
        Exit,
        Error
    };
    struct Frame
    {
        uint32_t width = 0, height = 0;
        XrTime   predictedDisplayTime = 0;
        XrView   views[2] {};
    };

    Runtime();
    ~Runtime();
    Runtime(Runtime const &)            = delete;
    Runtime &operator=(Runtime const &) = delete;

    bool        initialize(SDL_Window *window, std::string &error, uint32_t renderWidth = 0, uint32_t renderHeight = 0);
    void        shutdown();
    FrameResult beginFrame(Frame &frame, std::string &error);
    bool        bindEye(uint32_t eye, std::string &error);
    bool        bindMultiview(std::string &error);
    bool        captureFrame(char const *outputPrefix, bool requireDistinct, std::string &error);
    bool        mirrorEye(uint32_t eye, std::string &error);
    bool        finishFrame(bool submit, std::string &error);
    TickResult  diagnosticFrame(bool verifyPixels, char const *outputPrefix, std::string &error);
    uint64_t    submittedFrames() const;

  private:
    struct Impl;
    Impl *m_impl;
};

}  // namespace eduke_xr
