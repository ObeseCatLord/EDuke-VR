// SPDX-License-Identifier: GPL-2.0-only
// Test-only OpenXR API layer for EDUKE32's LOCAL reference-space regression.
//
// Build a shared object, substitute its absolute path into
// reference_space_layer.json.in, then use both this layer and core validation:
//   XR_API_LAYER_PATH=<manifest-dir>
//   XR_ENABLE_API_LAYERS=XR_APILAYER_EDUKE32_reference_space_test:XR_APILAYER_LUNARG_core_validation
//
// EDUKE32_TEST_REFERENCE_MARKER names a plaintext marker, read once after an
// instance, session, and successful xrWaitFrame are known. Its one line is:
//   valid tx ty tz yawRadians [delayMs]
// valid is 0 or 1. delayMs defaults to 300 and is clamped to 0..2000. tx/ty/tz
// and yaw describe newOriginInPreviousSpace. A valid=0 event deliberately still
// changes this layer's synthetic basis, while the event's pose remains undefined
// to the application under the OpenXR specification.

#define XR_NO_PROTOTYPES
#include <openxr/openxr.h>
#include <openxr/openxr_loader_negotiation.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_set>
#include <vector>

namespace {

constexpr const char kLayerName[] = "XR_APILAYER_EDUKE32_reference_space_test";
constexpr int64_t kDefaultDelayMs = 300;
constexpr int64_t kMaxDelayMs = 2000;

struct Marker
{
    XrBool32 poseValid;
    XrPosef newOriginInPreviousSpace;
    int64_t delayMs;
};

struct LayerState
{
    std::mutex mutex;
    PFN_xrGetInstanceProcAddr nextGetInstanceProcAddr = nullptr;
    PFN_xrCreateApiLayerInstance nextCreateApiLayerInstance = nullptr;
    PFN_xrDestroyInstance nextDestroyInstance = nullptr;
    PFN_xrCreateSession nextCreateSession = nullptr;
    PFN_xrDestroySession nextDestroySession = nullptr;
    PFN_xrCreateReferenceSpace nextCreateReferenceSpace = nullptr;
    PFN_xrDestroySpace nextDestroySpace = nullptr;
    PFN_xrPollEvent nextPollEvent = nullptr;
    PFN_xrWaitFrame nextWaitFrame = nullptr;
    PFN_xrLocateViews nextLocateViews = nullptr;
    PFN_xrLocateSpace nextLocateSpace = nullptr;
    PFN_xrEndFrame nextEndFrame = nullptr;
    XrInstance instance = XR_NULL_HANDLE;
    XrSession session = XR_NULL_HANDLE;
    XrTime lastPredictedDisplayTime = 0;
    bool hasPredictedDisplayTime = false;
    bool markerConsumed = false;
    bool changeScheduled = false;
    XrTime changeTime = 0;
    Marker marker{};
    std::unordered_set<XrSpace> localSpaces;
};

LayerState g_state;

template <typename T>
T nextProc(XrInstance instance, const char* name)
{
    PFN_xrVoidFunction function = nullptr;
    if (g_state.nextGetInstanceProcAddr == nullptr ||
        XR_FAILED(g_state.nextGetInstanceProcAddr(instance, name, &function)))
        return nullptr;
    return reinterpret_cast<T>(function);
}

void loadNextFunctions(XrInstance instance)
{
    g_state.nextDestroyInstance = nextProc<PFN_xrDestroyInstance>(instance, "xrDestroyInstance");
    g_state.nextCreateSession = nextProc<PFN_xrCreateSession>(instance, "xrCreateSession");
    g_state.nextDestroySession = nextProc<PFN_xrDestroySession>(instance, "xrDestroySession");
    g_state.nextCreateReferenceSpace = nextProc<PFN_xrCreateReferenceSpace>(instance, "xrCreateReferenceSpace");
    g_state.nextDestroySpace = nextProc<PFN_xrDestroySpace>(instance, "xrDestroySpace");
    g_state.nextPollEvent = nextProc<PFN_xrPollEvent>(instance, "xrPollEvent");
    g_state.nextWaitFrame = nextProc<PFN_xrWaitFrame>(instance, "xrWaitFrame");
    g_state.nextLocateViews = nextProc<PFN_xrLocateViews>(instance, "xrLocateViews");
    g_state.nextLocateSpace = nextProc<PFN_xrLocateSpace>(instance, "xrLocateSpace");
    g_state.nextEndFrame = nextProc<PFN_xrEndFrame>(instance, "xrEndFrame");
}

bool parseMarker(const char* path, Marker* marker)
{
    std::ifstream input(path);
    std::string line;
    if (!input || !std::getline(input, line) || line.size() > 256)
        return false;

    std::istringstream fields(line);
    int valid = -1;
    double tx = 0.0, ty = 0.0, tz = 0.0, yaw = 0.0;
    int64_t delayMs = kDefaultDelayMs;
    std::string surplus;
    if (!(fields >> valid >> tx >> ty >> tz >> yaw) ||
        (valid != 0 && valid != 1) || !std::isfinite(tx) || !std::isfinite(ty) ||
        !std::isfinite(tz) || !std::isfinite(yaw))
        return false;
    if (fields >> surplus)
    {
        std::istringstream delayField(surplus);
        if (!(delayField >> delayMs) || (delayField >> surplus) || (fields >> surplus))
            return false;
    }

    const float markerTx = static_cast<float>(tx);
    const float markerTy = static_cast<float>(ty);
    const float markerTz = static_cast<float>(tz);
    if (!std::isfinite(markerTx) || !std::isfinite(markerTy) || !std::isfinite(markerTz))
        return false;
    marker->poseValid = valid ? XR_TRUE : XR_FALSE;
    marker->newOriginInPreviousSpace.position = {
        markerTx, markerTy, markerTz};
    marker->newOriginInPreviousSpace.orientation = {
        0.0f, static_cast<float>(std::sin(yaw * 0.5)), 0.0f,
        static_cast<float>(std::cos(yaw * 0.5))};
    marker->delayMs = std::clamp(delayMs, int64_t{0}, kMaxDelayMs);
    return true;
}

XrQuaternionf conjugate(const XrQuaternionf& quaternion)
{
    return {-quaternion.x, -quaternion.y, -quaternion.z, quaternion.w};
}

XrQuaternionf multiply(const XrQuaternionf& lhs, const XrQuaternionf& rhs)
{
    return {
        lhs.w * rhs.x + lhs.x * rhs.w + lhs.y * rhs.z - lhs.z * rhs.y,
        lhs.w * rhs.y - lhs.x * rhs.z + lhs.y * rhs.w + lhs.z * rhs.x,
        lhs.w * rhs.z + lhs.x * rhs.y - lhs.y * rhs.x + lhs.z * rhs.w,
        lhs.w * rhs.w - lhs.x * rhs.x - lhs.y * rhs.y - lhs.z * rhs.z};
}

XrVector3f rotate(const XrQuaternionf& quaternion, const XrVector3f& vector)
{
    const XrQuaternionf vectorQuaternion{vector.x, vector.y, vector.z, 0.0f};
    const XrQuaternionf result = multiply(multiply(quaternion, vectorQuaternion), conjugate(quaternion));
    return {result.x, result.y, result.z};
}

void transformOldToNew(XrPosef* pose, const XrPosef& newOriginInPreviousSpace)
{
    const XrQuaternionf inverse = conjugate(newOriginInPreviousSpace.orientation);
    const XrVector3f offset{
        pose->position.x - newOriginInPreviousSpace.position.x,
        pose->position.y - newOriginInPreviousSpace.position.y,
        pose->position.z - newOriginInPreviousSpace.position.z};
    pose->position = rotate(inverse, offset);
    pose->orientation = multiply(inverse, pose->orientation);
}

void transformNewToOld(XrPosef* pose, const XrPosef& newOriginInPreviousSpace)
{
    const XrVector3f rotated = rotate(newOriginInPreviousSpace.orientation, pose->position);
    pose->position = {
        rotated.x + newOriginInPreviousSpace.position.x,
        rotated.y + newOriginInPreviousSpace.position.y,
        rotated.z + newOriginInPreviousSpace.position.z};
    pose->orientation = multiply(newOriginInPreviousSpace.orientation, pose->orientation);
}

bool activeChangeAt(XrTime time, XrPosef* markerPose)
{
    std::lock_guard<std::mutex> lock(g_state.mutex);
    if (!g_state.changeScheduled || time < g_state.changeTime)
        return false;
    *markerPose = g_state.marker.newOriginInPreviousSpace;
    return true;
}

bool isLocalSpace(XrSpace space)
{
    std::lock_guard<std::mutex> lock(g_state.mutex);
    return g_state.localSpaces.find(space) != g_state.localSpaces.end();
}

void clearSessionState(XrSession session)
{
    std::lock_guard<std::mutex> lock(g_state.mutex);
    if (g_state.session == session)
    {
        g_state.session = XR_NULL_HANDLE;
        g_state.hasPredictedDisplayTime = false;
        g_state.changeScheduled = false;
        g_state.localSpaces.clear();
    }
}

void clearInstanceState()
{
    g_state.nextGetInstanceProcAddr = nullptr;
    g_state.nextCreateApiLayerInstance = nullptr;
    g_state.nextDestroyInstance = nullptr;
    g_state.nextCreateSession = nullptr;
    g_state.nextDestroySession = nullptr;
    g_state.nextCreateReferenceSpace = nullptr;
    g_state.nextDestroySpace = nullptr;
    g_state.nextPollEvent = nullptr;
    g_state.nextWaitFrame = nullptr;
    g_state.nextLocateViews = nullptr;
    g_state.nextLocateSpace = nullptr;
    g_state.nextEndFrame = nullptr;
    g_state.instance = XR_NULL_HANDLE;
    g_state.session = XR_NULL_HANDLE;
    g_state.lastPredictedDisplayTime = 0;
    g_state.hasPredictedDisplayTime = false;
    g_state.markerConsumed = false;
    g_state.changeScheduled = false;
    g_state.changeTime = 0;
    g_state.marker = {};
    g_state.localSpaces.clear();
}

XrResult XRAPI_CALL layerDestroyInstance(XrInstance instance)
{
    PFN_xrDestroyInstance next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextDestroyInstance;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(instance);
    if (XR_SUCCEEDED(result))
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        if (g_state.instance == instance)
        {
            clearInstanceState();
        }
    }
    return result;
}

XrResult XRAPI_CALL layerCreateSession(
    XrInstance instance, const XrSessionCreateInfo* createInfo, XrSession* session)
{
    PFN_xrCreateSession next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextCreateSession;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(instance, createInfo, session);
    if (XR_SUCCEEDED(result) && session != nullptr)
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        if (g_state.instance == instance && g_state.session == XR_NULL_HANDLE)
            g_state.session = *session;
    }
    return result;
}

XrResult XRAPI_CALL layerDestroySession(XrSession session)
{
    PFN_xrDestroySession next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextDestroySession;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(session);
    if (XR_SUCCEEDED(result))
        clearSessionState(session);
    return result;
}

XrResult XRAPI_CALL layerCreateReferenceSpace(
    XrSession session, const XrReferenceSpaceCreateInfo* createInfo, XrSpace* space)
{
    PFN_xrCreateReferenceSpace next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextCreateReferenceSpace;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(session, createInfo, space);
    if (XR_SUCCEEDED(result) && createInfo != nullptr && space != nullptr &&
        createInfo->referenceSpaceType == XR_REFERENCE_SPACE_TYPE_LOCAL)
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        if (g_state.session == session)
            g_state.localSpaces.insert(*space);
    }
    return result;
}

XrResult XRAPI_CALL layerDestroySpace(XrSpace space)
{
    PFN_xrDestroySpace next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextDestroySpace;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(space);
    if (XR_SUCCEEDED(result))
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        g_state.localSpaces.erase(space);
    }
    return result;
}

XrResult XRAPI_CALL layerWaitFrame(
    XrSession session, const XrFrameWaitInfo* frameWaitInfo, XrFrameState* frameState)
{
    PFN_xrWaitFrame next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextWaitFrame;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(session, frameWaitInfo, frameState);
    if (XR_SUCCEEDED(result) && frameState != nullptr)
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        if (g_state.session == session)
        {
            g_state.lastPredictedDisplayTime = frameState->predictedDisplayTime;
            g_state.hasPredictedDisplayTime = true;
        }
    }
    return result;
}

XrResult XRAPI_CALL layerPollEvent(XrInstance instance, XrEventDataBuffer* eventData)
{
    PFN_xrPollEvent next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextPollEvent;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(instance, eventData);
    if (result != XR_EVENT_UNAVAILABLE || eventData == nullptr)
        return result;

    const char* markerPath = std::getenv("EDUKE32_TEST_REFERENCE_MARKER");
    Marker marker{};
    if (markerPath == nullptr || markerPath[0] == '\0' || !parseMarker(markerPath, &marker))
        return result;

    XrTime eventTime = 0;
    XrTime changeTime = 0;
    XrSession session = XR_NULL_HANDLE;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        if (g_state.markerConsumed || g_state.instance != instance ||
            g_state.session == XR_NULL_HANDLE || !g_state.hasPredictedDisplayTime)
            return result;
        const XrTime delay = marker.delayMs * 1000000;
        if (g_state.lastPredictedDisplayTime > std::numeric_limits<XrTime>::max() - delay)
            return result;
        g_state.markerConsumed = true;
        g_state.marker = marker;
        g_state.changeTime = g_state.lastPredictedDisplayTime + delay;
        g_state.changeScheduled = true;
        eventTime = g_state.lastPredictedDisplayTime;
        changeTime = g_state.changeTime;
        session = g_state.session;
    }

    std::memset(eventData, 0, sizeof(*eventData));
    XrEventDataReferenceSpaceChangePending* event =
        reinterpret_cast<XrEventDataReferenceSpaceChangePending*>(eventData);
    event->type = XR_TYPE_EVENT_DATA_REFERENCE_SPACE_CHANGE_PENDING;
    event->next = nullptr;
    event->session = session;
    event->referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
    event->changeTime = changeTime;
    event->poseValid = marker.poseValid;
    event->poseInPreviousSpace = marker.newOriginInPreviousSpace;
    std::fprintf(stderr,
                 "reference-space-layer: marker accepted valid=%u eventTime=%lld effective=%lld applied=scheduled\n",
                 static_cast<unsigned>(marker.poseValid),
                 static_cast<long long>(eventTime),
                 static_cast<long long>(changeTime));
    return XR_SUCCESS;
}

XrResult XRAPI_CALL layerLocateViews(
    XrSession session, const XrViewLocateInfo* viewLocateInfo, XrViewState* viewState,
    uint32_t viewCapacityInput, uint32_t* viewCountOutput, XrView* views)
{
    PFN_xrLocateViews next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextLocateViews;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(session, viewLocateInfo, viewState, viewCapacityInput, viewCountOutput, views);
    if (XR_SUCCEEDED(result) && viewLocateInfo != nullptr && views != nullptr &&
        isLocalSpace(viewLocateInfo->space))
    {
        XrPosef markerPose{};
        if (activeChangeAt(viewLocateInfo->displayTime, &markerPose))
        {
            const uint32_t count = viewCountOutput == nullptr ? viewCapacityInput :
                std::min(viewCapacityInput, *viewCountOutput);
            for (uint32_t index = 0; index < count; ++index)
                transformOldToNew(&views[index].pose, markerPose);
        }
    }
    return result;
}

XrResult XRAPI_CALL layerLocateSpace(
    XrSpace space, XrSpace baseSpace, XrTime time, XrSpaceLocation* location)
{
    PFN_xrLocateSpace next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextLocateSpace;
    }
    if (next == nullptr)
        return XR_ERROR_FUNCTION_UNSUPPORTED;
    const XrResult result = next(space, baseSpace, time, location);
    if (XR_SUCCEEDED(result) && location != nullptr && space != baseSpace && isLocalSpace(baseSpace) &&
        !isLocalSpace(space))
    {
        XrPosef markerPose{};
        if (activeChangeAt(time, &markerPose))
            transformOldToNew(&location->pose, markerPose);
    }
    return result;
}

XrResult XRAPI_CALL layerEndFrame(XrSession session, const XrFrameEndInfo* frameEndInfo)
{
    PFN_xrEndFrame next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextEndFrame;
    }
    if (next == nullptr || frameEndInfo == nullptr ||
        (frameEndInfo->layerCount != 0 && frameEndInfo->layers == nullptr))
        return next == nullptr ? XR_ERROR_FUNCTION_UNSUPPORTED : next(session, frameEndInfo);

    XrPosef markerPose{};
    if (!activeChangeAt(frameEndInfo->displayTime, &markerPose))
        return next(session, frameEndInfo);

    struct ProjectionCopy
    {
        XrCompositionLayerProjection layer{};
        std::vector<XrCompositionLayerProjectionView> views;
    };
    std::vector<ProjectionCopy> copies;
    std::vector<const XrCompositionLayerBaseHeader*> layers;
    copies.reserve(frameEndInfo->layerCount);
    layers.reserve(frameEndInfo->layerCount);
    bool changed = false;

    for (uint32_t index = 0; index < frameEndInfo->layerCount; ++index)
    {
        const XrCompositionLayerBaseHeader* base = frameEndInfo->layers[index];
        if (base != nullptr && base->type == XR_TYPE_COMPOSITION_LAYER_PROJECTION)
        {
            const XrCompositionLayerProjection* projection =
                reinterpret_cast<const XrCompositionLayerProjection*>(base);
            if (isLocalSpace(projection->space))
            {
                copies.emplace_back();
                ProjectionCopy& copy = copies.back();
                copy.layer = *projection;
                if (projection->viewCount != 0 && projection->views == nullptr)
                    return next(session, frameEndInfo);
                copy.views.assign(projection->views, projection->views + projection->viewCount);
                for (XrCompositionLayerProjectionView& view : copy.views)
                    transformNewToOld(&view.pose, markerPose);
                copy.layer.views = copy.views.data();
                layers.push_back(reinterpret_cast<const XrCompositionLayerBaseHeader*>(&copy.layer));
                changed = true;
                continue;
            }
        }
        layers.push_back(base);
    }

    if (!changed)
        return next(session, frameEndInfo);
    XrFrameEndInfo copiedEndInfo = *frameEndInfo;
    copiedEndInfo.layers = layers.data();
    return next(session, &copiedEndInfo);
}

XrResult XRAPI_CALL layerGetInstanceProcAddr(
    XrInstance instance, const char* name, PFN_xrVoidFunction* function)
{
    if (name == nullptr || function == nullptr)
        return XR_ERROR_VALIDATION_FAILURE;
    struct Intercept
    {
        const char* name;
        PFN_xrVoidFunction function;
    };
    static const Intercept intercepts[] = {
        {"xrDestroyInstance", reinterpret_cast<PFN_xrVoidFunction>(layerDestroyInstance)},
        {"xrCreateSession", reinterpret_cast<PFN_xrVoidFunction>(layerCreateSession)},
        {"xrDestroySession", reinterpret_cast<PFN_xrVoidFunction>(layerDestroySession)},
        {"xrCreateReferenceSpace", reinterpret_cast<PFN_xrVoidFunction>(layerCreateReferenceSpace)},
        {"xrDestroySpace", reinterpret_cast<PFN_xrVoidFunction>(layerDestroySpace)},
        {"xrPollEvent", reinterpret_cast<PFN_xrVoidFunction>(layerPollEvent)},
        {"xrWaitFrame", reinterpret_cast<PFN_xrVoidFunction>(layerWaitFrame)},
        {"xrLocateViews", reinterpret_cast<PFN_xrVoidFunction>(layerLocateViews)},
        {"xrLocateSpace", reinterpret_cast<PFN_xrVoidFunction>(layerLocateSpace)},
        {"xrEndFrame", reinterpret_cast<PFN_xrVoidFunction>(layerEndFrame)},
    };
    for (const Intercept& intercept : intercepts)
    {
        if (std::strcmp(name, intercept.name) == 0)
        {
            *function = intercept.function;
            return XR_SUCCESS;
        }
    }

    PFN_xrGetInstanceProcAddr next = nullptr;
    {
        std::lock_guard<std::mutex> lock(g_state.mutex);
        next = g_state.nextGetInstanceProcAddr;
    }
    return next == nullptr ? XR_ERROR_FUNCTION_UNSUPPORTED : next(instance, name, function);
}

XrResult XRAPI_CALL layerCreateApiLayerInstance(
    const XrInstanceCreateInfo* info, const XrApiLayerCreateInfo* layerInfo, XrInstance* instance)
{
    if (layerInfo == nullptr || layerInfo->nextInfo == nullptr || instance == nullptr)
        return XR_ERROR_INITIALIZATION_FAILED;
    XrApiLayerNextInfo* nextInfo = layerInfo->nextInfo;
    if (nextInfo->nextGetInstanceProcAddr == nullptr || nextInfo->nextCreateApiLayerInstance == nullptr)
        return XR_ERROR_INITIALIZATION_FAILED;

    XrApiLayerCreateInfo nextLayerInfo = *layerInfo;
    nextLayerInfo.nextInfo = nextInfo->next;
    const XrResult result =
        nextInfo->nextCreateApiLayerInstance(info, &nextLayerInfo, instance);
    if (XR_FAILED(result))
        return result;

    std::lock_guard<std::mutex> lock(g_state.mutex);
    if (g_state.instance != XR_NULL_HANDLE)
        return XR_ERROR_LIMIT_REACHED;
    g_state.nextGetInstanceProcAddr = nextInfo->nextGetInstanceProcAddr;
    g_state.nextCreateApiLayerInstance = nextInfo->nextCreateApiLayerInstance;
    g_state.instance = *instance;
    loadNextFunctions(*instance);
    return XR_SUCCESS;
}

} // namespace

extern "C" XRAPI_ATTR XrResult XRAPI_CALL xrNegotiateLoaderApiLayerInterface(
    const XrNegotiateLoaderInfo* loaderInfo, const char* layerName,
    XrNegotiateApiLayerRequest* apiLayerRequest)
{
    if (loaderInfo == nullptr || apiLayerRequest == nullptr || layerName == nullptr ||
        std::strcmp(layerName, kLayerName) != 0 ||
        loaderInfo->structType != XR_LOADER_INTERFACE_STRUCT_LOADER_INFO ||
        apiLayerRequest->structType != XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST ||
        loaderInfo->minInterfaceVersion > XR_CURRENT_LOADER_API_LAYER_VERSION ||
        loaderInfo->maxInterfaceVersion < XR_CURRENT_LOADER_API_LAYER_VERSION ||
        loaderInfo->minApiVersion > XR_CURRENT_API_VERSION ||
        loaderInfo->maxApiVersion < XR_API_VERSION_1_0)
        return XR_ERROR_INITIALIZATION_FAILED;

    apiLayerRequest->layerInterfaceVersion = XR_CURRENT_LOADER_API_LAYER_VERSION;
    apiLayerRequest->layerApiVersion =
        std::min<XrVersion>(loaderInfo->maxApiVersion, static_cast<XrVersion>(XR_CURRENT_API_VERSION));
    apiLayerRequest->getInstanceProcAddr = layerGetInstanceProcAddr;
    apiLayerRequest->createApiLayerInstance = layerCreateApiLayerInstance;
    return XR_SUCCESS;
}
