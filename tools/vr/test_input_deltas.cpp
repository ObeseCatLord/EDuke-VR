// SPDX-License-Identifier: GPL-2.0-only
// Focused CPU checks for the native input accumulation helpers in player.h.
// c++ -std=c++17 -Wall -Wextra -Werror -Wno-attributes -funsigned-char
// -DRENDERTYPESDL=1 -DSDL_TARGET=2 -D_GNU_SOURCE=1 -D_REENTRANT -pthread
// -fsanitize=address,undefined -fno-omit-frame-pointer -Isource/duke3d/src
// -Isource/build/include -Isource/mact/include -Isource/audiolib/include
// -Isource/glad/include -Isource/voidwrap/include -Isource/imgui/include
// -I/usr/include/SDL2 tools/vr/test_input_deltas.cpp -o work/native-input-delta-test/test_input_deltas
#include <climits>
#include <cstddef>
#include <cstdio>
#include <cstdlib>

#include "player.h"

#define EXPECT(condition)                                                                    \
    do                                                                                       \
    {                                                                                        \
        if (!(condition))                                                                    \
        {                                                                                    \
            std::fprintf(stderr, "%s:%d: expectation failed: %s\n", __FILE__, __LINE__, #condition); \
            return EXIT_FAILURE;                                                            \
        }                                                                                    \
    } while (0)

static input_t MakeInput(uint32_t bits, int16_t fvel, int16_t svel, fix16_t yaw, fix16_t pitch,
                         uint32_t extbits)
{
    return { bits, fvel, svel, yaw, pitch, extbits };
}

int main()
{
    static_assert(sizeof(input_t) == 20, "input_t is a packed 20-byte wire value");
    static_assert(offsetof(input_t, bits) == 0, "input_t bits offset changed");
    static_assert(offsetof(input_t, fvel) == 4, "input_t fvel offset changed");
    static_assert(offsetof(input_t, svel) == 6, "input_t svel offset changed");
    static_assert(offsetof(input_t, q16avel) == 8, "input_t yaw offset changed");
    static_assert(offsetof(input_t, q16horz) == 12, "input_t pitch offset changed");
    static_assert(offsetof(input_t, extbits) == 16, "input_t extbits offset changed");

    input_t pending{};
    input_t const first = MakeInput(0x01u, 100, -50, 120, -30, 0x10u);
    input_t const second = MakeInput(0x04u, -200, 75, -45, 55, 0x80u);
    P_AccumulateInput(&pending, &first);
    P_AccumulateInput(&pending, &second);
    EXPECT(pending.q16avel == 75);
    EXPECT(pending.q16horz == 25);
    EXPECT(pending.bits == 0x04u);
    EXPECT(pending.fvel == -200);
    EXPECT(pending.svel == 75);
    EXPECT(pending.extbits == 0x80u);

    // A later packet may update held fields without replacing accumulated motion.
    input_t const heldOnly = MakeInput(0x20u, 12, -13, 0, 0, 0x200u);
    P_AccumulateInput(&pending, &heldOnly);
    EXPECT(pending.q16avel == 75);
    EXPECT(pending.q16horz == 25);
    EXPECT(pending.bits == 0x20u);
    EXPECT(pending.fvel == 12);
    EXPECT(pending.svel == -13);
    EXPECT(pending.extbits == 0x200u);

    // Sending a tick copies its deltas, then clearing consumes them exactly once.
    input_t const sentTick = pending;
    P_ClearInputDeltas(&pending);
    EXPECT(sentTick.q16avel == 75);
    EXPECT(sentTick.q16horz == 25);
    EXPECT(pending.q16avel == 0);
    EXPECT(pending.q16horz == 0);
    EXPECT(pending.bits == sentTick.bits);
    EXPECT(pending.fvel == sentTick.fvel);
    EXPECT(pending.svel == sentTick.svel);
    EXPECT(pending.extbits == sentTick.extbits);

    // With no packet on the next tick, angular deltas remain consumed while held state remains.
    input_t const nextTick = pending;
    EXPECT(nextTick.q16avel == 0);
    EXPECT(nextTick.q16horz == 0);
    EXPECT(nextTick.bits == 0x20u);
    EXPECT(nextTick.fvel == 12);
    EXPECT(nextTick.svel == -13);
    EXPECT(nextTick.extbits == 0x200u);

    EXPECT(P_AddInputDelta(17, -31) == -14);
    EXPECT(P_AddInputDelta(-17, 31) == 14);
    EXPECT(P_AddInputDelta(INT32_MIN, 0) == INT32_MIN);
    EXPECT(P_AddInputDelta(0, INT32_MIN) == INT32_MIN);
    EXPECT(P_AddInputDelta(INT32_MIN, 1) == INT32_MIN + 1);
    EXPECT(P_AddInputDelta(INT32_MIN, -1) == INT32_MIN);
    EXPECT(P_AddInputDelta(INT32_MAX, 1) == INT32_MAX);
    EXPECT(P_AddInputDelta(INT32_MAX - 1, 1) == INT32_MAX);
    EXPECT(P_AddInputDelta(INT32_MAX, INT32_MAX) == INT32_MAX);
    EXPECT(P_AddInputDelta(INT32_MIN, INT32_MIN) == INT32_MIN);

    return EXIT_SUCCESS;
}
