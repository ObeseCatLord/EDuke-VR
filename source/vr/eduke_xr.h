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
    ButtonWheel      = 1u << 6,   // weapon wheel (right stick click; Index: touch the right trackpad)
    ButtonGadget     = 1u << 7,   // gadget wheel (left stick click; Index: touch the left trackpad)
};

struct HandInput
{
    uint32_t   buttons = 0, activeButtons = 0;
    XrVector2f stick {};
    bool       stickActive = false;
    XrPosef    aimPose {}, gripPose {};
    bool       aimValid = false, gripValid = false;
    XrVector3f gripVelocity {}; // LOCAL-space linear velocity, metres/second
    bool       gripVelocityValid = false;
    // XR_EXT_hand_tracking joints (XR_HAND_JOINT_PALM_EXT order, LOCAL space).
    static constexpr uint32_t JointCount = 26;
    XrPosef    joints[JointCount] {};
    float      jointRadii[JointCount] {};
    bool       jointsValid = false;
};

// EDUKE32_XR_PERF: per-interval sums (ms) measured by the runtime.
struct PerfStats
{
    bool     enabled = false;
    double   waitMs = 0, renderMs = 0, flushMs = 0, gpuMs = 0;
    unsigned frames = 0, flushes = 0, gpuFrames = 0;
};

// Foveated rendering of the multiview world (see Runtime::foveateFrame).
enum class Foveation : uint32_t
{
    Off,
    Fixed,       // full detail around each lens centre
    EyeTracked,  // full detail where you look (XR_EXT_eye_gaze_interaction); fixed while gaze is lost
};

struct FoveationStatus
{
    bool        available = false;    // GL multiview with 4 views (both eyes, each wide plus inset)
    bool        eyeTracking = false;  // the system reports an eye tracker
    bool        steamFrame = false;   // a Valve Steam Frame (standalone or streamed)
    bool        gazeTracked = false;  // a tracked gaze located for the current frame
    Foveation   mode = Foveation::Off;  // effective mode (after availability)
    float       scale = 1;
    bool        masked = false;               // radial density masking instead of inset views            // periphery resolution per axis (= inset size, in image fractions)
    uint32_t    width = 0, height = 0;  // per-view size of the foveated target
    std::string systemName, runtimeName;
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
    // Foveation: setFoveation picks the mode and the periphery scale (0.3..1; the full-detail inset is
    // the same fraction of each view). A frame opts in with foveateFrame(true) before its first
    // bindMultiview: from then on bindMultiview binds a 4-view target (views 0,1 the whole eyes at
    // `scale` resolution, 2,3 the full-detail insets; boundViews() and foveationInset() give the replay
    // what it needs) until resolveFoveation() blends it into the swapchain image and depth. Every
    // runtime call that reads or draws the swapchain image resolves first; per-eye native drawing
    // (bindEye) must call resolveFoveation() itself before it draws.
    void            setFoveation(Foveation mode, float scale, bool masked = false);
    // Masked method: call right after clearing the freshly bound foveated target.
    bool            maskFoveation(std::string &error);
    FoveationStatus foveation() const;
    void            foveateFrame(bool on);
    bool            resolveFoveation(std::string &error);
    uint32_t        boundViews() const;
    // Per eye: clip-space xy scale and offset from the full view to its inset (8 floats).
    void            foveationInset(float *out) const;
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
    // uvRect (u0,v0,u1,v1; v up) shows only that crop of the segment on the quad; keep=true
    // leaves the segment in place for another crop.
    bool        flushMenuOverlay(XrPosef const &pose, float halfWidth, float halfHeight, bool visible,
                                 std::string &error, char const *capturePrefix = nullptr, float const *worldClipMatrices = nullptr,
                                 float const *uvRect = nullptr, bool keep = false);
    bool        tintMenuWorld(float const *rgba, float const *correction, std::string &error);
    bool        completeMenuPresentation(std::string &error, char const *capturePrefix = nullptr);
    // Show the finished native back buffer (a flat screen the game drew without a menu
    // presentation: intermissions, logos, cutscenes) on a world-locked virtual screen and submit.
    // held: show the last presented flat screen again (the game is waiting without drawing).
    bool        presentNativeFrame(uint32_t width, uint32_t height, std::string &error, char const *capturePrefix = nullptr,
                                   bool held = false);
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
    void        enablePerf(bool on);
    PerfStats   takePerf();   // returns and resets the accumulated perf sums
    uint64_t    generation() const;
    bool        sessionRunning() const;

  private:
    XrPosef anchoredScreen(XrPosef const &head);
    bool drawMenuCapture(XrPosef const &pose, float halfWidth, float halfHeight, std::string &error, float const *worldClipMatrices = nullptr,
                         float const *uvRect = nullptr);
    struct Impl;
    Impl *m_impl;
};

}  // namespace eduke_xr
