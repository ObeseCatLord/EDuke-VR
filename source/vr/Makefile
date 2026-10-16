# SPDX-License-Identifier: GPL-2.0-only
# Standalone diagnostic build; the EDuke32 build supplies these objects separately.
CXX ?= c++
PKG_CONFIG ?= pkg-config
CXXFLAGS ?= -O2 -g
CXXFLAGS += -std=c++17 -DGL_GLEXT_PROTOTYPES
CPPFLAGS += $(shell $(PKG_CONFIG) --cflags sdl2 openxr gl x11)
LDLIBS += $(shell $(PKG_CONFIG) --libs sdl2 openxr gl x11)

.PHONY: all clean
all: xr_smoke

xr_smoke: eduke_xr.o xr_smoke.o
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)

eduke_xr.o: eduke_xr.cpp eduke_xr.h ../build/include/polymost_color_correction.h
xr_smoke.o: xr_smoke.cpp eduke_xr.h

clean:
	rm -f xr_smoke *.o
