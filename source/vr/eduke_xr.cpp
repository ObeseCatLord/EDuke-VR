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
#include <cstdlib>
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
    GLint     readFbo = 0, drawFbo = 0, readBuffer = GL_BACK, drawBuffer = GL_BACK, program = 0, vao = 0, arrayBuffer = 0, pixelPackBuffer = 0,
              renderbuffer = 0;
    GLint     activeTexture = GL_TEXTURE0, active2d = 0, activeArray = 0, unit02d = 0, unit0Array = 0, unit0Sampler = 0;
    GLint     viewport[4] = {}, scissor[4] = {}, packAlignment = 4, packRowLength = 0, packSkipPixels = 0, packSkipRows = 0;
    GLfloat   clearColor[4] = {}, clearDepth = 1;
    GLint     clearStencil = 0;
    GLboolean depthMask = GL_TRUE, colorMask[4] = { GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE };
    GLint     depthFunc = GL_LESS, stencilWriteMask = ~0, stencilBackWriteMask = ~0;
    GLboolean depthTest = GL_FALSE, scissorTest = GL_FALSE, blend = GL_FALSE, cull = GL_FALSE, alphaTest = GL_FALSE, rasterizerDiscard = GL_FALSE, srgb = GL_FALSE,
              dither = GL_FALSE, stencilTest = GL_FALSE;

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
        glGetIntegerv(GL_RENDERBUFFER_BINDING, &renderbuffer);
        glGetIntegerv(GL_ACTIVE_TEXTURE, &activeTexture);
        glGetIntegerv(GL_VIEWPORT, viewport);
        glGetIntegerv(GL_SCISSOR_BOX, scissor);
        glGetFloatv(GL_COLOR_CLEAR_VALUE, clearColor);
        glGetFloatv(GL_DEPTH_CLEAR_VALUE, &clearDepth);
        glGetIntegerv(GL_STENCIL_CLEAR_VALUE, &clearStencil);
        glGetIntegerv(GL_DEPTH_FUNC, &depthFunc);
        glGetIntegerv(GL_STENCIL_WRITEMASK, &stencilWriteMask);
        glGetIntegerv(GL_STENCIL_BACK_WRITEMASK, &stencilBackWriteMask);
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
        stencilTest       = glIsEnabled(GL_STENCIL_TEST);
        glActiveTexture(GL_TEXTURE0);
        glGetIntegerv(GL_TEXTURE_BINDING_2D, &unit02d);
        glGetIntegerv(GL_TEXTURE_BINDING_2D_ARRAY, &unit0Array);
        glGetIntegerv(GL_SAMPLER_BINDING, &unit0Sampler);
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
        glBindRenderbuffer(GL_RENDERBUFFER, renderbuffer);
        glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
        glScissor(scissor[0], scissor[1], scissor[2], scissor[3]);
        glClearColor(clearColor[0], clearColor[1], clearColor[2], clearColor[3]);
        glClearDepth(clearDepth);
        glClearStencil(clearStencil);
        glDepthFunc(depthFunc);
        glStencilMaskSeparate(GL_FRONT, stencilWriteMask);
        glStencilMaskSeparate(GL_BACK, stencilBackWriteMask);
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
        (stencilTest ? glEnable : glDisable)(GL_STENCIL_TEST);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, unit02d);
        glBindTexture(GL_TEXTURE_2D_ARRAY, unit0Array);
        glBindSampler(0, unit0Sampler);
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

void poseMatrix(XrPosef const &pose, float *out)
{
    float const x = pose.orientation.x, y = pose.orientation.y, z = pose.orientation.z, w = pose.orientation.w;
    out[0] = 1 - 2 * y * y - 2 * z * z; out[1] = 2 * x * y + 2 * z * w;     out[2] = 2 * x * z - 2 * y * w;     out[3] = 0;
    out[4] = 2 * x * y - 2 * z * w;     out[5] = 1 - 2 * x * x - 2 * z * z; out[6] = 2 * y * z + 2 * x * w;     out[7] = 0;
    out[8] = 2 * x * z + 2 * y * w;     out[9] = 2 * y * z - 2 * x * w;     out[10] = 1 - 2 * x * x - 2 * y * y; out[11] = 0;
    out[12] = pose.position.x; out[13] = pose.position.y; out[14] = pose.position.z; out[15] = 1;
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

bool writeTexturePpm(GLuint texture, uint32_t width, uint32_t height, char const *path, std::string &error)
{
    if (!texture || !width || !height || !path)
    {
        error = "invalid menu capture parameters";
        return false;
    }
    GLState state;
    state.save();
    GLuint read = 0;
    glGenFramebuffers(1, &read);
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read);
    glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ROW_LENGTH, 0);
    glPixelStorei(GL_PACK_SKIP_PIXELS, 0);
    glPixelStorei(GL_PACK_SKIP_ROWS, 0);
    std::vector<unsigned char> pixels(size_t(width) * height * 4);
    bool good = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    if (good)
    {
        glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
        good = glSucceeded("reading menu capture", error);
    }
    if (good && !writePpm(path, pixels, width, height))
    {
        error = "could not write menu capture PPM";
        good = false;
    }
    glDeleteFramebuffers(1, &read);
    if (good)
        good = glSucceeded("cleaning up menu capture readback", error);
    state.restore();
    return good;
}

struct Runtime::Impl
{
    XrInstance                              instance = XR_NULL_HANDLE;
    XrSystemId                              system   = XR_NULL_SYSTEM_ID;
    XrSession                               session  = XR_NULL_HANDLE;
    XrSpace                                 space    = XR_NULL_HANDLE;
    XrSpace                                 viewSpace = XR_NULL_HANDLE;
    XrActionSet                             actionSet = XR_NULL_HANDLE;
    std::array<XrAction, 6>                 buttonActions {};
    XrAction                                stickAction = XR_NULL_HANDLE, gripPoseAction = XR_NULL_HANDLE, aimPoseAction = XR_NULL_HANDLE;
    std::array<XrPath, kViewCount>          handPaths {};
    std::array<XrSpace, kViewCount>         gripSpaces {}, aimSpaces {};
    XrSwapchain                             color    = XR_NULL_HANDLE;
    std::vector<XrSwapchainImageOpenGLKHR>  colorImages;
    std::array<XrView, kViewCount>          views {};
    uint32_t                                width = 0, height = 0;
    GLuint                                  fbo = 0, depth = 0, program = 0, vao = 0, vbo = 0;
    GLuint                                  menuFbo = 0, menuColor = 0, menuDepth = 0, menuProgram = 0, menuVao = 0, menuVbo = 0;
    PFNGLFRAMEBUFFERTEXTUREMULTIVIEWOVRPROC multiview = nullptr;
    bool                                    running = false, exiting = false;
    XrSessionState                          sessionState = XR_SESSION_STATE_UNKNOWN;
    bool                                    frameBegun = false, imageAcquired = false, imageReady = false;
    uint32_t                                imageIndex = 0;
    XrFrameState                            frameState { XR_TYPE_FRAME_STATE };
    GLint                                   previousReadFbo = 0, previousDrawFbo = 0;
    uint64_t                                submitted = 0;
    uint64_t                                actionGeneration = 0;
    uint64_t                                nextMenuOwner = 0, menuOwner = 0;
    uint32_t                                menuWidth = 0, menuHeight = 0;
    bool                                    menuActive = false, menuArmed = false;
    struct NativeTarget { GLint readFbo=0, drawFbo=0, readBuffer=GL_BACK, drawBuffer=GL_BACK; } menuNativeState;

    void restoreMenuTarget()
    {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, menuNativeState.readFbo);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, menuNativeState.drawFbo);
        glReadBuffer(menuNativeState.readBuffer);
        glDrawBuffer(menuNativeState.drawBuffer);
    }

    void clearMenuPresentation()
    {
        menuActive = menuArmed = false;
        menuOwner = 0;
    }

    void destroyMenuGl()
    {
        if (menuVbo)
            glDeleteBuffers(1, &menuVbo);
        if (menuVao)
            glDeleteVertexArrays(1, &menuVao);
        if (menuProgram)
            glDeleteProgram(menuProgram);
        if (menuDepth)
            glDeleteRenderbuffers(1, &menuDepth);
        if (menuColor)
            glDeleteTextures(1, &menuColor);
        if (menuFbo)
            glDeleteFramebuffers(1, &menuFbo);
        menuFbo = menuColor = menuDepth = menuProgram = menuVao = menuVbo = 0;
        menuWidth = menuHeight = 0;
        clearMenuPresentation();
    }

    bool ensureMenuProgram(std::string &error)
    {
        if (menuProgram && menuVao && menuVbo && viewSpace != XR_NULL_HANDLE) return true;
        auto fail = [&] {
            destroyMenuGl();
            if (viewSpace != XR_NULL_HANDLE) xrDestroySpace(viewSpace);
            viewSpace=XR_NULL_HANDLE;
            return false;
        };
        XrReferenceSpaceCreateInfo info { XR_TYPE_REFERENCE_SPACE_CREATE_INFO };
        info.referenceSpaceType=XR_REFERENCE_SPACE_TYPE_VIEW;
        info.poseInReferenceSpace.orientation.w=1;
        XrResult const result=xrCreateReferenceSpace(session,&info,&viewSpace);
        if (XR_FAILED(result))
        {
            error=xrError(instance,result,"xrCreateReferenceSpace view");
            return fail();
        }
        std::string shaderError;
        char const *menuVert = "#version 410 compatibility\n#extension GL_OVR_multiview2 : require\nlayout(num_views=2) in; layout(location=0) in vec3 p; "
                               "layout(location=1) in vec2 uv; uniform mat4 uViewProj[2]; out vec2 texcoord; void main(){ gl_Position=uViewProj[gl_ViewID_OVR]*vec4(p,1); texcoord=uv; }";
        char const *menuFrag = "#version 410 compatibility\nin vec2 texcoord; uniform sampler2D uTexture; out vec4 outColor; "
                               "void main(){ outColor=vec4(texture(uTexture,texcoord).rgb,1); }";
        GLuint menuVs = compile(GL_VERTEX_SHADER, menuVert, shaderError), menuFs = menuVs ? compile(GL_FRAGMENT_SHADER, menuFrag, shaderError) : 0;
        if (menuVs && menuFs)
        {
            menuProgram = glCreateProgram();
            glAttachShader(menuProgram, menuVs);
            glAttachShader(menuProgram, menuFs);
            glLinkProgram(menuProgram);
            GLint linked = 0;
            glGetProgramiv(menuProgram, GL_LINK_STATUS, &linked);
            if (!linked)
            {
                char log[2048] = {};
                glGetProgramInfoLog(menuProgram, sizeof(log), nullptr, log);
                shaderError = std::string("menu presentation shader link failed: ") + log;
            }
        }
        if (menuVs)
            glDeleteShader(menuVs);
        if (menuFs)
            glDeleteShader(menuFs);
        if (!shaderError.empty()) { error=shaderError; return fail(); }
        float menuVertices[] = { -1, -1, 0, 0, 0, 1, -1, 0, 1, 0, 1, 1, 0, 1, 1, -1, -1, 0, 0, 0, 1, 1, 0, 1, 1, -1, 1, 0, 0, 1 };
        glGenVertexArrays(1, &menuVao);
        glBindVertexArray(menuVao);
        glGenBuffers(1, &menuVbo);
        glBindBuffer(GL_ARRAY_BUFFER, menuVbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(menuVertices), menuVertices, GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 5 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 5 * sizeof(float), reinterpret_cast<void *>(3 * sizeof(float)));
        glEnableVertexAttribArray(1);
        if (!menuProgram || !menuVao || !menuVbo || !glSucceeded("initializing menu presentation", shaderError))
            shaderError = shaderError.empty() ? "could not initialize menu presentation resources" : shaderError;
        if (!shaderError.empty()) { error=shaderError; return fail(); }
        return true;
    }

    bool ensureMenuCapture(uint32_t width, uint32_t height, std::string &error)
    {
        if (!width || !height)
        {
            error = "menu presentation requires a nonzero native extent";
            return false;
        }
        if (!ensureMenuProgram(error)) return false;
        if (menuFbo && menuWidth == width && menuHeight == height)
            return true;
        if (!menuFbo)
            glGenFramebuffers(1, &menuFbo);
        if (!menuColor)
            glGenTextures(1, &menuColor);
        if (!menuDepth)
            glGenRenderbuffers(1, &menuDepth);
        if (!menuFbo || !menuColor || !menuDepth)
        {
            error = "could not allocate menu presentation GL objects";
            destroyMenuGl();
            return false;
        }
        glBindFramebuffer(GL_FRAMEBUFFER, menuFbo);
        glBindTexture(GL_TEXTURE_2D, menuColor);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, menuColor, 0);
        glBindRenderbuffer(GL_RENDERBUFFER, menuDepth);
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, width, height);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, menuDepth);
        glDrawBuffer(GL_COLOR_ATTACHMENT0);
        GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
        if (status != GL_FRAMEBUFFER_COMPLETE || !glSucceeded("setting up menu presentation framebuffer", error))
        {
            if (status != GL_FRAMEBUFFER_COMPLETE)
                error = "menu presentation framebuffer incomplete: " + std::to_string(status);
            destroyMenuGl();
            return false;
        }
        menuWidth = width;
        menuHeight = height;
        return true;
    }

    bool mirrorMenuToNative(std::string &error)
    {
        GLState state;
        state.save();
        glDisable(GL_SCISSOR_TEST);
        glBindFramebuffer(GL_READ_FRAMEBUFFER, menuFbo);
        glReadBuffer(GL_COLOR_ATTACHMENT0);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, menuNativeState.drawFbo);
        glDrawBuffer(menuNativeState.drawBuffer);
        glBlitFramebuffer(0, 0, menuWidth, menuHeight, 0, 0, menuWidth, menuHeight, GL_COLOR_BUFFER_BIT, GL_NEAREST);
        bool good = glSucceeded("mirroring menu presentation", error);
        state.restore();
        restoreMenuTarget();
        return good;
    }

    bool createActions(std::string &error)
    {
        auto fail = [&](XrResult result, char const *where) { error = xrError(instance, result, where); return false; };
        auto path = [&](char const *name, XrPath &out) { return XR_SUCCEEDED(xrStringToPath(instance, name, &out)); };
        if (!path("/user/hand/left", handPaths[0]) || !path("/user/hand/right", handPaths[1]))
        {
            error = "OpenXR runtime rejected hand subaction paths";
            return false;
        }
        XrActionSetCreateInfo setInfo { XR_TYPE_ACTION_SET_CREATE_INFO };
        std::snprintf(setInfo.actionSetName, sizeof(setInfo.actionSetName), "eduke32_physical_input");
        std::snprintf(setInfo.localizedActionSetName, sizeof(setInfo.localizedActionSetName), "EDuke32 physical input");
        XrResult result = xrCreateActionSet(instance, &setInfo, &actionSet);
        if (XR_FAILED(result)) return fail(result, "xrCreateActionSet");
        auto create = [&](XrAction &action, XrActionType type, char const *name, char const *localized)
        {
            XrActionCreateInfo info { XR_TYPE_ACTION_CREATE_INFO };
            info.actionType = type;
            info.countSubactionPaths = handPaths.size();
            info.subactionPaths = handPaths.data();
            std::snprintf(info.actionName, sizeof(info.actionName), "%s", name);
            std::snprintf(info.localizedActionName, sizeof(info.localizedActionName), "%s", localized);
            result = xrCreateAction(actionSet, &info, &action);
            return XR_SUCCEEDED(result);
        };
        char const * const names[] = { "select", "grip", "primary", "secondary", "menu", "stickclick" };
        char const * const labels[] = { "Select", "Grip", "Primary", "Secondary", "Menu", "Stick click" };
        for (size_t i = 0; i < buttonActions.size(); ++i)
            if (!create(buttonActions[i], XR_ACTION_TYPE_BOOLEAN_INPUT, names[i], labels[i])) return fail(result, "xrCreateAction button");
        if (!create(stickAction, XR_ACTION_TYPE_VECTOR2F_INPUT, "stick", "Stick")) return fail(result, "xrCreateAction stick");
        if (!create(gripPoseAction, XR_ACTION_TYPE_POSE_INPUT, "grip_pose", "Grip pose")) return fail(result, "xrCreateAction grip pose");
        if (!create(aimPoseAction, XR_ACTION_TYPE_POSE_INPUT, "aim_pose", "Aim pose")) return fail(result, "xrCreateAction aim pose");

        struct Binding { XrAction action; char const *path; };
        auto suggest = [&](char const *profile, std::initializer_list<Binding> bindings)
        {
            XrPath profilePath = XR_NULL_PATH;
            result = xrStringToPath(instance, profile, &profilePath);
            if (XR_FAILED(result)) return false;
            std::vector<XrActionSuggestedBinding> suggested;
            suggested.reserve(bindings.size());
            for (Binding const &binding : bindings)
            {
                XrPath bindingPath = XR_NULL_PATH;
                result = xrStringToPath(instance, binding.path, &bindingPath);
                if (XR_FAILED(result)) return false;
                suggested.push_back({ binding.action, bindingPath });
            }
            XrInteractionProfileSuggestedBinding info { XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING };
            info.interactionProfile = profilePath;
            info.countSuggestedBindings = suggested.size();
            info.suggestedBindings = suggested.data();
            result = xrSuggestInteractionProfileBindings(instance, &info);
            return XR_SUCCEEDED(result);
        };
        auto const select = buttonActions[0], grip = buttonActions[1], primary = buttonActions[2], secondary = buttonActions[3], menu = buttonActions[4], click = buttonActions[5];
        if (!suggest("/interaction_profiles/khr/simple_controller", {
                { select, "/user/hand/left/input/select/click" }, { select, "/user/hand/right/input/select/click" },
                { menu, "/user/hand/left/input/menu/click" }, { menu, "/user/hand/right/input/menu/click" },
                { gripPoseAction, "/user/hand/left/input/grip/pose" }, { gripPoseAction, "/user/hand/right/input/grip/pose" },
                { aimPoseAction, "/user/hand/left/input/aim/pose" }, { aimPoseAction, "/user/hand/right/input/aim/pose" }})) return fail(result, "xrSuggestInteractionProfileBindings simple");
        if (!suggest("/interaction_profiles/oculus/touch_controller", {
                { select, "/user/hand/left/input/trigger/value" }, { select, "/user/hand/right/input/trigger/value" },
                { grip, "/user/hand/left/input/squeeze/value" }, { grip, "/user/hand/right/input/squeeze/value" },
                { primary, "/user/hand/left/input/x/click" }, { secondary, "/user/hand/left/input/y/click" },
                { primary, "/user/hand/right/input/a/click" }, { secondary, "/user/hand/right/input/b/click" },
                { menu, "/user/hand/left/input/menu/click" },
                { stickAction, "/user/hand/left/input/thumbstick" }, { stickAction, "/user/hand/right/input/thumbstick" },
                { click, "/user/hand/left/input/thumbstick/click" }, { click, "/user/hand/right/input/thumbstick/click" },
                { gripPoseAction, "/user/hand/left/input/grip/pose" }, { gripPoseAction, "/user/hand/right/input/grip/pose" },
                { aimPoseAction, "/user/hand/left/input/aim/pose" }, { aimPoseAction, "/user/hand/right/input/aim/pose" }})) return fail(result, "xrSuggestInteractionProfileBindings touch");
        if (!suggest("/interaction_profiles/valve/index_controller", {
                { select, "/user/hand/left/input/trigger/value" }, { select, "/user/hand/right/input/trigger/value" },
                { grip, "/user/hand/left/input/squeeze/value" }, { grip, "/user/hand/right/input/squeeze/value" },
                { primary, "/user/hand/left/input/a/click" }, { secondary, "/user/hand/left/input/b/click" },
                { primary, "/user/hand/right/input/a/click" }, { secondary, "/user/hand/right/input/b/click" },
                { menu, "/user/hand/left/input/thumbstick/click" }, { click, "/user/hand/right/input/thumbstick/click" },
                { stickAction, "/user/hand/left/input/thumbstick" }, { stickAction, "/user/hand/right/input/thumbstick" },
                { gripPoseAction, "/user/hand/left/input/grip/pose" }, { gripPoseAction, "/user/hand/right/input/grip/pose" },
                { aimPoseAction, "/user/hand/left/input/aim/pose" }, { aimPoseAction, "/user/hand/right/input/aim/pose" }})) return fail(result, "xrSuggestInteractionProfileBindings index");
        if (!suggest("/interaction_profiles/microsoft/motion_controller", {
                { select, "/user/hand/left/input/trigger/value" }, { select, "/user/hand/right/input/trigger/value" },
                { grip, "/user/hand/left/input/squeeze/click" }, { grip, "/user/hand/right/input/squeeze/click" },
                { menu, "/user/hand/left/input/menu/click" }, { menu, "/user/hand/right/input/menu/click" },
                { stickAction, "/user/hand/left/input/thumbstick" }, { stickAction, "/user/hand/right/input/thumbstick" },
                { click, "/user/hand/left/input/thumbstick/click" }, { click, "/user/hand/right/input/thumbstick/click" },
                { primary, "/user/hand/right/input/thumbstick/click" }, { primary, "/user/hand/left/input/trackpad/click" },
                { secondary, "/user/hand/right/input/trackpad/click" }, { secondary, "/user/hand/left/input/thumbstick/click" },
                { gripPoseAction, "/user/hand/left/input/grip/pose" }, { gripPoseAction, "/user/hand/right/input/grip/pose" },
                { aimPoseAction, "/user/hand/left/input/aim/pose" }, { aimPoseAction, "/user/hand/right/input/aim/pose" }})) return fail(result, "xrSuggestInteractionProfileBindings motion");

        for (size_t hand = 0; hand < handPaths.size(); ++hand)
        {
            XrActionSpaceCreateInfo info { XR_TYPE_ACTION_SPACE_CREATE_INFO };
            info.action = gripPoseAction;
            info.subactionPath = handPaths[hand];
            info.poseInActionSpace.orientation.w = 1.f;
            result = xrCreateActionSpace(session, &info, &gripSpaces[hand]);
            if (XR_FAILED(result)) return fail(result, "xrCreateActionSpace grip");
            info.action = aimPoseAction;
            result = xrCreateActionSpace(session, &info, &aimSpaces[hand]);
            if (XR_FAILED(result)) return fail(result, "xrCreateActionSpace aim");
        }
        XrSessionActionSetsAttachInfo attach { XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO };
        attach.countActionSets = 1;
        attach.actionSets = &actionSet;
        result = xrAttachSessionActionSets(session, &attach);
        return XR_SUCCEEDED(result) ? true : fail(result, "xrAttachSessionActionSets");
    }

    void destroyGl()
    {
        destroyMenuGl();
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
        for (XrSpace &actionSpace : gripSpaces)
            if (actionSpace != XR_NULL_HANDLE) xrDestroySpace(actionSpace);
        for (XrSpace &actionSpace : aimSpaces)
            if (actionSpace != XR_NULL_HANDLE) xrDestroySpace(actionSpace);
        if (space != XR_NULL_HANDLE)
            xrDestroySpace(space);
        if (viewSpace != XR_NULL_HANDLE)
            xrDestroySpace(viewSpace);
        if (session != XR_NULL_HANDLE)
            xrDestroySession(session);
        if (actionSet != XR_NULL_HANDLE)
            xrDestroyActionSet(actionSet);
        if (instance != XR_NULL_HANDLE)
            xrDestroyInstance(instance);
        instance = XR_NULL_HANDLE;
        system   = XR_NULL_SYSTEM_ID;
        session  = XR_NULL_HANDLE;
        space    = XR_NULL_HANDLE;
        viewSpace = XR_NULL_HANDLE;
        actionSet = XR_NULL_HANDLE;
        buttonActions = {};
        stickAction = gripPoseAction = aimPoseAction = XR_NULL_HANDLE;
        handPaths = {};
        gripSpaces = {};
        aimSpaces = {};
        color    = XR_NULL_HANDLE;
        colorImages.clear();
        width = height = 0;
        multiview      = nullptr;
        running = exiting = false;
        sessionState = XR_SESSION_STATE_UNKNOWN;
        frameBegun = imageAcquired = imageReady = false;
        clearMenuPresentation();
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
    if (!m_impl->createActions(error))
    {
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
    ++m_impl->actionGeneration;
    bool hasGlResources = m_impl->fbo || m_impl->depth || m_impl->program || m_impl->vao || m_impl->vbo || m_impl->menuFbo || m_impl->menuColor
                       || m_impl->menuDepth || m_impl->menuProgram || m_impl->menuVao || m_impl->menuVbo;
    bool hasXrResources
    = m_impl->instance != XR_NULL_HANDLE || m_impl->session != XR_NULL_HANDLE || m_impl->space != XR_NULL_HANDLE || m_impl->viewSpace != XR_NULL_HANDLE
      || m_impl->color != XR_NULL_HANDLE;
    bool    hasContext = hasGlResources && SDL_GL_GetCurrentContext() != nullptr;
    GLState state;
    if (hasContext && m_impl->menuActive)
    {
        m_impl->restoreMenuTarget();
        m_impl->clearMenuPresentation();
    }
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
            m_impl->sessionState = changed->state;
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
    // Input uses this timestamp even when the frame will not render or view
    // tracking is temporarily unavailable.
    frame.predictedDisplayTime = frameState.predictedDisplayTime;
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

bool Runtime::beginMenuPresentation(uint32_t width, uint32_t height, uint64_t &owner, std::string &error)
{
    owner = 0;
    error.clear();
    if (!m_impl || !m_impl->frameBegun || !m_impl->imageReady)
    {
        error = "menu presentation requires a ready OpenXR frame";
        return false;
    }
    if (m_impl->menuActive)
    {
        error = "a menu presentation is already active";
        return false;
    }
    GLState state;
    state.save();
    if (!m_impl->ensureMenuCapture(width, height, error))
    {
        state.restore();
        return false;
    }
    m_impl->menuNativeState = { state.readFbo, state.drawFbo, state.readBuffer, state.drawBuffer };
    state.restore();
    glBindFramebuffer(GL_READ_FRAMEBUFFER, m_impl->menuFbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, m_impl->menuFbo);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    glDrawBuffer(GL_COLOR_ATTACHMENT0);

    glDisable(GL_SCISSOR_TEST);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDepthMask(GL_TRUE);
    glStencilMaskSeparate(GL_FRONT, ~0u);
    glStencilMaskSeparate(GL_BACK, ~0u);
    glClearColor(0, 0, 0, 1);
    glClearDepth(1);
    glClearStencil(0);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
    glClearColor(state.clearColor[0], state.clearColor[1], state.clearColor[2], state.clearColor[3]);
    glClearDepth(state.clearDepth);
    glClearStencil(state.clearStencil);
    glColorMask(state.colorMask[0], state.colorMask[1], state.colorMask[2], state.colorMask[3]);
    glDepthMask(state.depthMask);
    glStencilMaskSeparate(GL_FRONT, state.stencilWriteMask);
    glStencilMaskSeparate(GL_BACK, state.stencilBackWriteMask);
    if (state.scissorTest)
        glEnable(GL_SCISSOR_TEST);
    if (!glSucceeded("clearing menu presentation", error))
    {
        m_impl->restoreMenuTarget();
        m_impl->clearMenuPresentation();
        return false;
    }
    owner = ++m_impl->nextMenuOwner;
    if (!owner)
        owner = ++m_impl->nextMenuOwner;
    m_impl->menuOwner = owner;
    m_impl->menuActive = true;
    m_impl->menuArmed = false;
    return true;
}

bool Runtime::armMenuPresentation(uint64_t owner, uint32_t width, uint32_t height)
{
    if (!m_impl || !m_impl->menuActive || !m_impl->frameBegun || !m_impl->imageReady || !owner || owner != m_impl->menuOwner
        || width != m_impl->menuWidth || height != m_impl->menuHeight)
        return false;
    m_impl->menuArmed = true;
    return true;
}

bool Runtime::menuPresentationActive() const
{ return m_impl && m_impl->menuActive; }

bool Runtime::menuPresentationArmed() const
{ return m_impl && m_impl->menuActive && m_impl->menuArmed; }

bool Runtime::cancelMenuPresentation(std::string &error, bool mirror)
{
    error.clear();
    if (!m_impl || !m_impl->menuActive)
    {
        error = "no menu presentation is active";
        return false;
    }
    bool good = true;
    if (mirror)
        good = m_impl->mirrorMenuToNative(error);
    else
        m_impl->restoreMenuTarget();
    m_impl->clearMenuPresentation();
    std::string finishError;
    if (m_impl->frameBegun && !finishFrame(false, finishError))
    {
        if (error.empty())
            error = finishError;
        good = false;
    }
    return good;
}

bool Runtime::completeMenuPresentation(std::string &error, char const *capturePrefix)
{
    error.clear();
    if (!m_impl || !m_impl->menuActive)
    {
        error = "no menu presentation is active";
        return false;
    }
    if (!m_impl->menuArmed)
        return cancelMenuPresentation(error, true);

    XrSpaceLocation head { XR_TYPE_SPACE_LOCATION };
    XrResult result = xrLocateSpace(m_impl->viewSpace, m_impl->space, m_impl->frameState.predictedDisplayTime, &head);
    if (XR_FAILED(result))
    {
        error=xrError(m_impl->instance,result,"xrLocateSpace view");
        std::string cleanup;
        cancelMenuPresentation(cleanup,true);
        return false;
    }
    static bool injectedPoseLoss;
    if (auto test=std::getenv("EDUKE32_XR_TEST_MENU_POSE"))
        if (!injectedPoseLoss && !std::strcmp(test,"1"))
        {
            injectedPoseLoss=true;
            head.locationFlags=0;
            std::fprintf(stderr,"OpenXR menu pose test: injected temporary invalidity.\n");
        }
    if ((head.locationFlags & (XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT))
        != (XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT))
        return cancelMenuPresentation(error,true);

    GLState state;
    state.save();
    bool rendered = bindMultiview(error);
    if (rendered)
    {
        glViewport(0, 0, m_impl->width, m_impl->height);
        glDisable(GL_SCISSOR_TEST);
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glDisable(GL_BLEND);
        glDisable(GL_CULL_FACE);
        glDisable(GL_ALPHA_TEST);
        glDisable(GL_STENCIL_TEST);
        glDisable(GL_RASTERIZER_DISCARD);
        glDisable(GL_FRAMEBUFFER_SRGB);
        glDisable(GL_DITHER);
        glClearColor(0, 0, 0, 1);
        glClearDepth(1);
        glClearStencil(0);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        glDepthMask(GL_FALSE);
        float headMatrix[16], translate[16] = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -1.5f, 1 };
        float scale[16] = { .9f, 0, 0, 0, 0, .9f * float(m_impl->menuHeight) / m_impl->menuWidth, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };
        float world[16], model[16], matrices[kViewCount][16];
        poseMatrix(head.pose, headMatrix);
        multiply(world, headMatrix, translate);
        multiply(model, world, scale);
        for (uint32_t i = 0; i < kViewCount; ++i)
        {
            float projection[16], view[16], viewProjection[16];
            projectionMatrix(m_impl->views[i].fov, projection);
            viewMatrix(m_impl->views[i].pose, view);
            multiply(viewProjection, projection, view);
            multiply(matrices[i], viewProjection, model);
        }
        glUseProgram(m_impl->menuProgram);
        glUniformMatrix4fv(glGetUniformLocation(m_impl->menuProgram, "uViewProj[0]"), kViewCount, GL_FALSE, &matrices[0][0]);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, m_impl->menuColor);
        glBindSampler(0, 0);
        glUniform1i(glGetUniformLocation(m_impl->menuProgram, "uTexture"), 0);
        glBindVertexArray(m_impl->menuVao);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        rendered = glSucceeded("drawing menu presentation", error);
    }
    state.restore();
    if (!rendered)
    {
        std::string cleanup;
        cancelMenuPresentation(cleanup, true);
        return false;
    }

    bool captureOk = true;
    if (capturePrefix)
    {
        std::string path = std::string(capturePrefix) + "-ui.ppm";
        captureOk = writeTexturePpm(m_impl->menuColor, m_impl->menuWidth, m_impl->menuHeight, path.c_str(), error);
        if (captureOk)
            captureOk = captureFrame(capturePrefix, false, error);
    }
    std::string mirrorError;
    bool mirrored = m_impl->mirrorMenuToNative(mirrorError);
    if (capturePrefix && captureOk && mirrored)
    {
        std::string path=std::string(capturePrefix)+"-desktop.ppm";
        captureOk=captureFramebuffer(path.c_str(),m_impl->menuWidth,m_impl->menuHeight,error);
    }
    m_impl->clearMenuPresentation();
    std::string finishError;
    bool submitted = finishFrame(mirrored, finishError);
    if (!captureOk || !mirrored || !submitted)
    {
        if (error.empty())
            error = !mirrored ? mirrorError : finishError;
        return false;
    }
    return true;
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
    if (m_impl->menuActive)
    {
        // An early caller must not retain the private target or submit an
        // incomplete logical presentation frame.
        m_impl->restoreMenuTarget();
        m_impl->clearMenuPresentation();
        submit = false;
    }
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

bool Runtime::readInput(ActionInput &out, XrTime const atTime, std::string &error)
{
    out = {};
    error.clear();
    if (!m_impl || !m_impl->running)
        return true;
    if (m_impl->sessionState != XR_SESSION_STATE_FOCUSED)
        return true;
    if (m_impl->actionSet == XR_NULL_HANDLE)
    {
        error = "OpenXR input action set is unavailable";
        return false;
    }
    XrActiveActionSet activeSet {};
    activeSet.actionSet = m_impl->actionSet;
    XrActionsSyncInfo sync { XR_TYPE_ACTIONS_SYNC_INFO };
    sync.countActiveActionSets = 1;
    sync.activeActionSets = &activeSet;
    XrResult result = xrSyncActions(m_impl->session, &sync);
    if (result == XR_SESSION_NOT_FOCUSED)
        return true;
    if (XR_FAILED(result))
    {
        error = xrError(m_impl->instance, result, "xrSyncActions");
        return false;
    }

    ActionInput sample {};
    sample.focused = true;
    auto boolean = [&](XrAction action, XrPath hand, XrActionStateBoolean &state)
    {
        XrActionStateGetInfo info { XR_TYPE_ACTION_STATE_GET_INFO };
        info.action = action;
        info.subactionPath = hand;
        state = { XR_TYPE_ACTION_STATE_BOOLEAN };
        result = xrGetActionStateBoolean(m_impl->session, &info, &state);
        return XR_SUCCEEDED(result);
    };
    auto neutralIfUnfocused = [&]()
    {
        if (result == XR_SESSION_NOT_FOCUSED)
        {
            out = {};
            return true;
        }
        return false;
    };
    for (size_t hand = 0; hand < m_impl->handPaths.size(); ++hand)
    {
        HandInput &target = sample.hands[hand];
        for (size_t button = 0; button < m_impl->buttonActions.size(); ++button)
        {
            XrActionStateBoolean state { XR_TYPE_ACTION_STATE_BOOLEAN };
            if (!boolean(m_impl->buttonActions[button], m_impl->handPaths[hand], state))
            {
                if (neutralIfUnfocused()) return true;
                error = xrError(m_impl->instance, result, "xrGetActionStateBoolean");
                return false;
            }
            uint32_t const bit = 1u << button;
            if (state.isActive)
            {
                target.activeButtons |= bit;
                if (state.currentState) target.buttons |= bit;
            }
        }
        XrActionStateGetInfo stickInfo { XR_TYPE_ACTION_STATE_GET_INFO };
        stickInfo.action = m_impl->stickAction;
        stickInfo.subactionPath = m_impl->handPaths[hand];
        XrActionStateVector2f stick { XR_TYPE_ACTION_STATE_VECTOR2F };
        result = xrGetActionStateVector2f(m_impl->session, &stickInfo, &stick);
        if (XR_FAILED(result))
        {
            if (neutralIfUnfocused()) return true;
            error = xrError(m_impl->instance, result, "xrGetActionStateVector2f");
            return false;
        }
        if (stick.isActive)
        {
            target.stickActive = true;
            target.stick = stick.currentState;
        }
        auto pose = [&](XrAction action, XrSpace actionSpace, XrPosef &value, bool &valid)
        {
            XrActionStateGetInfo info { XR_TYPE_ACTION_STATE_GET_INFO };
            info.action = action;
            info.subactionPath = m_impl->handPaths[hand];
            XrActionStatePose state { XR_TYPE_ACTION_STATE_POSE };
            result = xrGetActionStatePose(m_impl->session, &info, &state);
            if (XR_FAILED(result)) return false;
            if (!state.isActive || !atTime) return true;
            XrSpaceLocation location { XR_TYPE_SPACE_LOCATION };
            result = xrLocateSpace(actionSpace, m_impl->space, atTime, &location);
            if (XR_FAILED(result)) return false;
            if ((location.locationFlags & (XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT))
                == (XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT))
            {
                value = location.pose;
                valid = true;
            }
            return true;
        };
        if (!pose(m_impl->gripPoseAction, m_impl->gripSpaces[hand], target.gripPose, target.gripValid))
        {
            if (neutralIfUnfocused()) return true;
            error = xrError(m_impl->instance, result, "OpenXR grip pose query");
            return false;
        }
        if (!pose(m_impl->aimPoseAction, m_impl->aimSpaces[hand], target.aimPose, target.aimValid))
        {
            if (neutralIfUnfocused()) return true;
            error = xrError(m_impl->instance, result, "OpenXR aim pose query");
            return false;
        }
    }
    out = sample;
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

uint64_t Runtime::generation() const
{ return m_impl ? m_impl->actionGeneration : 0; }
}  // namespace eduke_xr
