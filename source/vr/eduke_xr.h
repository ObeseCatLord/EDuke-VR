// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors

#pragma once

#include <cstdint>
#include <openxr/openxr.h>
#include <string>
#include <vector>

struct SDL_Window;

namespace eduke_xr
{
constexpr float PanelDistance=1.5f, PanelHalfWidth=.9f;
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
    // XR_EXT_hand_tracking joints (XR_HAND_JOINT_PALM_EXT order, LOCAL space).
    static constexpr uint32_t JointCount = 26;
    XrPosef    joints[JointCount] {};
    float      jointRadii[JointCount] {};
    bool       jointsValid = false;
};

struct ActionInput
{
    bool      focused = false;
    XrPosef   headPose {};
    bool      headValid = false;
    HandInput hands[2] {};
};

// The runtime's recommended per-eye image size (largest of both views),
// queried once without a graphics binding; cached for the process.
bool queryRecommendedExtent(uint32_t &width, uint32_t &height, std::string &error);

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
        uint64_t serial = 0;
        XrTime   predictedDisplayTime = 0;
        XrView   views[2] {};
        // Changes effective for this frame's locate timestamp, in time order.
        std::vector<XrEventDataReferenceSpaceChangePending> referenceChanges;
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
    // Redirect native UI into a reusable RGBA8/depth-stencil target. Opaque
    // title menus clear black; overlay capture preserves the rendered stereo
    // world. One logical owner retains the existing acquired XR frame.
    bool        beginMenuPresentation(uint32_t width, uint32_t height, uint64_t &owner, std::string &error, bool overlay = false);
    bool        armMenuPresentation(uint64_t owner, uint32_t width, uint32_t height);
    bool        menuPresentationActive() const;
    bool        menuPresentationArmed() const;
    bool        menuOverlayTargetBound() const;
    // Composite one sequential native segment, mirror it, then clear/reuse the
    // same capture. The original presentation owner and acquired frame remain.
    // Optional two column-major native clip matrices place a world-space segment
    // with LEQUAL testing against existing eye depth; depth writes remain off.
    bool        flushMenuOverlay(XrPosef const &pose, float halfWidth, float halfHeight, bool visible,
                                 std::string &error, char const *capturePrefix = nullptr, float const *worldClipMatrices = nullptr);
    bool        tintMenuWorld(float const *rgba, float const *correction, std::string &error);
    bool        completeMenuPresentation(std::string &error, char const *capturePrefix = nullptr);
    bool        cancelMenuPresentation(std::string &error, bool mirror = true);
    bool        captureFrame(char const *outputPrefix, bool requireDistinct, std::string &error, bool captureDepth = false);
    bool        mirrorEye(uint32_t eye, std::string &error);
    bool        finishFrame(bool submit, std::string &error);
    TickResult  diagnosticFrame(bool verifyPixels, char const *outputPrefix, std::string &error);
    bool        readInput(ActionInput &out, XrTime atTime, std::string &error);
    // Best-effort controller vibration (focused sessions only); hand 0=left.
    bool        vibrate(uint32_t hand, float amplitude, float seconds);
    uint64_t    submittedFrames() const;
    uint64_t    lastSubmittedSerial() const;
    uint64_t    generation() const;
    bool        sessionRunning() const;

  private:
    bool drawMenuCapture(XrPosef const &pose, float halfWidth, float halfHeight, std::string &error, float const *worldClipMatrices = nullptr);
    struct Impl;
    Impl *m_impl;
};

}  // namespace eduke_xr
