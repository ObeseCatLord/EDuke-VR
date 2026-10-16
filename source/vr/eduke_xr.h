// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors

#pragma once

#include <cstdint>
#include <openxr/openxr.h>
#include <string>

struct SDL_Window;

namespace eduke_xr
{
enum HandButton : uint32_t
{
    ButtonSelect     = 1u << 0,
    ButtonGrip       = 1u << 1,
    ButtonPrimary    = 1u << 2,
    ButtonSecondary  = 1u << 3,
    ButtonMenu       = 1u << 4,
    ButtonStickClick = 1u << 5,
};

struct HandInput
{
    uint32_t   buttons = 0, activeButtons = 0;
    XrVector2f stick {};
    bool       stickActive = false;
    XrPosef    aimPose {}, gripPose {};
    bool       aimValid = false, gripValid = false;
};

struct ActionInput
{
    bool      focused = false;
    HandInput hands[2] {};
};

// Save the currently drawn framebuffer without changing its rendering state.
// Used for native-versus-stereo regression captures at the world boundary.
bool captureFramebuffer(char const *path, uint32_t width, uint32_t height, std::string &error);
// Raw GL_UNSIGNED_INT depth samples, bottom row first, for exact local fixtures.
bool captureFramebufferDepth(char const *path, uint32_t width, uint32_t height, std::string &error);


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
    bool        captureFrame(char const *outputPrefix, bool requireDistinct, std::string &error, bool captureDepth = false);
    bool        mirrorEye(uint32_t eye, std::string &error);
    bool        finishFrame(bool submit, std::string &error);
    TickResult  diagnosticFrame(bool verifyPixels, char const *outputPrefix, std::string &error);
    bool        readInput(ActionInput &out, XrTime atTime, std::string &error);
    uint64_t    submittedFrames() const;
    uint64_t    generation() const;

  private:
    struct Impl;
    Impl *m_impl;
};

}  // namespace eduke_xr
