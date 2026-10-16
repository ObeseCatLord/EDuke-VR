// SPDX-License-Identifier: GPL-2.0-only
// Copyright (C) 2026 EDuke32 VR contributors

#include "eduke_xr.h"

#define XR_USE_PLATFORM_XLIB
#define XR_USE_GRAPHICS_API_OPENGL
#define GL_GLEXT_PROTOTYPES 1
#include <GL/gl.h>
#include <GL/glext.h>
#include <GL/glx.h>
#include <SDL2/SDL.h>
#include <SDL2/SDL_syswm.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <string>
#include <vector>

namespace eduke_xr
{
namespace
{
constexpr uint32_t kViewCount = 2;
constexpr float    kNearZ = .05f, kFarZ = 100.f;

std::string xrError(XrInstance instance, XrResult result, char const *where)
{
    char message[XR_MAX_RESULT_STRING_SIZE] = {};
    if (instance != XR_NULL_HANDLE)
        xrResultToString(instance, result, message);
    return std::string(where) + ": " + (message[0] ? message : std::to_string(result));
}

bool hasExtension(char const *wanted)
{
    GLint count = 0;
    glGetIntegerv(GL_NUM_EXTENSIONS, &count);
    if (count > 0)
    {
        auto getStringi = reinterpret_cast<PFNGLGETSTRINGIPROC>(SDL_GL_GetProcAddress("glGetStringi"));
        for (GLint i = 0; getStringi && i < count; ++i)
            if (!std::strcmp(reinterpret_cast<char const *>(getStringi(GL_EXTENSIONS, i)), wanted))
                return true;
    }
    char const *all = reinterpret_cast<char const *>(glGetString(GL_EXTENSIONS));
    if (!all)
        return false;
    size_t length = std::strlen(wanted);
    for (char const *p = all; (p = std::strstr(p, wanted)); p += length)
        if ((p == all || p[-1] == ' ') && (p[length] == '\0' || p[length] == ' '))
            return true;
    return false;
}

struct GLState
{
    GLint     readFbo = 0, drawFbo = 0, readBuffer = GL_BACK, drawBuffer = GL_BACK, program = 0, vao = 0, arrayBuffer = 0, pixelPackBuffer = 0;
    GLint     activeTexture = GL_TEXTURE0, active2d = 0, activeArray = 0, unit02d = 0, unit0Array = 0;
    GLint     viewport[4] = {}, scissor[4] = {}, packAlignment = 4, packRowLength = 0, packSkipPixels = 0, packSkipRows = 0;
    GLfloat   clearColor[4] = {}, clearDepth = 1;
    GLboolean depthMask = GL_TRUE, colorMask[4] = { GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE };
    GLint     depthFunc = GL_LESS;
    GLboolean depthTest = GL_FALSE, scissorTest = GL_FALSE, blend = GL_FALSE, cull = GL_FALSE, alphaTest = GL_FALSE, rasterizerDiscard = GL_FALSE, srgb = GL_FALSE,
              dither = GL_FALSE;

    void save()
    {
        glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &readFbo);
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &drawFbo);
        glGetIntegerv(GL_READ_BUFFER, &readBuffer);
        glGetIntegerv(GL_DRAW_BUFFER, &drawBuffer);
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
        glGetIntegerv(GL_ARRAY_BUFFER_BINDING, &arrayBuffer);
        glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &pixelPackBuffer);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &activeTexture);
        glGetIntegerv(GL_VIEWPORT, viewport);
        glGetIntegerv(GL_SCISSOR_BOX, scissor);
        glGetFloatv(GL_COLOR_CLEAR_VALUE, clearColor);
        glGetFloatv(GL_DEPTH_CLEAR_VALUE, &clearDepth);
        glGetIntegerv(GL_DEPTH_FUNC, &depthFunc);
        glGetIntegerv(GL_PACK_ALIGNMENT, &packAlignment);
        glGetIntegerv(GL_PACK_ROW_LENGTH, &packRowLength);
        glGetIntegerv(GL_PACK_SKIP_PIXELS, &packSkipPixels);
        glGetIntegerv(GL_PACK_SKIP_ROWS, &packSkipRows);
        glGetBooleanv(GL_DEPTH_WRITEMASK, &depthMask);
        glGetBooleanv(GL_COLOR_WRITEMASK, colorMask);
        depthTest         = glIsEnabled(GL_DEPTH_TEST);
        scissorTest       = glIsEnabled(GL_SCISSOR_TEST);
        blend             = glIsEnabled(GL_BLEND);
        cull              = glIsEnabled(GL_CULL_FACE);
        alphaTest         = glIsEnabled(GL_ALPHA_TEST);
        rasterizerDiscard = glIsEnabled(GL_RASTERIZER_DISCARD);
        srgb              = glIsEnabled(GL_FRAMEBUFFER_SRGB);
        dither            = glIsEnabled(GL_DITHER);
        glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &unit02d);
        glGetIntegerv(GL_TEXTURE_BINDING_2D_ARRAY, &unit0Array);
        glActiveTexture(activeTexture);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &active2d);
        glGetIntegerv(GL_TEXTURE_BINDING_2D_ARRAY, &activeArray);
    }
    void restore() const
    {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, readFbo);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, drawFbo);
        glReadBuffer(readBuffer);
        glDrawBuffer(drawBuffer);
        glUseProgram(program);
        glBindVertexArray(vao);
        glBindBuffer(GL_ARRAY_BUFFER, arrayBuffer);
        glBindBuffer(GL_PIXEL_PACK_BUFFER, pixelPackBuffer);
        glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
        glScissor(scissor[0], scissor[1], scissor[2], scissor[3]);
        glClearColor(clearColor[0], clearColor[1], clearColor[2], clearColor[3]);
        glClearDepth(clearDepth);
        glDepthFunc(depthFunc);
        glPixelStorei(GL_PACK_ALIGNMENT, packAlignment);
        glPixelStorei(GL_PACK_ROW_LENGTH, packRowLength);
        glPixelStorei(GL_PACK_SKIP_PIXELS, packSkipPixels);
        glPixelStorei(GL_PACK_SKIP_ROWS, packSkipRows);
        glDepthMask(depthMask);
        glColorMask(colorMask[0], colorMask[1], colorMask[2], colorMask[3]);
        (depthTest ? glEnable : glDisable)(GL_DEPTH_TEST);
        (scissorTest ? glEnable : glDisable)(GL_SCISSOR_TEST);
        (blend ? glEnable : glDisable)(GL_BLEND);
        (cull ? glEnable : glDisable)(GL_CULL_FACE);
        (alphaTest ? glEnable : glDisable)(GL_ALPHA_TEST);
        (rasterizerDiscard ? glEnable : glDisable)(GL_RASTERIZER_DISCARD);
        (srgb ? glEnable : glDisable)(GL_FRAMEBUFFER_SRGB);
        (dither ? glEnable : glDisable)(GL_DITHER);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, unit02d);
        glBindTexture(GL_TEXTURE_2D_ARRAY, unit0Array);
        glActiveTexture(activeTexture);
        glBindTexture(GL_TEXTURE_2D, active2d);
        glBindTexture(GL_TEXTURE_2D_ARRAY, activeArray);
    }
};

GLuint compile(GLenum type, char const *source, std::string &error)
{
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint ok = 0;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok)
    {
        char log[2048] = {};
        glGetShaderInfoLog(shader, sizeof(log), nullptr, log);
        error = std::string("multiview shader compilation failed: ") + log;
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

void multiply(float *out, float const *a, float const *b)
{
    for (int column = 0; column < 4; ++column)
        for (int row = 0; row < 4; ++row)
        {
            out[column * 4 + row] = 0;
            for (int k = 0; k < 4; ++k) out[column * 4 + row] += a[k * 4 + row] * b[column * 4 + k];
        }
}

void viewMatrix(XrPosef const &pose, float *out)
{
    float x = pose.orientation.x, y = pose.orientation.y, z = pose.orientation.z, w = pose.orientation.w;
    float r[3][3] = { { 1 - 2 * y * y - 2 * z * z, 2 * x * y - 2 * z * w, 2 * x * z + 2 * y * w },
                      { 2 * x * y + 2 * z * w, 1 - 2 * x * x - 2 * z * z, 2 * y * z - 2 * x * w },
                      { 2 * x * z - 2 * y * w, 2 * y * z + 2 * x * w, 1 - 2 * x * x - 2 * y * y } };
    std::memset(out, 0, 16 * sizeof(float));
    for (int row = 0; row < 3; ++row)
        for (int column = 0; column < 3; ++column) out[column * 4 + row] = r[column][row];
    out[12] = -(r[0][0] * pose.position.x + r[1][0] * pose.position.y + r[2][0] * pose.position.z);
    out[13] = -(r[0][1] * pose.position.x + r[1][1] * pose.position.y + r[2][1] * pose.position.z);
    out[14] = -(r[0][2] * pose.position.x + r[1][2] * pose.position.y + r[2][2] * pose.position.z);
    out[15] = 1;
}

void projectionMatrix(XrFovf const &fov, float *out)
{
    float left = std::tan(fov.angleLeft), right = std::tan(fov.angleRight), down = std::tan(fov.angleDown), up = std::tan(fov.angleUp);
    std::memset(out, 0, 16 * sizeof(float));
    out[0]  = 2 / (right - left);
    out[5]  = 2 / (up - down);
    out[8]  = (right + left) / (right - left);
    out[9]  = (up + down) / (up - down);
    out[10] = -(kFarZ + kNearZ) / (kFarZ - kNearZ);
    out[11] = -1;
    out[14] = -2 * kFarZ * kNearZ / (kFarZ - kNearZ);
}

uint64_t hashPixels(std::vector<unsigned char> const &pixels)
{
    uint64_t h = 1469598103934665603ULL;
    for (unsigned char c : pixels)
    {
        h ^= c;
        h *= 1099511628211ULL;
    }
    return h;
}

bool writePpm(char const *path, std::vector<unsigned char> const &pixels, uint32_t width, uint32_t height)
{
    FILE *file = std::fopen(path, "wb");
    if (!file)
        return false;
    std::fprintf(file, "P6\n%u %u\n255\n", width, height);
    for (uint32_t y = 0; y < height; ++y)
        for (uint32_t x = 0; x < width; ++x) std::fwrite(&pixels[((height - 1 - y) * width + x) * 4], 1, 3, file);
    return std::fclose(file) == 0;
}

bool glSucceeded(char const *where, std::string &error)
{
    GLenum result = glGetError();
    if (result == GL_NO_ERROR)
        return true;
    error = std::string(where) + ": OpenGL error " + std::to_string(result);
    while (glGetError() != GL_NO_ERROR) { }
    return false;
}

// The caller owns the read FBO and pack state. No rendering or GL cache changes.
bool writeDepthReadback(char const *path, uint32_t width, uint32_t height, std::string &error)
{
    std::vector<uint32_t> depth(size_t(width)*height);
    glReadPixels(0,0,width,height,GL_DEPTH_COMPONENT,GL_UNSIGNED_INT,depth.data());
    if (!glSucceeded("reading world depth",error)) return false;
    FILE *file=std::fopen(path,"wb");
    if (!file) { error="could not open depth capture"; return false; }
    bool good=std::fwrite(depth.data(),sizeof(uint32_t),depth.size(),file) == depth.size();
    if (std::fclose(file) != 0) good=false;
    if (!good) error="could not write depth capture";
    return good;
}
}  // namespace

bool captureFramebuffer(char const *path, uint32_t width, uint32_t height, std::string &error)
{
    if (!path || !width || !height)
    {
        error="invalid framebuffer capture parameters";
        return false;
    }
    GLState state;
    state.save();
    glBindFramebuffer(GL_READ_FRAMEBUFFER,state.drawFbo);
    glReadBuffer(state.drawFbo ? GL_COLOR_ATTACHMENT0 : GL_BACK);
    glBindBuffer(GL_PIXEL_PACK_BUFFER,0);
    glPixelStorei(GL_PACK_ALIGNMENT,1);
    glPixelStorei(GL_PACK_ROW_LENGTH,0);
    glPixelStorei(GL_PACK_SKIP_PIXELS,0);
    glPixelStorei(GL_PACK_SKIP_ROWS,0);
    std::vector<unsigned char> pixels(size_t(width)*height*4);
    glReadPixels(0,0,width,height,GL_RGBA,GL_UNSIGNED_BYTE,pixels.data());
    bool good=glSucceeded("reading native world framebuffer",error);
    if (good && !writePpm(path,pixels,width,height))
    {
        error="could not write native world framebuffer capture";
        good=false;
    }
    state.restore();
    return good;
}

bool captureFramebufferDepth(char const *path, uint32_t width, uint32_t height, std::string &error)
{
    if (!path || !width || !height) { error="invalid depth capture parameters"; return false; }
    GLState state;
    state.save();
    glBindFramebuffer(GL_READ_FRAMEBUFFER,state.drawFbo);
    glBindBuffer(GL_PIXEL_PACK_BUFFER,0);
    glPixelStorei(GL_PACK_ALIGNMENT,1);
    glPixelStorei(GL_PACK_ROW_LENGTH,0);
    glPixelStorei(GL_PACK_SKIP_PIXELS,0);
    glPixelStorei(GL_PACK_SKIP_ROWS,0);
    bool good=writeDepthReadback(path,width,height,error);
    state.restore();
    return good;
}

struct Runtime::Impl
{
    XrInstance                              instance = XR_NULL_HANDLE;
    XrSystemId                              system   = XR_NULL_SYSTEM_ID;
    XrSession                               session  = XR_NULL_HANDLE;
    XrSpace                                 space    = XR_NULL_HANDLE;
    XrSwapchain                             color    = XR_NULL_HANDLE;
    std::vector<XrSwapchainImageOpenGLKHR>  colorImages;
    std::array<XrView, kViewCount>          views {};
    uint32_t                                width = 0, height = 0;
    GLuint                                  fbo = 0, depth = 0, program = 0, vao = 0, vbo = 0;
    PFNGLFRAMEBUFFERTEXTUREMULTIVIEWOVRPROC multiview = nullptr;
    bool                                    running = false, exiting = false;
    bool                                    frameBegun = false, imageAcquired = false, imageReady = false;
    uint32_t                                imageIndex = 0;
    XrFrameState                            frameState { XR_TYPE_FRAME_STATE };
    GLint                                   previousReadFbo = 0, previousDrawFbo = 0;
    uint64_t                                submitted = 0;

    void destroyGl()
    {
        if (vbo)
            glDeleteBuffers(1, &vbo);
        if (vao)
            glDeleteVertexArrays(1, &vao);
        if (program)
            glDeleteProgram(program);
        if (depth)
            glDeleteTextures(1, &depth);
        if (fbo)
            glDeleteFramebuffers(1, &fbo);
        fbo = depth = program = vao = vbo = 0;
    }
    void destroyXr()
    {
        if (color != XR_NULL_HANDLE)
            xrDestroySwapchain(color);
        if (space != XR_NULL_HANDLE)
            xrDestroySpace(space);
        if (session != XR_NULL_HANDLE)
            xrDestroySession(session);
        if (instance != XR_NULL_HANDLE)
            xrDestroyInstance(instance);
        instance = XR_NULL_HANDLE;
        system   = XR_NULL_SYSTEM_ID;
        session  = XR_NULL_HANDLE;
        space    = XR_NULL_HANDLE;
        color    = XR_NULL_HANDLE;
        colorImages.clear();
        width = height = 0;
        multiview      = nullptr;
        running = exiting = false;
        frameBegun = imageAcquired = imageReady = false;
    }
};

Runtime::Runtime() : m_impl(new Impl)
{
}
Runtime::~Runtime()
{
    shutdown();
    delete m_impl;
}

bool Runtime::initialize(SDL_Window *window, std::string &error, uint32_t renderWidth, uint32_t renderHeight)
{
    shutdown();
    error.clear();
    if (!window || !SDL_GL_GetCurrentContext())
    {
        error = "OpenXR requires a current SDL compatibility OpenGL context";
        return false;
    }
    SDL_SysWMinfo wm {};
    SDL_VERSION(&wm.version);
    if (!SDL_GetWindowWMInfo(window, &wm) || wm.subsystem != SDL_SYSWM_X11)
    {
        error = "OpenXR GLX diagnostic requires an SDL X11 window";
        return false;
    }
    Display    *display    = wm.info.x11.display;
    GLXContext  context    = glXGetCurrentContext();
    GLXDrawable drawable   = glXGetCurrentDrawable();
    int         fbconfigId = 0;
    if (!display || !context || !drawable || glXQueryContext(display, context, GLX_FBCONFIG_ID, &fbconfigId) != 0 || !fbconfigId)
    {
        error = "could not obtain current GLX FBConfig";
        return false;
    }
    int          attrs[] = { GLX_FBCONFIG_ID, fbconfigId, None };
    int          configs = 0;
    GLXFBConfig *found   = glXChooseFBConfig(display, DefaultScreen(display), attrs, &configs);
    if (!found || configs != 1)
    {
        if (found)
            XFree(found);
        error = "could not resolve current GLX FBConfig";
        return false;
    }
    GLXFBConfig  fbconfig = found[0];
    XVisualInfo *visual   = glXGetVisualFromFBConfig(display, fbconfig);
    XFree(found);
    if (!visual)
    {
        error = "could not resolve GLX visual ID";
        return false;
    }
    uint32_t visualid = visual->visualid;
    XFree(visual);
    if (!hasExtension("GL_OVR_multiview2"))
    {
        error = "single-pass stereo unavailable: current GL context lacks GL_OVR_multiview2 (no two-pass fallback)";
        return false;
    }
    m_impl->multiview = reinterpret_cast<PFNGLFRAMEBUFFERTEXTUREMULTIVIEWOVRPROC>(SDL_GL_GetProcAddress("glFramebufferTextureMultiviewOVR"));
    if (!m_impl->multiview)
    {
        error = "single-pass stereo unavailable: glFramebufferTextureMultiviewOVR is not exposed by current GL context";
        return false;
    }

    uint32_t extensionCount = 0;
    XrResult result         = xrEnumerateInstanceExtensionProperties(nullptr, 0, &extensionCount, nullptr);
    if (XR_FAILED(result))
    {
        error = xrError(XR_NULL_HANDLE, result, "xrEnumerateInstanceExtensionProperties");
        return false;
    }
    std::vector<XrExtensionProperties> extensions(extensionCount, { XR_TYPE_EXTENSION_PROPERTIES });
    result      = xrEnumerateInstanceExtensionProperties(nullptr, extensionCount, &extensionCount, extensions.data());
    bool opengl = false;
    for (auto const &extension : extensions)
        if (!std::strcmp(extension.extensionName, XR_KHR_OPENGL_ENABLE_EXTENSION_NAME))
            opengl = true;
    if (XR_FAILED(result) || !opengl)
    {
        error = XR_FAILED(result) ? xrError(XR_NULL_HANDLE, result, "xrEnumerateInstanceExtensionProperties") : "OpenXR runtime lacks XR_KHR_opengl_enable";
        return false;
    }
    char const          *enabled[] = { XR_KHR_OPENGL_ENABLE_EXTENSION_NAME };
    XrInstanceCreateInfo instanceInfo { XR_TYPE_INSTANCE_CREATE_INFO };
    std::snprintf(instanceInfo.applicationInfo.applicationName, sizeof(instanceInfo.applicationInfo.applicationName), "EDuke32 VR");
    instanceInfo.applicationInfo.apiVersion = XR_CURRENT_API_VERSION;
    instanceInfo.enabledExtensionCount      = 1;
    instanceInfo.enabledExtensionNames      = enabled;
    result                                  = xrCreateInstance(&instanceInfo, &m_impl->instance);
    if (XR_FAILED(result))
    {
        error = xrError(XR_NULL_HANDLE, result, "xrCreateInstance");
        shutdown();
        return false;
    }
    XrSystemGetInfo systemInfo { XR_TYPE_SYSTEM_GET_INFO };
    systemInfo.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
    result                = xrGetSystem(m_impl->instance, &systemInfo, &m_impl->system);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrGetSystem");
        shutdown();
        return false;
    }
    PFN_xrGetOpenGLGraphicsRequirementsKHR getRequirements = nullptr;
    result = xrGetInstanceProcAddr(m_impl->instance, "xrGetOpenGLGraphicsRequirementsKHR", reinterpret_cast<PFN_xrVoidFunction *>(&getRequirements));
    XrGraphicsRequirementsOpenGLKHR requirements { XR_TYPE_GRAPHICS_REQUIREMENTS_OPENGL_KHR };
    if (XR_FAILED(result) || !getRequirements || XR_FAILED(result = getRequirements(m_impl->instance, m_impl->system, &requirements)))
    {
        error = XR_FAILED(result) ? xrError(m_impl->instance, result, "xrGetOpenGLGraphicsRequirementsKHR") : "OpenXR runtime did not expose graphics requirements";
        shutdown();
        return false;
    }
    GLint major = 0, minor = 0;
    glGetIntegerv(GL_MAJOR_VERSION, &major);
    glGetIntegerv(GL_MINOR_VERSION, &minor);
    XrVersion glVersion = XR_MAKE_VERSION(major, minor, 0);
    if (glVersion < requirements.minApiVersionSupported || glVersion > requirements.maxApiVersionSupported)
    {
        error = "current OpenGL version is outside OpenXR runtime graphics requirements";
        shutdown();
        return false;
    }
    XrGraphicsBindingOpenGLXlibKHR binding { XR_TYPE_GRAPHICS_BINDING_OPENGL_XLIB_KHR };
    binding.xDisplay    = display;
    binding.visualid    = visualid;
    binding.glxFBConfig = fbconfig;
    binding.glxDrawable = drawable;
    binding.glxContext  = context;
    XrSessionCreateInfo sessionInfo { XR_TYPE_SESSION_CREATE_INFO };
    sessionInfo.next     = &binding;
    sessionInfo.systemId = m_impl->system;
    result               = xrCreateSession(m_impl->instance, &sessionInfo, &m_impl->session);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrCreateSession");
        shutdown();
        return false;
    }
    uint32_t blendCount = 0;
    result              = xrEnumerateEnvironmentBlendModes(m_impl->instance, m_impl->system, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 0, &blendCount, nullptr);
    std::vector<XrEnvironmentBlendMode> blends(blendCount);
    if (XR_SUCCEEDED(result))
        result
        = xrEnumerateEnvironmentBlendModes(m_impl->instance, m_impl->system, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, blendCount, &blendCount, blends.data());
    if (XR_FAILED(result) || std::find(blends.begin(), blends.end(), XR_ENVIRONMENT_BLEND_MODE_OPAQUE) == blends.end())
    {
        error
        = XR_FAILED(result) ? xrError(m_impl->instance, result, "xrEnumerateEnvironmentBlendModes") : "OpenXR runtime does not support opaque stereo composition";
        shutdown();
        return false;
    }
    XrReferenceSpaceCreateInfo spaceInfo { XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
    spaceInfo.referenceSpaceType                 = XR_REFERENCE_SPACE_TYPE_LOCAL;
    spaceInfo.poseInReferenceSpace.orientation.w = 1;
    result                                       = xrCreateReferenceSpace(m_impl->session, &spaceInfo, &m_impl->space);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrCreateReferenceSpace");
        shutdown();
        return false;
    }
    uint32_t viewCount = 0;
    result             = xrEnumerateViewConfigurationViews(m_impl->instance, m_impl->system, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 0, &viewCount, nullptr);
    if (XR_FAILED(result) || viewCount != kViewCount)
    {
        error
        = XR_FAILED(result) ? xrError(m_impl->instance, result, "xrEnumerateViewConfigurationViews") : "OpenXR runtime did not expose exactly two stereo views";
        shutdown();
        return false;
    }
    std::array<XrViewConfigurationView, kViewCount> viewConfig {};
    for (auto &view : viewConfig) view.type = XR_TYPE_VIEW_CONFIGURATION_VIEW;
    result
    = xrEnumerateViewConfigurationViews(m_impl->instance, m_impl->system, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, kViewCount, &viewCount, viewConfig.data());
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrEnumerateViewConfigurationViews");
        shutdown();
        return false;
    }
    XrSystemProperties systemProperties { XR_TYPE_SYSTEM_PROPERTIES };
    result = xrGetSystemProperties(m_impl->instance, m_impl->system, &systemProperties);
    for (auto const &view : viewConfig)
    {
        m_impl->width  = std::max(m_impl->width, view.recommendedImageRectWidth);
        m_impl->height = std::max(m_impl->height, view.recommendedImageRectHeight);
    }
    if (XR_FAILED(result) || !m_impl->width || !m_impl->height || m_impl->width > systemProperties.graphicsProperties.maxSwapchainImageWidth
        || m_impl->height > systemProperties.graphicsProperties.maxSwapchainImageHeight)
    {
        error = XR_FAILED(result) ? xrError(m_impl->instance, result, "xrGetSystemProperties") : "recommended stereo extent exceeds OpenXR system swapchain limits";
        shutdown();
        return false;
    }
    uint32_t formatCount = 0;
    result               = xrEnumerateSwapchainFormats(m_impl->session, 0, &formatCount, nullptr);
    std::vector<int64_t> formats(formatCount);
    if (XR_SUCCEEDED(result))
        result = xrEnumerateSwapchainFormats(m_impl->session, formatCount, &formatCount, formats.data());
    int64_t chosen = 0;
    for (int64_t wanted : { int64_t(GL_SRGB8_ALPHA8), int64_t(GL_RGBA8) })
        if (std::find(formats.begin(), formats.end(), wanted) != formats.end())
        {
            chosen = wanted;
            break;
        }
    if (XR_FAILED(result) || !chosen)
    {
        error = XR_FAILED(result) ? xrError(m_impl->instance, result, "xrEnumerateSwapchainFormats")
                                  : "OpenXR runtime supports neither GL_SRGB8_ALPHA8 nor GL_RGBA8 swapchain images";
        shutdown();
        return false;
    }
    if (renderWidth || renderHeight)
    {
        if (!renderWidth || !renderHeight)
        {
            error = "both OpenXR render dimensions must be specified";
            shutdown();
            return false;
        }
        if (renderWidth > systemProperties.graphicsProperties.maxSwapchainImageWidth
            || renderHeight > systemProperties.graphicsProperties.maxSwapchainImageHeight)
        {
            error = "requested render extent exceeds an OpenXR system limit";
            shutdown();
            return false;
        }
        for (auto const &view : viewConfig)
            if (renderWidth > view.maxImageRectWidth || renderHeight > view.maxImageRectHeight)
            {
                error = "requested render extent exceeds an OpenXR view limit";
                shutdown();
                return false;
            }
        m_impl->width  = renderWidth;
        m_impl->height = renderHeight;
    }
    XrSwapchainCreateInfo swapInfo { XR_TYPE_SWAPCHAIN_CREATE_INFO };
    swapInfo.usageFlags  = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_SAMPLED_BIT;
    swapInfo.format      = chosen;
    swapInfo.sampleCount = 1;
    swapInfo.width       = m_impl->width;
    swapInfo.height      = m_impl->height;
    swapInfo.faceCount   = 1;
    swapInfo.arraySize   = kViewCount;
    swapInfo.mipCount    = 1;
    result               = xrCreateSwapchain(m_impl->session, &swapInfo, &m_impl->color);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrCreateSwapchain");
        shutdown();
        return false;
    }
    uint32_t imageCount = 0;
    result              = xrEnumerateSwapchainImages(m_impl->color, 0, &imageCount, nullptr);
    if (XR_FAILED(result) || !imageCount)
    {
        error = XR_FAILED(result) ? xrError(m_impl->instance, result, "xrEnumerateSwapchainImages") : "OpenXR runtime returned no swapchain images";
        shutdown();
        return false;
    }
    m_impl->colorImages.assign(imageCount, { XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_KHR });
    result = xrEnumerateSwapchainImages(m_impl->color, imageCount, &imageCount, reinterpret_cast<XrSwapchainImageBaseHeader *>(m_impl->colorImages.data()));
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrEnumerateSwapchainImages");
        shutdown();
        return false;
    }
    GLState state;
    state.save();
    std::string shaderError;
    char const *vert = "#version 410 compatibility\n#extension GL_OVR_multiview2 : require\nlayout(num_views=2) in; layout(location=0) in vec3 p; "
                       "layout(location=1) in vec3 c; uniform mat4 uViewProj[2]; flat out vec3 color; void main(){ gl_Position=uViewProj[gl_ViewID_OVR]*vec4(p,1); "
                       "color=c+vec3(0.0,0.08*float(gl_ViewID_OVR),0.22*float(gl_ViewID_OVR)); }";
    char const *frag = "#version 410 compatibility\nflat in vec3 color; out vec4 outColor; void main(){outColor=vec4(color,1);}";
    GLuint      vs = compile(GL_VERTEX_SHADER, vert, shaderError), fs = vs ? compile(GL_FRAGMENT_SHADER, frag, shaderError) : 0;
    if (vs && fs)
    {
        m_impl->program = glCreateProgram();
        glAttachShader(m_impl->program, vs);
        glAttachShader(m_impl->program, fs);
        glLinkProgram(m_impl->program);
        GLint linked = 0;
        glGetProgramiv(m_impl->program, GL_LINK_STATUS, &linked);
        if (!linked)
        {
            char log[2048] = {};
            glGetProgramInfoLog(m_impl->program, sizeof(log), nullptr, log);
            shaderError = std::string("multiview shader link failed: ") + log;
        }
    }
    if (vs)
        glDeleteShader(vs);
    if (fs)
        glDeleteShader(fs);
    if (!shaderError.empty())
    {
        state.restore();
        error = shaderError;
        shutdown();
        return false;
    }
    float vertices[] = { -1, -.75f, -3, .95f, .08f, .05f, 1, -.75f, -3, .1f, .75f, .15f, 1,  .75f, -3, .1f, .25f, .95f,
                         -1, -.75f, -3, .95f, .08f, .05f, 1, .75f,  -3, .1f, .25f, .95f, -1, .75f, -3, .9f, .75f, .05f };
    glGenFramebuffers(1, &m_impl->fbo);
    glGenTextures(1, &m_impl->depth);
    glBindTexture(GL_TEXTURE_2D_ARRAY, m_impl->depth);
    glTexImage3D(GL_TEXTURE_2D_ARRAY, 0, GL_DEPTH_COMPONENT24, m_impl->width, m_impl->height, kViewCount, 0, GL_DEPTH_COMPONENT, GL_UNSIGNED_INT, nullptr);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glGenVertexArrays(1, &m_impl->vao);
    glBindVertexArray(m_impl->vao);
    glGenBuffers(1, &m_impl->vbo);
    glBindBuffer(GL_ARRAY_BUFFER, m_impl->vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float), nullptr);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 6 * sizeof(float), reinterpret_cast<void *>(3 * sizeof(float)));
    glEnableVertexAttribArray(1);
    state.restore();
    return true;
}

void Runtime::shutdown()
{
    if (!m_impl)
        return;
    bool hasGlResources = m_impl->fbo || m_impl->depth || m_impl->program || m_impl->vao || m_impl->vbo;
    bool hasXrResources
    = m_impl->instance != XR_NULL_HANDLE || m_impl->session != XR_NULL_HANDLE || m_impl->space != XR_NULL_HANDLE || m_impl->color != XR_NULL_HANDLE;
    bool    hasContext = hasGlResources && SDL_GL_GetCurrentContext() != nullptr;
    GLState state;
    if (hasContext)
        state.save();
    if (hasContext)
    {
        // xrDestroySwapchain requires application graphics work referring to
        // its images to have completed.  xrEndFrame alone does not wait for
        // our last draw, and the native hook only reads back the first frame.
        glFinish();
        m_impl->destroyGl();
    }
    if (hasXrResources)
        m_impl->destroyXr();
    m_impl->colorImages.clear();
    m_impl->system = XR_NULL_SYSTEM_ID;
    m_impl->width = m_impl->height = 0;
    m_impl->multiview              = nullptr;
    m_impl->submitted              = 0;
    m_impl->running = m_impl->exiting = false;
    if (hasContext)
        state.restore();
}

Runtime::FrameResult Runtime::beginFrame(Frame &frame, std::string &error)
{
    error.clear();
    frame = {};
    if (!m_impl->instance || !m_impl->session || m_impl->frameBegun)
    {
        error = m_impl->frameBegun ? "previous OpenXR frame is still open" : "OpenXR runtime is not initialized";
        return FrameResult::Error;
    }
    XrEventDataBuffer event { XR_TYPE_EVENT_DATA_BUFFER };
    while (true)
    {
        XrResult result = xrPollEvent(m_impl->instance, &event);
        if (result == XR_EVENT_UNAVAILABLE)
            break;
        if (XR_FAILED(result))
        {
            error = xrError(m_impl->instance, result, "xrPollEvent");
            return FrameResult::Error;
        }
        if (event.type == XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING)
        {
            m_impl->exiting = true;
            m_impl->running = false;
        }
        else if (event.type == XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED)
        {
            auto const *changed = reinterpret_cast<XrEventDataSessionStateChanged const *>(&event);
            if (changed->state == XR_SESSION_STATE_READY)
            {
                XrSessionBeginInfo begin { XR_TYPE_SESSION_BEGIN_INFO };
                begin.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
                result                             = xrBeginSession(m_impl->session, &begin);
                if (XR_FAILED(result))
                {
                    error = xrError(m_impl->instance, result, "xrBeginSession");
                    return FrameResult::Error;
                }
                m_impl->running = true;
            }
            else if (changed->state == XR_SESSION_STATE_STOPPING)
            {
                if (m_impl->running)
                {
                    result = xrEndSession(m_impl->session);
                    if (XR_FAILED(result))
                    {
                        error = xrError(m_impl->instance, result, "xrEndSession");
                        return FrameResult::Error;
                    }
                }
                m_impl->running = false;
            }
            else if (changed->state == XR_SESSION_STATE_EXITING || changed->state == XR_SESSION_STATE_LOSS_PENDING)
            {
                m_impl->exiting = true;
                m_impl->running = false;
            }
        }
        event = { XR_TYPE_EVENT_DATA_BUFFER };
    }
    if (m_impl->exiting)
        return FrameResult::Exit;
    if (!m_impl->running)
        return FrameResult::Idle;
    XrFrameWaitInfo waitInfo { XR_TYPE_FRAME_WAIT_INFO };
    m_impl->frameState  = { XR_TYPE_FRAME_STATE };
    auto    &frameState = m_impl->frameState;
    XrResult result     = xrWaitFrame(m_impl->session, &waitInfo, &frameState);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrWaitFrame");
        return FrameResult::Error;
    }
    XrFrameBeginInfo beginInfo { XR_TYPE_FRAME_BEGIN_INFO };
    result = xrBeginFrame(m_impl->session, &beginInfo);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrBeginFrame");
        return FrameResult::Error;
    }
    m_impl->frameBegun = true;
    if (!frameState.shouldRender)
        return finishFrame(false, error) ? FrameResult::Idle : FrameResult::Error;
    XrViewLocateInfo locate { XR_TYPE_VIEW_LOCATE_INFO };
    locate.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
    locate.displayTime           = frameState.predictedDisplayTime;
    locate.space                 = m_impl->space;
    XrViewState viewState { XR_TYPE_VIEW_STATE };
    uint32_t    count = 0;
    for (auto &view : m_impl->views) view.type = XR_TYPE_VIEW;
    result = xrLocateViews(m_impl->session, &locate, &viewState, kViewCount, &count, m_impl->views.data());
    if (XR_FAILED(result) || count != kViewCount)
    {
        error = XR_FAILED(result) ? xrError(m_impl->instance, result, "xrLocateViews") : "OpenXR did not provide valid stereo view poses";
        finishFrame(false, error);
        return FrameResult::Error;
    }
    // Validity can be temporarily absent at session start or while tracking
    // recovers.  Keep polling instead of treating this as a fatal API error.
    if ((viewState.viewStateFlags & (XR_VIEW_STATE_POSITION_VALID_BIT | XR_VIEW_STATE_ORIENTATION_VALID_BIT))
        != (XR_VIEW_STATE_POSITION_VALID_BIT | XR_VIEW_STATE_ORIENTATION_VALID_BIT))
        return finishFrame(false, error) ? FrameResult::Idle : FrameResult::Error;
    auto                       &imageIndex = m_impl->imageIndex;
    XrSwapchainImageAcquireInfo acquire { XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO };
    result = xrAcquireSwapchainImage(m_impl->color, &acquire, &imageIndex);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrAcquireSwapchainImage");
        finishFrame(false, error);
        return FrameResult::Error;
    }
    m_impl->imageAcquired = true;
    XrSwapchainImageWaitInfo imageWait { XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO };
    imageWait.timeout = 1000LL * 1000LL * 1000LL;
    result            = xrWaitSwapchainImage(m_impl->color, &imageWait);
    if (result != XR_SUCCESS)
    {
        error = xrError(m_impl->instance, result, "xrWaitSwapchainImage");
        return FrameResult::Error;
    }
    m_impl->imageReady = true;
    glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &m_impl->previousReadFbo);
    glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &m_impl->previousDrawFbo);
    frame.width                = m_impl->width;
    frame.height               = m_impl->height;
    frame.predictedDisplayTime = frameState.predictedDisplayTime;
    std::copy(m_impl->views.begin(), m_impl->views.end(), frame.views);
    return FrameResult::Ready;
}

bool Runtime::bindEye(uint32_t eye, std::string &error)
{
    if (!m_impl->frameBegun || !m_impl->imageReady || eye >= kViewCount)
    {
        error = "cannot bind an eye without a ready OpenXR frame";
        return false;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, m_impl->fbo);
    glFramebufferTextureLayer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, m_impl->colorImages[m_impl->imageIndex].image, 0, eye);
    glFramebufferTextureLayer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, m_impl->depth, 0, eye);
    glDrawBuffer(GL_COLOR_ATTACHMENT0);
    GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    if (status != GL_FRAMEBUFFER_COMPLETE)
    {
        error = "OpenXR eye framebuffer incomplete: " + std::to_string(status);
        return false;
    }
    return glSucceeded("binding OpenXR eye", error);
}

bool Runtime::bindMultiview(std::string &error)
{
    if (!m_impl->frameBegun || !m_impl->imageReady)
    {
        error = "cannot bind multiview without a ready OpenXR frame";
        return false;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, m_impl->fbo);
    m_impl->multiview(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, m_impl->colorImages[m_impl->imageIndex].image, 0, 0, kViewCount);
    m_impl->multiview(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, m_impl->depth, 0, 0, kViewCount);
    glDrawBuffer(GL_COLOR_ATTACHMENT0);
    GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    if (status != GL_FRAMEBUFFER_COMPLETE)
    {
        error = "OpenXR multiview framebuffer incomplete: " + std::to_string(status);
        return false;
    }
    return glSucceeded("binding OpenXR multiview", error);
}

bool Runtime::captureFrame(char const *outputPrefix, bool requireDistinct, std::string &error, bool captureDepth)
{
    if (!m_impl->frameBegun || !m_impl->imageReady)
    {
        error = "cannot capture without a ready OpenXR frame";
        return false;
    }
    GLState state;
    state.save();
    uint32_t imageIndex = m_impl->imageIndex;
    bool     pixelsOk   = true;
    {
        std::array<uint64_t, kViewCount> hashes {};
        std::vector<unsigned char>       pixels(size_t(m_impl->width) * m_impl->height * 4);
        GLuint                           read = 0;
        glGenFramebuffers(1, &read);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, read);
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glPixelStorei(GL_PACK_ROW_LENGTH, 0);
        glPixelStorei(GL_PACK_SKIP_PIXELS, 0);
        glPixelStorei(GL_PACK_SKIP_ROWS, 0);
        for (uint32_t layer = 0; layer < kViewCount; ++layer)
        {
            glFramebufferTextureLayer(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, m_impl->colorImages[imageIndex].image, 0, layer);
            if (captureDepth)
                glFramebufferTextureLayer(GL_READ_FRAMEBUFFER,GL_DEPTH_ATTACHMENT,m_impl->depth,0,layer);
            glReadBuffer(GL_COLOR_ATTACHMENT0);
            if (glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE || !glSucceeded("setting up diagnostic readback", error))
            {
                pixelsOk = false;
                break;
            }
            glReadPixels(0, 0, m_impl->width, m_impl->height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
            if (!glSucceeded("reading diagnostic layer", error))
            {
                pixelsOk = false;
                break;
            }
            bool nonBackground = false;
            for (size_t i = 0; i < pixels.size(); i += 4)
                if (pixels[i] > 20 || pixels[i + 1] > 25 || pixels[i + 2] > 45)
                {
                    nonBackground = true;
                    break;
                }
            hashes[layer] = hashPixels(pixels);
            if (outputPrefix)
            {
                std::string path = std::string(outputPrefix) + (layer ? "-right.ppm" : "-left.ppm");
                if (!writePpm(path.c_str(), pixels, m_impl->width, m_impl->height))
                {
                    error    = "could not write diagnostic PPM";
                    pixelsOk = false;
                    break;
                }
                if (captureDepth)
                {
                    std::string depthPath=std::string(outputPrefix)+(layer ? "-right-depth.bin" : "-left-depth.bin");
                    if (!writeDepthReadback(depthPath.c_str(),m_impl->width,m_impl->height,error))
                    {
                        pixelsOk=false;
                        break;
                    }
                }
            }
            if (requireDistinct && !nonBackground)
            {
                error    = "diagnostic layer contains only its background";
                pixelsOk = false;
                break;
            }
        }
        if (pixelsOk && requireDistinct && hashes[0] == hashes[1])
        {
            error    = "diagnostic layers are identical";
            pixelsOk = false;
        }
        glDeleteFramebuffers(1, &read);
        if (!glSucceeded("cleaning up diagnostic readback", error))
            pixelsOk = false;
    }
    state.restore();
    return pixelsOk;
}

bool Runtime::mirrorEye(uint32_t eye, std::string &error)
{
    if (!bindEye(eye, error))
        return false;
    // FBOs and scissor are restored exactly; no engine-cached state is changed.
    GLboolean const scissor = glIsEnabled(GL_SCISSOR_TEST);
    glDisable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, m_impl->fbo);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, m_impl->previousDrawFbo);
    glBlitFramebuffer(0, 0, m_impl->width, m_impl->height, 0, 0,
                      m_impl->width, m_impl->height, GL_COLOR_BUFFER_BIT, GL_NEAREST);
    if (scissor)
        glEnable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, m_impl->previousReadFbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, m_impl->previousDrawFbo);
    return glSucceeded("mirroring OpenXR eye", error);
}

bool Runtime::finishFrame(bool submit, std::string &error)
{
    if (!m_impl->frameBegun)
    {
        error = "no OpenXR frame is open";
        return false;
    }
    if (m_impl->imageAcquired && !m_impl->imageReady)
    {
        error = "acquired OpenXR image never became ready; runtime shutdown is required";
        return false;
    }
    if (m_impl->imageReady)
    {
        // Rendering belongs to the caller.  Preserve its engine GL state cache:
        // only the framebuffer bindings owned by this adapter are restored.
        glBindFramebuffer(GL_READ_FRAMEBUFFER, m_impl->previousReadFbo);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, m_impl->previousDrawFbo);
        XrSwapchainImageReleaseInfo release { XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO };
        XrResult                    result = xrReleaseSwapchainImage(m_impl->color, &release);
        if (XR_FAILED(result))
        {
            error = xrError(m_impl->instance, result, "xrReleaseSwapchainImage");
            return false;
        }
        m_impl->imageReady = m_impl->imageAcquired = false;
    }
    else if (submit)
    {
        error = "cannot submit without rendering a ready OpenXR image";
        return false;
    }
    if (!submit)
    {
        XrFrameEndInfo end { XR_TYPE_FRAME_END_INFO };
        end.displayTime          = m_impl->frameState.predictedDisplayTime;
        end.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
        XrResult result          = xrEndFrame(m_impl->session, &end);
        m_impl->frameBegun       = false;
        if (XR_FAILED(result))
        {
            error = xrError(m_impl->instance, result, "xrEndFrame");
            return false;
        }
        return true;
    }
    XrResult                                                 result;
    std::array<XrCompositionLayerProjectionView, kViewCount> layerViews {};
    for (uint32_t i = 0; i < kViewCount; ++i)
    {
        layerViews[i].type                      = XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW;
        layerViews[i].pose                      = m_impl->views[i].pose;
        layerViews[i].fov                       = m_impl->views[i].fov;
        layerViews[i].subImage.swapchain        = m_impl->color;
        layerViews[i].subImage.imageRect.extent = { int32_t(m_impl->width), int32_t(m_impl->height) };
        layerViews[i].subImage.imageArrayIndex  = i;
    }
    XrCompositionLayerProjection projection { XR_TYPE_COMPOSITION_LAYER_PROJECTION };
    projection.space                             = m_impl->space;
    projection.viewCount                         = kViewCount;
    projection.views                             = layerViews.data();
    XrCompositionLayerBaseHeader const *layers[] = { reinterpret_cast<XrCompositionLayerBaseHeader const *>(&projection) };
    XrFrameEndInfo                      end { XR_TYPE_FRAME_END_INFO };
    end.displayTime          = m_impl->frameState.predictedDisplayTime;
    end.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
    end.layerCount           = 1;
    end.layers               = layers;
    result                   = xrEndFrame(m_impl->session, &end);
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrEndFrame");
        return false;
    }
    m_impl->frameBegun = false;
    ++m_impl->submitted;
    return true;
}

Runtime::TickResult Runtime::diagnosticFrame(bool verifyPixels, char const *outputPrefix, std::string &error)
{
    Frame       frame;
    FrameResult result = beginFrame(frame, error);
    if (result == FrameResult::Idle)
        return TickResult::Idle;
    if (result == FrameResult::Exit)
        return TickResult::Exit;
    if (result != FrameResult::Ready)
        return TickResult::Error;
    GLState state;
    state.save();
    while (glGetError() != GL_NO_ERROR) { }
    if (!bindMultiview(error))
    {
        state.restore();
        finishFrame(false, error);
        return TickResult::Error;
    }
    glViewport(0, 0, m_impl->width, m_impl->height);
    glDisable(GL_SCISSOR_TEST);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LEQUAL);
    glDepthMask(GL_TRUE);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDisable(GL_BLEND);
    glDisable(GL_CULL_FACE);
    glDisable(GL_ALPHA_TEST);
    glDisable(GL_RASTERIZER_DISCARD);
    glDisable(GL_FRAMEBUFFER_SRGB);
    glDisable(GL_DITHER);
    glClearColor(.015f, .02f, .04f, 1);
    glClearDepth(1);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    float matrices[kViewCount][16];
    for (uint32_t i = 0; i < kViewCount; ++i)
    {
        float p[16], v[16];
        projectionMatrix(m_impl->views[i].fov, p);
        viewMatrix(m_impl->views[i].pose, v);
        multiply(matrices[i], p, v);
    }
    glUseProgram(m_impl->program);
    glUniformMatrix4fv(glGetUniformLocation(m_impl->program, "uViewProj[0]"), kViewCount, GL_FALSE, &matrices[0][0]);
    glBindVertexArray(m_impl->vao);
    glDrawArrays(GL_TRIANGLES, 0, 6);
    bool rendered = glSucceeded("drawing multiview diagnostic", error);
    if (rendered && verifyPixels)
        rendered = captureFrame(outputPrefix, true, error);
    state.restore();
    if (!rendered)
    {
        finishFrame(false, error);
        return TickResult::Error;
    }
    return finishFrame(true, error) ? TickResult::Submitted : TickResult::Error;
}

uint64_t Runtime::submittedFrames() const
{ return m_impl ? m_impl->submitted : 0; }
}  // namespace eduke_xr
