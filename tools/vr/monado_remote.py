#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Local test client for Monado's native ``mndrmt3`` remote debug devices.

Layout reference: Monado src/xrt/drivers/remote/r_interface.h (BSL-1.0).
This test-only native-endian protocol is unrelated to EDuke32's game protocol.
Only loopback connections are permitted. A private remote-driver runtime must
already be running; this module never changes the user's runtime/configuration.
"""
import ctypes as c
import socket
import sys


class Vec3(c.Structure):
    _fields_ = [(name, c.c_float) for name in ('x', 'y', 'z')]


class Quat(c.Structure):
    _fields_ = [(name, c.c_float) for name in ('x', 'y', 'z', 'w')]


class Pose(c.Structure):
    _fields_ = [('orientation', Quat), ('position', Vec3)]


class Vec2(c.Structure):
    _fields_ = [('x', c.c_float), ('y', c.c_float)]


class Fov(c.Structure):
    _fields_ = [(name, c.c_float) for name in ('angle_left', 'angle_right', 'angle_up', 'angle_down')]


class View(c.Structure):
    _fields_ = [('fov', Fov), ('pose', Pose), ('_pad', c.c_uint32)]


class Head(c.Structure):
    _fields_ = [('views', View * 2), ('center', Pose), ('per_view_data_valid', c.c_bool),
                ('_pad0', c.c_bool), ('_pad1', c.c_bool), ('_pad2', c.c_bool)]


class Hand(c.Structure):
    _fields_ = [('pose', Pose), ('linear_velocity', Vec3), ('angular_velocity', Vec3),
                ('hand_curl', c.c_float * 5), ('trigger_value', c.c_float),
                ('squeeze_value', c.c_float), ('squeeze_force', c.c_float),
                ('thumbstick', Vec2), ('trackpad_force', c.c_float), ('trackpad', Vec2)] + [
                    (name, c.c_bool) for name in (
                        'hand_tracking_active', 'active', 'system_click', 'system_touch',
                        'a_click', 'a_touch', 'b_click', 'b_touch', 'trigger_click', 'trigger_touch',
                        'thumbstick_click', 'thumbstick_touch', 'trackpad_touch', '_pad0', '_pad1', '_pad2')]


class Packet(c.Structure):
    _fields_ = [('header', c.c_uint64), ('head', Head), ('left', Hand), ('right', Hand)]


class Remote:
    def __init__(self, port, timeout=3):
        if sys.byteorder != 'little' or (c.sizeof(Head), c.sizeof(Hand), c.sizeof(Packet)) != (128, 120, 376):
            raise RuntimeError('unsupported native Monado remote protocol layout')
        self.socket = socket.create_connection(('127.0.0.1', port), timeout=timeout)
        try:
            self.reset = self._receive()
            self.packet = self._receive()
        except Exception:
            self.socket.close()
            raise

    def _receive(self):
        data = bytearray()
        while len(data) < c.sizeof(Packet):
            chunk = self.socket.recv(c.sizeof(Packet) - len(data))
            if not chunk:
                raise RuntimeError('remote runtime closed during handshake')
            data.extend(chunk)
        if bytes(data[:8]) != b'mndrmt3\0':
            raise RuntimeError('remote runtime protocol version mismatch')
        return Packet.from_buffer_copy(data)

    def send(self):
        self.socket.sendall(bytes(self.packet))

    def neutral(self):
        # Restore the runtime-provided poses and release every test control.
        self.packet = Packet.from_buffer_copy(bytes(self.reset))
        self.send()

    def close(self):
        try:
            self.neutral()
        finally:
            self.socket.close()

    def __enter__(self):
        self.neutral()
        return self

    def __exit__(self, *_):
        self.close()
