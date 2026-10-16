// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <cstdint>
#ifdef USE_OPENXR
// Experimental ordinary-room stereo oracle. True means the logical room pass
// was consumed, including failures after animation (never repeat CON effects).
bool G_XRDrawRooms(int32_t smoothRatio);
void G_XRTestAnimationInputs();
bool G_XRCanAppendSprite(int32_t limit);
void G_XRInheritSprite(int32_t destination, int32_t parent);
#endif
