// SPDX-License-Identifier: GPL-2.0-only
// What Proton's steam.exe does before a VR game starts: wineopenxr fills the registry (the active
// OpenXR runtime and the Vulkan extensions the host runtime needs). Build:
//   x86_64-w64-mingw32-gcc -O2 -o xr_init_registry.exe xr_init_registry.c
#include <windows.h>
#include <stdio.h>

int main(void)
{
    HMODULE xr = LoadLibraryA("wineopenxr.dll");
    if (!xr) { printf("xr_init_registry: no wineopenxr.dll (error %lu)\n", GetLastError()); return 1; }
    typedef int (WINAPI *init_fn)(void);
    init_fn init = (init_fn)GetProcAddress(xr, "wineopenxr_init_registry");
    if (!init) { printf("xr_init_registry: wineopenxr_init_registry missing\n"); return 2; }
    int status = init();
    printf("xr_init_registry: status %d\n", status);
    return 0;
}
