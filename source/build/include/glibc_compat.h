// SPDX-License-Identifier: GPL-2.0-only
// Portable Linux release builds (make ... PORTABLE_GLIBC=1, x86_64): bind math and strtol-family
// calls to their long-standing glibc symbol versions instead of the newest ones a recent toolchain
// picks (GLIBC_2.43 float math, GLIBC_2.38 C23 strtol/scanf aliases, ...), so the game runs on
// older distributions. Same behaviour: these versions only differ in errno/C23 corner cases.
#if defined __linux__ && defined __x86_64__
# include <features.h>
#endif
#if defined __linux__ && defined __x86_64__ && defined __GLIBC__
__asm__(".symver acosf,acosf@GLIBC_2.2.5");
__asm__(".symver atan2f,atan2f@GLIBC_2.2.5");
__asm__(".symver log10f,log10f@GLIBC_2.2.5");
__asm__(".symver remainderf,remainderf@GLIBC_2.2.5");
__asm__(".symver sqrtf,sqrtf@GLIBC_2.2.5");
__asm__(".symver fmod,fmod@GLIBC_2.2.5");
__asm__(".symver fmodf,fmodf@GLIBC_2.2.5");
__asm__(".symver hypot,hypot@GLIBC_2.2.5");
__asm__(".symver hypotf,hypotf@GLIBC_2.2.5");
__asm__(".symver __isoc23_fscanf,__isoc99_fscanf@GLIBC_2.7");
__asm__(".symver __isoc23_sscanf,__isoc99_sscanf@GLIBC_2.7");
__asm__(".symver __isoc23_strtol,strtol@GLIBC_2.2.5");
__asm__(".symver __isoc23_strtoll,strtoll@GLIBC_2.2.5");
__asm__(".symver __isoc23_strtoul,strtoul@GLIBC_2.2.5");
__asm__(".symver __isoc23_strtoull,strtoull@GLIBC_2.2.5");
#endif
