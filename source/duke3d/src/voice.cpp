// SPDX-License-Identifier: GPL-2.0-only
// Multiplayer voice chat (see voice.h). Structure and constants follow
// QuakeSpasm 2.0's voice chat: SDL capture, Opus VoIP 24 kbps VBR/DTX in
// 20 ms frames, energy VAD with pre-roll and hangover, per-talker adaptive
// jitter buffer (60-140 ms) with Opus PLC, distance attenuation + stereo pan
// crossfading into a centred "radio" level for distant talkers.
#ifdef USE_VOICECHAT

#include "voice.h"

#include "duke3d.h"
#include "fx_man.h"
#include "multivoc.h"
#include "osd.h"
#include "sdl_inc.h"
#ifdef USE_OPENXR
# include "vr.h"
#endif

#include <opus.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

// ---------------------------------------------------------------- settings (voice.h)
int32_t voice_enable = 1;          // receive and play voice
int32_t voice_transmit = 2;        // 0 off, 1 on, 2 auto (on in VR, off on desktop)
int32_t voice_mode = 0;            // 0 voice activation, 1 push-to-talk
int32_t voice_vad_sensitivity = 55;
int32_t voice_ptt_key = 0;         // legacy keyboard scancode for push-to-talk (0 none); see Push_To_Talk
int32_t voice_loopback = 0;        // hear your own transmission (mic test)
int32_t voice_hud = 1;
float voice_input_gain = 1.f;
float voice_volume = 1.f;
int32_t voice_agc = 1;            // automatic gain control of each talker (received audio)
float voice_agc_max_gain = 8.f;   // most a quiet microphone is raised (x)
float voice_radio_volume = .45f;
int32_t voice_spatial_distance = 9216;  // Build units (~24 m) where a talker becomes "radio"
char voice_device[128] = "";

namespace
{
constexpr int Rate = 48000, Frame = 960;               // 20 ms
constexpr int MaxSpeakers = MAXPLAYERS;
constexpr int RingSamples = 16384;                     // ~340 ms per talker
constexpr int JitterPackets = 16;

float playerVolume[MaxSpeakers];

double nowMs() { return 1000.0 * double(timerGetNanoTicks()) / double(timerGetNanoTickRate()); }

bool transmitAllowed()
{
    if (voice_transmit == 2)
    {
#ifdef USE_OPENXR
        char const *xr = std::getenv("EDUKE32_XR");
        return xr && *xr && std::strcmp(xr, "0");
#else
        return false;
#endif
    }
    return voice_transmit != 0;
}

// ---------------------------------------------------------------- VAD
struct Vad
{
    float noise = -1.f, meter = 0.f;
    int loud = 0, quiet = 0;
    bool active = false;

    void update(int16_t const *pcm)
    {
        double sum = 0;
        for (int i = 0; i < Frame; ++i) sum += std::abs(int(pcm[i]));
        float const energy = float(sum / Frame);
        meter = meter * .75f + energy * .25f;
        if (noise < 0) noise = std::max(energy, 8.f);
        float const s = float(clamp(voice_vad_sensitivity, 0, 100));
        float const openRatio = (2304.f - 11.f * s) / 1024.f, closeRatio = openRatio - .25f;
        float const openMargin = std::max(960.f - 7.f * s, 192.f) / 256.f * 32.f, closeMargin = openMargin * .5f + 6.f;
        float const openAt = std::max(noise * openRatio, noise + openMargin);
        float const closeAt = std::max(noise * closeRatio, noise + closeMargin);
        if (!active)
        {
            loud = energy > openAt ? loud + 1 : 0;
            if (loud >= 2) { active = true; quiet = 0; }
            noise = energy < openAt ? noise * 15.f / 16.f + energy / 16.f : noise * 31.f / 32.f + energy / 32.f;
        }
        else
        {
            if (energy < closeAt) { if (++quiet >= 12) { active = false; loud = 0; } noise = noise * 63.f / 64.f + energy / 64.f; }
            else quiet = 0;
        }
        noise = std::max(noise, 4.f);
    }
};

// ---------------------------------------------------------------- capture/encode
struct Capture
{
    SDL_AudioDeviceID device = 0;
    SDL_AudioStream *stream = nullptr;
    bool sdlAudio = false;
    double retryAt = 0;
    std::vector<int16_t> pending;
    // Test source (EDUKE32_VOICE_TEST_TONE=hz[:on_ms:off_ms]): a synthetic microphone.
    double toneHz = 0, toneOn = 0, toneOff = 0, toneStart = -1, toneSamples = 0;
} capture;

OpusEncoder *encoder;
Vad vad;
bool pushToTalk, vrPushToTalk, transmitting;
// The voice settings menu keeps the microphone open for its level meter (nothing is sent).
bool menuMonitor, gateOpen;
double menuMonitorUntil;   // refreshed every frame the voice menu shows
uint32_t statSent, statReceived, statDecoded, statConcealed;
uint16_t sequence;
uint32_t timestamp;
uint8_t talkspurt;
std::vector<std::vector<int16_t>> preroll;

void closeCapture()
{
    if (capture.device) SDL_CloseAudioDevice(capture.device);
    if (capture.stream) SDL_FreeAudioStream(capture.stream);
    capture.device = 0; capture.stream = nullptr;
    capture.pending.clear();
}

bool openCapture()
{
    if (capture.toneHz > 0) return true;
    if (capture.device) return true;
    double const now = nowMs();
    if (now < capture.retryAt) return false;
    capture.retryAt = now + 10000.0;
    if (!SDL_WasInit(SDL_INIT_AUDIO))
    {
        if (SDL_InitSubSystem(SDL_INIT_AUDIO) != 0) return false;
        capture.sdlAudio = true;
    }
    SDL_AudioSpec want{}, have{};
    want.freq = Rate; want.format = AUDIO_S16SYS; want.channels = 1; want.samples = Frame;
    capture.device = SDL_OpenAudioDevice(voice_device[0] ? voice_device : nullptr, 1, &want, &have, SDL_AUDIO_ALLOW_ANY_CHANGE);
    if (!capture.device)
    {
        LOG_F(WARNING, "Voice: no capture device (%s).", SDL_GetError());
        return false;
    }
    if (have.freq != Rate || have.format != AUDIO_S16SYS || have.channels != 1)
        capture.stream = SDL_NewAudioStream(have.format, have.channels, have.freq, AUDIO_S16SYS, 1, Rate);
    SDL_PauseAudioDevice(capture.device, 0);
    LOG_F(INFO, "Voice: capturing from %s (%d Hz, %d ch).", voice_device[0] ? voice_device : "default device", have.freq, have.channels);
    return true;
}

// Pull whole 20 ms frames of 48 kHz mono PCM; at most a few per call.
bool nextCaptureFrame(int16_t *out)
{
    if (capture.toneHz > 0)
    {
        double const now = nowMs();
        if (capture.toneStart < 0) capture.toneStart = now;
        double const due = (now - capture.toneStart) * Rate / 1000.0;
        if (capture.toneSamples + Frame > due) return false;
        double const period = capture.toneOn + capture.toneOff;
        for (int i = 0; i < Frame; ++i)
        {
            double const t = (capture.toneSamples + i) / Rate;
            bool const on = period <= 0 || std::fmod(t * 1000.0, period) < capture.toneOn;
            out[i] = on ? int16_t(9000.0 * std::sin(2 * M_PI * capture.toneHz * t)) : int16_t((i * 7919) % 41 - 20);
        }
        capture.toneSamples += Frame;
        return true;
    }
    if (!capture.device) return false;
    uint8_t raw[8192];
    while (capture.pending.size() < size_t(Frame))
    {
        uint32_t const queued = SDL_GetQueuedAudioSize(capture.device);
        if (!queued) break;
        uint32_t const got = SDL_DequeueAudio(capture.device, raw, std::min<uint32_t>(queued, sizeof(raw)));
        if (!got) break;
        if (capture.stream)
        {
            SDL_AudioStreamPut(capture.stream, raw, got);
            int16_t conv[4096];
            int n;
            while ((n = SDL_AudioStreamGet(capture.stream, conv, sizeof(conv))) > 0)
                capture.pending.insert(capture.pending.end(), conv, conv + n / 2);
        }
        else capture.pending.insert(capture.pending.end(), (int16_t *)raw, (int16_t *)raw + got / 2);
    }
    // Drop a backlog (e.g. after a hitch) rather than send stale audio.
    if (capture.pending.size() > size_t(Frame * 10))
        capture.pending.erase(capture.pending.begin(), capture.pending.end() - Frame);
    if (capture.pending.size() < size_t(Frame)) return false;
    std::copy_n(capture.pending.begin(), Frame, out);
    capture.pending.erase(capture.pending.begin(), capture.pending.begin() + Frame);
    return true;
}

void sendFrame(uint8_t const *payload, int bytes, uint8_t flags)
{
    uint8_t body[VoiceHeaderBytes + VoiceMaxPayload];
    body[0] = uint8_t(sequence); body[1] = uint8_t(sequence >> 8);
    for (int i = 0; i < 4; ++i) body[2 + i] = uint8_t(timestamp >> (8 * i));
    body[6] = talkspurt; body[7] = flags;
    body[8] = uint8_t(bytes); body[9] = uint8_t(bytes >> 8);
    if (bytes > 0) std::memcpy(body + VoiceHeaderBytes, payload, bytes);
    ++sequence;
    ++statSent;
    if (bytes > 0) timestamp += Frame;
    Net_SendVoice(body, VoiceHeaderBytes + bytes);
    if (voice_loopback) Voice_ReceivePacket(myconnectindex, body, VoiceHeaderBytes + bytes);
}

void encodeAndSend(int16_t const *pcm, uint8_t flags)
{
    uint8_t payload[VoiceMaxPayload];
    int const bytes = opus_encode(encoder, pcm, Frame, payload, VoiceMaxPayload);
    if (bytes < 0) return;
    sendFrame(payload, bytes, flags);
}

void processCapture()
{
    menuMonitor = nowMs() < menuMonitorUntil;
    bool const session = Net_VoiceAvailable() || voice_loopback;
    bool const live = session && transmitAllowed() && encoder;
    if (!live && transmitting) { sendFrame(nullptr, 0, VoiceFlagEnd); transmitting = false; }
    if (!(session && transmitAllowed()) && !menuMonitor) { closeCapture(); gateOpen = false; return; }
    if (!openCapture()) { gateOpen = false; return; }
    int16_t pcm[Frame];
    for (int frames = 0; frames < 10 && nextCaptureFrame(pcm); ++frames)
    {
        if (voice_input_gain != 1.f)
            for (auto &s : pcm) s = int16_t(clamp(int(s * voice_input_gain), -32768, 32767));
        vad.update(pcm);
        bool const ptt = pushToTalk || vrPushToTalk;
        bool const gate = voice_mode ? ptt : vad.active;
        gateOpen = gate;
        if (!live) continue;   // monitoring for the settings menu only
        if (gate && !transmitting)
        {
            transmitting = true;
            if (++talkspurt == 0) talkspurt = 1;
            opus_encoder_ctl(encoder, OPUS_RESET_STATE);
            bool first = true;
            if (!voice_mode)
                for (auto &frame : preroll) { encodeAndSend(frame.data(), first ? VoiceFlagStart : 0); first = false; }
            preroll.clear();
            encodeAndSend(pcm, first ? VoiceFlagStart : 0);
        }
        else if (gate) encodeAndSend(pcm, 0);
        else
        {
            if (transmitting) { sendFrame(nullptr, 0, VoiceFlagEnd); transmitting = false; }
            preroll.emplace_back(pcm, pcm + Frame);
            if (preroll.size() > 3) preroll.erase(preroll.begin());
        }
    }
}

// ---------------------------------------------------------------- receive/jitter/decode
struct Packet { uint16_t seq; uint8_t flags; uint16_t bytes; uint8_t data[VoiceMaxPayload]; };

struct Speaker
{
    OpusDecoder *decoder = nullptr;
    Packet jitter[JitterPackets];
    int count = 0;
    bool started = false, ended = false;
    uint8_t talkspurt = 0;
    uint16_t expected = 0;
    double firstArrival = 0, lastArrival = 0, deadline = 0, talkingUntil = 0, lastAudio = 0;
    int targetMs = 60, impairment = 0;
    // Audio thread ring (SPSC): written here, read by the mixer's demand feed.
    int16_t ring[RingSamples];
    std::atomic<uint32_t> head{0}, tail{0};
    int16_t block[Frame];
    int handle = 0;
    FILE *dump = nullptr;
    float agcLevel = 0.f, agcGain = 1.f, agcApplied = 1.f;   // AGC: speech level estimate, gain, last gain used
} speakers[MaxSpeakers];

// Automatic gain control per talker: brings each player's speech to one loudness whatever their
// microphone (quiet mics were hard to hear in VR). The level follows speech only (frames above a
// noise floor), so pauses and background noise are not pumped up; the gain falls quickly and rises
// slowly, ramps across each 20 ms frame and is capped so the frame never clips.
void applyAgc(Speaker &sp, int16_t *pcm, int n)
{
    if (!voice_agc || n <= 0) return;
    constexpr float Target = 4000.f, NoiseFloor = 250.f;   // RMS: ~-18 dBFS speech, ~-42 dBFS floor
    double sum = 0; int peak = 1;
    for (int i = 0; i < n; i++) { sum += double(pcm[i]) * pcm[i]; peak = std::max(peak, std::abs(int(pcm[i]))); }
    float const rms = float(std::sqrt(sum / n));
    if (rms > NoiseFloor)
    {
        sp.agcLevel = sp.agcLevel <= 0.f ? rms : sp.agcLevel + (rms - sp.agcLevel) * (rms > sp.agcLevel ? .3f : .05f);
        float const want = clamp(Target / sp.agcLevel, .5f, std::max(1.f, voice_agc_max_gain));
        sp.agcGain += (want - sp.agcGain) * (want < sp.agcGain ? .3f : .05f);
    }
    float const gain = std::min(sp.agcGain, 32000.f / float(peak));
    float const from = sp.agcApplied;
    for (int i = 0; i < n; i++)
    {
        float const g = from + (gain - from) * float(i + 1) / float(n);
        pcm[i] = int16_t(clamp(int(std::lround(pcm[i] * g)), -32768, 32767));
    }
    sp.agcApplied = gain;
}

void demandFeed(char const **ptr, uint32_t *length, void *userdata)
{
    auto &sp = *static_cast<Speaker *>(userdata);
    uint32_t tail = sp.tail.load(std::memory_order_relaxed);
    uint32_t const head = sp.head.load(std::memory_order_acquire);
    int i = 0;
    for (; i < Frame && tail != head; ++i, ++tail) sp.block[i] = sp.ring[tail % RingSamples];
    for (; i < Frame; ++i) sp.block[i] = 0;
    sp.tail.store(tail, std::memory_order_release);
    *ptr = (char const *)sp.block;
    *length = Frame;
}

void pushAudio(Speaker &sp, int16_t *pcm, int n)
{
    applyAgc(sp, pcm, n);
    uint32_t head = sp.head.load(std::memory_order_relaxed);
    uint32_t const tail = sp.tail.load(std::memory_order_acquire);
    for (int i = 0; i < n && head - tail < uint32_t(RingSamples); ++i, ++head) sp.ring[head % RingSamples] = pcm[i];
    sp.head.store(head, std::memory_order_release);
    if (sp.dump) std::fwrite(pcm, sizeof(int16_t), n, sp.dump);
}

void resetSpeaker(Speaker &sp)
{
    sp.count = 0; sp.started = sp.ended = false;
    if (sp.decoder) opus_decoder_ctl(sp.decoder, OPUS_RESET_STATE);
}

int16_t seqDiff(uint16_t a, uint16_t b) { return int16_t(uint16_t(a - b)); }

void decodeSpeaker(int index, double now)
{
    auto &sp = speakers[index];
    if (!sp.decoder) return;
    if (!sp.started)
    {
        if (!sp.count || now - sp.firstArrival < sp.targetMs) return;
        sp.started = true; sp.deadline = now;
        sp.expected = sp.jitter[0].seq;
    }
    int16_t pcm[Frame];
    for (int steps = 0; steps < 8 && now >= sp.deadline; ++steps)
    {
        int found = -1;
        for (int i = 0; i < sp.count; ++i) if (sp.jitter[i].seq == sp.expected) { found = i; break; }
        if (found >= 0)
        {
            Packet const pkt = sp.jitter[found];
            std::move(sp.jitter + found + 1, sp.jitter + sp.count, sp.jitter + found);
            --sp.count;
            if (pkt.bytes == 0 && (pkt.flags & VoiceFlagEnd))
            {
                // End of the talkspurt: adapt the target delay to how rough it was.
                sp.targetMs = sp.impairment ? 60 + 20 * std::min(sp.impairment, 4) : std::max(60, sp.targetMs - 20);
                sp.impairment = 0;
                resetSpeaker(sp);
                return;
            }
            int const n = opus_decode(sp.decoder, pkt.data, pkt.bytes, pcm, Frame, 0);
            if (n > 0) { pushAudio(sp, pcm, n); sp.talkingUntil = now + 150; sp.lastAudio = now; ++statDecoded; }
        }
        else if (sp.count)
        {
            // Missing frame at its deadline: Opus packet-loss concealment.
            int const n = opus_decode(sp.decoder, nullptr, 0, pcm, Frame, 0);
            if (n > 0) { pushAudio(sp, pcm, n); ++statConcealed; }
            sp.impairment = std::min(sp.impairment + 1, 4);
            // Skip past frames that can no longer arrive in order.
            for (int i = 0; i < sp.count; )
                if (seqDiff(sp.jitter[i].seq, sp.expected) < 0) { std::move(sp.jitter + i + 1, sp.jitter + sp.count, sp.jitter + i); --sp.count; }
                else ++i;
        }
        else
        {
            if (now - sp.lastArrival > 400) resetSpeaker(sp);   // stream went quiet without an END
            return;
        }
        ++sp.expected;
        sp.deadline += 20.0;
    }
}

// ---------------------------------------------------------------- spatial playback
void listener(vec3_t &pos, int &ang)
{
    auto const p = g_player[screenpeek].ps;
    if (ud.camerasprite == -1)
    {
        pos = CAMERA(pos);
        ang = fix16_to_int(CAMERA(q16ang));
#ifdef USE_OPENXR
        ang = G_XRListenerAngle(ang);   // head yaw in VR
#endif
    }
    else { pos = sprite[ud.camerasprite].xyz; ang = sprite[ud.camerasprite].ang; }
    (void)p;
}

void updatePlayback(int index, double now)
{
    auto &sp = speakers[index];
    bool const active = now - sp.lastAudio < 2000.0;
    if (!active || !voice_enable || !ud.config.SoundToggle)
    {
        if (MV_VoiceOwnedBy(sp.handle, &sp)) FX_StopSound(sp.handle, false);
        sp.handle = 0;
        return;
    }
    // Gains: positional attenuation + pan near, crossfading into a centred radio level far away.
    float left = voice_radio_volume, right = voice_radio_volume;
    auto const p = g_player[index].ps;
    if (index != myconnectindex && p && unsigned(p->i) < MAXSPRITES && (p->gm & MODE_GAME))
    {
        vec3_t l; int ang;
        listener(l, ang);
        float const dx = float(p->pos.x - l.x), dy = float(p->pos.y - l.y), dz = float(p->pos.z - l.z) / 16.f;
        float const dist = std::sqrt(dx * dx + dy * dy + dz * dz);
        float const a = ang * (fPI / 1024.f);
        float const pan = dist > 1.f ? (dx * -std::sin(a) + dy * std::cos(a)) / dist : 0.f;   // +1 = listener's right
        float const blend = clamp(dist / float(std::max(voice_spatial_distance, 1)), 0.f, 1.f);
        float const positional = 1.f / (1.f + dist / 6144.f);
        left = (1.f - blend) * positional * (1.f - .5f * pan) + blend * voice_radio_volume;
        right = (1.f - blend) * positional * (1.f + .5f * pan) + blend * voice_radio_volume;
    }
    // Headroom so a nearby talker can pan fully (0.5x..1.5x per side) without clipping the 0-255 range.
    float const gain = .66f * voice_volume * playerVolume[index] * ud.config.FXVolume / 255.f;
    int const l = clamp(int(left * gain * 255.f), 0, 255), r = clamp(int(right * gain * 255.f), 0, 255);
    // Our voice only while the handle still is it (a finished voice's handle is reused by game
    // sounds). MUSIC_ID: the game's sound callback ignores this voice ending.
    if (!MV_VoiceOwnedBy(sp.handle, &sp) || !FX_SoundValidAndActive(sp.handle))
        sp.handle = FX_StartDemandFeedPlayback(demandFeed, 16, 1, Rate, 0, std::max(l, r), l, r, 255, fix16_one, MUSIC_ID, &sp);
    else
        FX_SetPan(sp.handle, std::max(l, r), l, r);
    if (std::getenv("EDUKE32_VOICE_TEST_DUMP"))
    {
        static double lastLog[MaxSpeakers];
        if (now - lastLog[index] > 1000.0)
        {
            lastLog[index] = now;
            LOG_F(INFO, "Voice playback: speaker=%d left=%d right=%d handle=%d buffered=%u.", index, l, r, sp.handle,
                  sp.head.load() - sp.tail.load());
        }
    }
}

int findPlayer(char const *name)
{
    char *end;
    long const slot = std::strtol(name, &end, 10);
    if (end != name && !*end && slot >= 0 && slot < MAXPLAYERS) return int(slot);
    for (int i = 0; i < MAXPLAYERS; ++i)
        if (g_player[i].ps && !Bstrcasecmp(g_player[i].user_name, name)) return i;
    return -1;
}

int osdcmd_voice_mute(osdcmdptr_t parm)
{
    if (parm->numparms != 1) return OSDCMD_SHOWHELP;
    int const p = findPlayer(parm->parms[0]);
    if (p < 0) { OSD_Printf("voice_mute: no player \"%s\"\n", parm->parms[0]); return OSDCMD_OK; }
    playerVolume[p] = playerVolume[p] > 0.f ? 0.f : 1.f;
    OSD_Printf("voice: %s %s\n", g_player[p].user_name, playerVolume[p] > 0.f ? "unmuted" : "muted");
    return OSDCMD_OK;
}

int osdcmd_voice_devices(osdcmdptr_t)
{
    if (!SDL_WasInit(SDL_INIT_AUDIO)) SDL_InitSubSystem(SDL_INIT_AUDIO);
    int const n = SDL_GetNumAudioDevices(1);
    OSD_Printf("Recording devices (%d):\n", n);
    for (int i = 0; i < n; ++i) OSD_Printf("  \"%s\"\n", SDL_GetAudioDeviceName(i, 1));
    return OSDCMD_OK;
}

int osdcmd_voice_status(osdcmdptr_t)
{
    OSD_Printf("voice: transport=%d transmit=%d mode=%s capture=%s transmitting=%d level=%.0f noise=%.0f\n",
               Net_VoiceAvailable(), transmitAllowed(), voice_mode ? "ptt" : "vad",
               capture.toneHz > 0 ? "test tone" : capture.device ? "open" : "closed", transmitting, vad.meter, vad.noise);
    for (int i = 0; i < MaxSpeakers; ++i)
        if (speakers[i].decoder)
            OSD_Printf("  %d %s: %s target=%dms%s\n", i, g_player[i].user_name, Voice_IsTalking(i) ? "talking" : "quiet",
                       speakers[i].targetMs, playerVolume[i] > 0.f ? "" : " (muted)");
    return OSDCMD_OK;
}

int osdcmd_voice_restart(osdcmdptr_t)
{
    closeCapture(); capture.retryAt = 0;
    return OSDCMD_OK;
}
} // namespace

void Voice_Init(void)
{
    static osdcvardata_t cvars[] = {
        { "voice_enable", "voice chat: receive and play other players' voices", (void *)&voice_enable, CVAR_BOOL, 0, 1 },
        { "voice_transmit", "voice chat transmit: 0 off, 1 on, 2 auto (on in VR, off on desktop)", (void *)&voice_transmit, CVAR_INT, 0, 2 },
        { "voice_mode", "voice chat: 0 voice activation, 1 push-to-talk", (void *)&voice_mode, CVAR_INT, 0, 1 },
        { "voice_vad_sensitivity", "voice activation sensitivity (0-100)", (void *)&voice_vad_sensitivity, CVAR_INT, 0, 100 },
        { "voice_ptt_key", "extra keyboard scancode held for push-to-talk (0 none; bind Push_To_Talk instead)", (void *)&voice_ptt_key, CVAR_INT, 0, 255 },
        { "voice_loopback", "hear your own voice (microphone test)", (void *)&voice_loopback, CVAR_BOOL|CVAR_NOSAVE, 0, 1 },
        { "voice_hud", "show the microphone state and who is talking", (void *)&voice_hud, CVAR_BOOL, 0, 1 },
        { "voice_input_gain", "microphone gain (0-4)", (void *)&voice_input_gain, CVAR_FLOAT, 0, 4 },
        { "voice_volume", "voice chat volume (0-2)", (void *)&voice_volume, CVAR_FLOAT, 0, 2 },
        { "voice_agc", "automatic gain control: every talker at one loudness, quiet microphones raised (0/1)", (void *)&voice_agc, CVAR_BOOL, 0, 1 },
        { "voice_agc_max_gain", "most the automatic gain control raises a quiet microphone (1-16x)", (void *)&voice_agc_max_gain, CVAR_FLOAT, 1, 16 },
        { "voice_radio_volume", "volume of distant talkers (centred radio level, 0-1)", (void *)&voice_radio_volume, CVAR_FLOAT, 0, 1 },
        { "voice_spatial_distance", "distance (Build units) at which a talker is heard as radio", (void *)&voice_spatial_distance, CVAR_INT, 512, 65536 },
        { "voice_device", "recording device name (\"\" = system default; see voice_devices)", (void *)voice_device, CVAR_STRING, 0, sizeof(voice_device) },
    };
    for (auto &cv : cvars) OSD_RegisterCvar(&cv, osdcmd_cvar_set);
    OSD_RegisterFunction("voice_mute", "voice_mute <name|slot>: toggle muting a player's voice", osdcmd_voice_mute);
    OSD_RegisterFunction("voice_devices", "voice_devices: list recording devices", osdcmd_voice_devices);
    OSD_RegisterFunction("voice_status", "voice_status: voice chat state", osdcmd_voice_status);
    OSD_RegisterFunction("voice_restart", "voice_restart: reopen the recording device", osdcmd_voice_restart);
    for (auto &v : playerVolume) v = 1.f;
    int error = 0;
    encoder = opus_encoder_create(Rate, 1, OPUS_APPLICATION_VOIP, &error);
    if (encoder)
    {
        opus_encoder_ctl(encoder, OPUS_SET_BITRATE(24000));
        opus_encoder_ctl(encoder, OPUS_SET_VBR(1));
        opus_encoder_ctl(encoder, OPUS_SET_DTX(1));
    }
    if (char const *tone = std::getenv("EDUKE32_VOICE_TEST_TONE"))
    {
        std::sscanf(tone, "%lf:%lf:%lf", &capture.toneHz, &capture.toneOn, &capture.toneOff);
        LOG_F(INFO, "Voice: test tone %.0f Hz (%.0f ms on / %.0f ms off) replaces the microphone.", capture.toneHz, capture.toneOn, capture.toneOff);
    }
}

void Voice_Shutdown(void)
{
    closeCapture();
    for (auto &sp : speakers)
    {
        if (MV_VoiceOwnedBy(sp.handle, &sp)) FX_StopSound(sp.handle, false);
        sp.handle = 0;
        if (sp.decoder) opus_decoder_destroy(sp.decoder);
        sp.decoder = nullptr;
        if (sp.dump) std::fclose(sp.dump);
        sp.dump = nullptr;
    }
    if (encoder) opus_encoder_destroy(encoder);
    encoder = nullptr;
}

bool Voice_ValidBody(uint8_t const *body, uint32_t length)
{
    if (length < VoiceHeaderBytes) return false;
    uint32_t const bytes = body[8] | (body[9] << 8);
    uint8_t const flags = body[7];
    return bytes <= VoiceMaxPayload && length == VoiceHeaderBytes + bytes && !(flags & ~(VoiceFlagStart | VoiceFlagEnd))
        && (bytes > 0 || (flags & VoiceFlagEnd));
}

void Voice_ReceivePacket(int source, uint8_t const *body, uint32_t length)
{
    if ((unsigned)source >= MaxSpeakers || !voice_enable || !Voice_ValidBody(body, length)) return;
    if (source == myconnectindex && !voice_loopback) return;
    ++statReceived;
    auto &sp = speakers[source];
    if (!sp.decoder)
    {
        int error = 0;
        sp.decoder = opus_decoder_create(Rate, 1, &error);
        if (!sp.decoder) return;
        if (char const *prefix = std::getenv("EDUKE32_VOICE_TEST_DUMP"))
        {
            std::string path = std::string(prefix) + "-speaker-" + std::to_string(source) + ".s16";
            sp.dump = std::fopen(path.c_str(), "wb");
        }
    }
    double const now = nowMs();
    Packet pkt;
    pkt.seq = uint16_t(body[0] | (body[1] << 8));
    pkt.flags = body[7];
    pkt.bytes = uint16_t(body[8] | (body[9] << 8));
    std::memcpy(pkt.data, body + VoiceHeaderBytes, pkt.bytes);
    uint8_t const spurt = body[6];
    if (spurt != sp.talkspurt || now - sp.lastArrival > 400)
    {
        resetSpeaker(sp);
        sp.talkspurt = spurt;
        sp.firstArrival = now;
    }
    sp.lastArrival = now;
    if (sp.started && seqDiff(pkt.seq, sp.expected) < 0) return;       // too late
    for (int i = 0; i < sp.count; ++i) if (sp.jitter[i].seq == pkt.seq) return;   // duplicate
    if (sp.count == JitterPackets) { sp.impairment = std::min(sp.impairment + 1, 4); return; }
    int at = sp.count;
    while (at > 0 && seqDiff(sp.jitter[at - 1].seq, pkt.seq) > 0) { sp.jitter[at] = sp.jitter[at - 1]; --at; }
    if (at != sp.count) sp.impairment = std::min(sp.impairment + 1, 4);  // reordered
    sp.jitter[at] = pkt;
    ++sp.count;
    if (sp.count == 1 && !sp.started) sp.firstArrival = now;
}

void Voice_ResetPlayer(int player)
{
    if ((unsigned)player >= MaxSpeakers) return;
    auto &sp = speakers[player];
    resetSpeaker(sp);
    sp.lastAudio = 0;
    if (MV_VoiceOwnedBy(sp.handle, &sp)) FX_StopSound(sp.handle, false);
    sp.handle = 0;
    playerVolume[player] = 1.f;
}

bool Voice_IsTalking(int player)
{
    if ((unsigned)player >= MaxSpeakers) return false;
    if (player == myconnectindex && !voice_loopback) return transmitting;
    return nowMs() < speakers[player].talkingUntil;
}

bool Voice_PushToTalkMode(void) { return voice_enable && voice_mode==1; }

void Voice_SetPushToTalk(bool held) { vrPushToTalk = held; }

int Voice_CaptureDevices(char const ***names)
{
    static std::vector<std::string> list;
    static std::vector<char const *> pointers;
    if (!SDL_WasInit(SDL_INIT_AUDIO)) SDL_InitSubSystem(SDL_INIT_AUDIO);
    list.clear();
    int const n = SDL_GetNumAudioDevices(1);
    for (int i = 0; i < n; ++i)
        if (char const *name = SDL_GetAudioDeviceName(i, 1)) list.emplace_back(name);
    pointers.clear();
    for (auto const &name : list) pointers.push_back(name.c_str());
    *names = pointers.data();
    return int(pointers.size());
}

void Voice_RestartCapture(void) { closeCapture(); capture.retryAt = 0; gateOpen = false; }

// Refreshed every frame the voice menu shows; lapses half a second after it closes.
void Voice_SetMenuMonitor(bool on)
{
    if (on && nowMs() > menuMonitorUntil) capture.retryAt = 0;
    menuMonitorUntil = on ? nowMs() + 500.0 : 0.0;
}

bool Voice_CaptureOpen(void) { return capture.device || capture.toneHz > 0; }

float Voice_InputLevel(void)
{
    // Mean absolute amplitude as a 60 dB meter.
    float const db = 20.f * std::log10(std::max(vad.meter, 1.f) / 32768.f);
    return clamp((db + 60.f) / 60.f, 0.f, 1.f);
}

bool Voice_InputGateOpen(void) { return gateOpen; }

void Voice_Frame(void)
{
    if (g_networkMode == NET_DEDICATED_SERVER) return;
    // Push-to-talk: the bound Push_To_Talk keys (or a mouse/controller button), not while typing.
    {
        auto const &keys = ud.config.KeyboardKeys[gamefunc_Push_To_Talk];
        bool const typing = (g_player[myconnectindex].ps->gm & MODE_TYPE) || (osd && (osd->flags & OSD_CAPTURE));
        bool const key = (keys[0] != 0xff && keys[0] != sc_None && KB_KeyPressed(keys[0]))
            || (keys[1] != 0xff && keys[1] != sc_None && KB_KeyPressed(keys[1]))
            || (voice_ptt_key > 0 && voice_ptt_key < 256 && KB_KeyPressed(voice_ptt_key));
        pushToTalk = !typing && (key || BUTTON(gamefunc_Push_To_Talk));
    }
    processCapture();
    double const now = nowMs();
    if (std::getenv("EDUKE32_VOICE_TEST_LOG") || std::getenv("EDUKE32_VOICE_TEST_DUMP") || std::getenv("EDUKE32_VOICE_TEST_TONE"))
    {
        static double lastStats;
        if (now - lastStats > 3000.0)
        {
            lastStats = now;
            LOG_F(INFO, "Voice stats: sent=%u received=%u decoded=%u concealed=%u transport=%d transmitting=%d vad=%d level=%.0f noise=%.0f.",
                  statSent, statReceived, statDecoded, statConcealed, Net_VoiceAvailable(), transmitting, vad.active, vad.meter, vad.noise);
            for (auto &sp : speakers) if (sp.dump) std::fflush(sp.dump);
        }
    }
    for (int i = 0; i < MaxSpeakers; ++i)
    {
        if (!speakers[i].decoder) continue;
        decodeSpeaker(i, now);
        updatePlayback(i, now);
    }
}

void Voice_DrawStatus(bool wrist)
{
    if (!voice_hud || !(Net_VoiceAvailable() || voice_loopback)) return;
    struct Line { char text[64]; int pal; } lines[MaxSpeakers + 1];
    int count = 0;
    if (transmitAllowed())
    {
        Bstrcpy(lines[count].text, transmitting ? "^10MIC LIVE" : voice_mode ? "^12MIC (PUSH TO TALK)" : "^12MIC READY");
        lines[count++].pal = 0;
    }
    for (int i = 0; i < MaxSpeakers; ++i)
    {
        if (i == myconnectindex || !Voice_IsTalking(i)) continue;
        Bsnprintf(lines[count].text, sizeof(lines[count].text), "> %s", g_player[i].user_name);
        lines[count++].pal = g_player[i].ps ? g_player[i].ps->palookup : 0;
    }
    // Flat: top left, mic first. Headset: on the left wrist HUD, stacked upward from just above the
    // health readout (which starts at y 175), the mic line nearest it.
    for (int i = 0; i < count; ++i)
        minitext(4, wrist ? 167 - 8*i : 30 + 8*i, lines[i].text, lines[i].pal, 2 + 8 + 16 + 256);
}

#endif
