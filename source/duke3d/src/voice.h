// SPDX-License-Identifier: GPL-2.0-only
// Multiplayer voice chat: SDL capture, Opus (48 kHz mono, 20 ms), VAD or
// push-to-talk, ENet relay through the server, adaptive jitter buffer with
// Opus loss concealment, and positional playback through the native mixer.
// Design follows QuakeSpasm 2.0's voice chat (distance attenuation, stereo
// pan, crossfade to a centred "radio" level for distant talkers).
#pragma once

#include <cstdint>

// Wire body shared by both directions (the network layer adds the packet type,
// and the source player on relay): u16 sequence, u32 timestamp (+960 per
// frame), u8 talkspurt, u8 flags, u16 payload length, Opus payload.
enum : uint8_t { VoiceFlagStart = 1, VoiceFlagEnd = 2 };
constexpr uint32_t VoiceHeaderBytes = 10, VoiceMaxPayload = 400;

#ifdef USE_VOICECHAT
void Voice_Init(void);      // cvars and commands (after the OSD exists)
void Voice_Shutdown(void);
void Voice_Frame(void);     // once per displayed frame: capture/encode/send, decode, spatialize
void Voice_ReceivePacket(int source, uint8_t const *body, uint32_t length);
bool Voice_ValidBody(uint8_t const *body, uint32_t length);
void Voice_ResetPlayer(int player);
bool Voice_IsTalking(int player);
void Voice_SetPushToTalk(bool held); // VR controller push-to-talk (left Y / Index left B)
bool Voice_PushToTalkMode(void);     // voice chat on in push-to-talk mode (the VR button talks)
void Voice_DrawStatus(void);         // HUD: mic state and who is talking

// Transport, implemented by network.cpp.
bool Net_VoiceAvailable(void);
void Net_SendVoice(uint8_t const *body, uint32_t length);
#else
static inline void Voice_Init(void) {}
static inline void Voice_Shutdown(void) {}
static inline void Voice_Frame(void) {}
static inline void Voice_ReceivePacket(int, uint8_t const *, uint32_t) {}
static inline bool Voice_ValidBody(uint8_t const *, uint32_t) { return false; }
static inline void Voice_ResetPlayer(int) {}
static inline bool Voice_IsTalking(int) { return false; }
static inline void Voice_SetPushToTalk(bool) {}
static inline bool Voice_PushToTalkMode(void) { return false; }
static inline void Voice_DrawStatus(void) {}
#endif
