#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Summarise an EDUKE32_XR_PROFILE dump: profile_report.py DUMP BINARY [N].

Symbolizes the game's own frames with addr2line and prints the top N functions by inclusive and
self samples (percent of main-thread CPU samples)."""
import collections, subprocess, sys

dump, binary = sys.argv[1], sys.argv[2]
top = int(sys.argv[3]) if len(sys.argv) > 3 else 40
stacks = [line.split() for line in open(dump) if line.strip()]
offsets = sorted({f.split('+')[1] for s in stacks for f in s if '+' in f and f.split('+')[0].endswith(binary.split('/')[-1])})
names = {}
if offsets:
    # return addresses point after the call: look up address-1
    out = subprocess.run(['addr2line', '-f', '-C', '-e', binary] + [hex(int(o, 16) - 1) for o in offsets],
                         capture_output=True, text=True).stdout.split('\n')
    for i, o in enumerate(offsets):
        names[o] = out[2 * i] if 2 * i < len(out) else o


def name(frame):
    if '+' in frame:
        module, offset = frame.split('+')
        if module.endswith(binary.split('/')[-1]):
            return names.get(offset, frame)
        return module.split('/')[-1]
    return frame


inclusive, self_ = collections.Counter(), collections.Counter()
for s in stacks:
    seq = [name(f) for f in s]
    if seq and seq[0] == 'libc.so.6':   # the signal return trampoline
        seq = seq[1:]
    if seq:
        self_[seq[0]] += 1
    for n in set(seq):
        inclusive[n] += 1
total = len(stacks) or 1
print(f'{len(stacks)} samples')
print('--- inclusive')
for n, c in inclusive.most_common(top):
    print(f'{100 * c / total:5.1f}% {n}')
print('--- self')
for n, c in self_.most_common(top // 2):
    print(f'{100 * c / total:5.1f}% {n}')
