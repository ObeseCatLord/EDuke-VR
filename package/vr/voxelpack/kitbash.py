"""Kitbash: compose a new voxel model from pieces of the Voxel Duke Nukem 3D voxels (pure numpy).

A Kit is a palette-index grid in KVX convention (x, y horizontal, z DOWN), grown as pieces are pasted.
Pieces are cut from source KVX files with boxes, turned with axis permutations / flips, stretched or
shortened by repeating / dropping slices, recoloured, and pasted at integer voxel offsets. Every voxel
keeps its source colour (mapped to the Duke Nukem 3D palette), so the result is made of Cheello's voxels
only; nothing is resampled unless a piece asks for `downsample`.

Every piece used is recorded (file, box, operations, offset) so the build record can list the sources.
"""
import numpy as np
from kvx import read_kvx, fill_solid

_CACHE = {}


def load(root, rel):
    key = (str(root), rel)
    if key not in _CACHE:
        _CACHE[key] = read_kvx(root / f'{rel}.kvx')
    return _CACHE[key]


def nearest_index(rgb, palette):
    """uint8 [..., 3] colours -> nearest palette index (Euclidean RGB, no dithering)."""
    flat = rgb.reshape(-1, 3).astype(np.int32)
    pal = palette.astype(np.int32)
    out = np.empty(len(flat), np.int16)
    for i in range(0, len(flat), 4096):
        d = ((flat[i:i + 4096, None, :] - pal[None]) ** 2).sum(-1)
        out[i:i + 4096] = d.argmin(1)
    return out.reshape(rgb.shape[:-1])


class Piece:
    """A cut-out of one source voxel, as a colour grid (uint8 rgb) and occupancy."""

    def __init__(self, root, rel, box=None, keep=None):
        k = load(root, rel)
        g = k['grid']
        sl = tuple(slice(lo, hi + 1) for lo, hi in (box or [(0, n - 1) for n in g.shape]))
        self.grid = g[sl].copy()
        self.rgb = k['palette'][np.clip(self.grid, 0, 255)]
        self.occ = self.grid >= 0
        if keep is not None:          # callable(rgb, idx grid) -> bool mask of voxels to keep
            self.occ &= keep(self.rgb, np.indices(self.grid.shape).transpose(1, 2, 3, 0) +
                             np.array([b[0] for b in (box or [(0, 0)] * 3)]))
        self.log = dict(source=f'voxels/{rel}.kvx', box=[list(b) for b in box] if box else None, ops=[])

    def _apply(self, f, note):
        self.rgb, self.occ = f(self.rgb), f(self.occ)
        self.log['ops'].append(note)
        return self

    def orient(self, perm, flip=()):
        """New axis i = old axis perm[i]; then flip the listed NEW axes."""
        def f(a):
            a = np.transpose(a, tuple(perm) + ((3,) if a.ndim == 4 else ()))
            for ax in flip:
                a = np.flip(a, ax)
            return np.ascontiguousarray(a)
        return self._apply(f, f'orient{tuple(perm)} flip{tuple(flip)}')

    def stretch(self, axis, lo, hi, times=1):
        """Repeat slices lo..hi (inclusive, along `axis`) `times` more times (a longer tank / barrel)."""
        def f(a):
            idx = list(range(0, hi + 1)) + list(range(lo, hi + 1)) * times + list(range(hi + 1, a.shape[axis]))
            return np.take(a, idx, axis=axis)
        return self._apply(f, f'stretch axis{axis} {lo}..{hi} x{times}')

    def drop(self, axis, lo, hi):
        """Remove slices lo..hi (a shorter handle)."""
        def f(a):
            idx = [i for i in range(a.shape[axis]) if not lo <= i <= hi]
            return np.take(a, idx, axis=axis)
        return self._apply(f, f'drop axis{axis} {lo}..{hi}')

    def extrude(self, axis, n, at_low=True):
        """Add n slices on one side of `axis`, copying the outermost slice's voxels (a deeper body)."""
        def f(a):
            edge = np.take(a, [0 if at_low else a.shape[axis] - 1], axis=axis)
            rep = np.repeat(edge, n, axis=axis)
            return np.concatenate([rep, a] if at_low else [a, rep], axis=axis)
        return self._apply(f, f'extrude axis{axis} {n} {"low" if at_low else "high"}')

    def recolour(self, fn, note):
        """fn(rgb uint8 [...,3], occ) -> new rgb."""
        self.rgb = fn(self.rgb, self.occ).astype(np.uint8)
        self.log['ops'].append(f'recolour: {note}')
        return self

    def downsample(self, f, occ_frac=0.375):
        """f x f x f blocks: solid when >= occ_frac occupied, colour = the block's most common stored colour."""
        pads = [(0, (-n) % f) for n in self.occ.shape]
        O = np.pad(self.occ, pads)
        C = np.pad(self.rgb, pads + [(0, 0)])
        X, Y, Z = (n // f for n in O.shape)
        ob = O.reshape(X, f, Y, f, Z, f).transpose(0, 2, 4, 1, 3, 5).reshape(X, Y, Z, -1)
        cb = C.reshape(X, f, Y, f, Z, f, 3).transpose(0, 2, 4, 1, 3, 5, 6).reshape(X, Y, Z, -1, 3)
        occ = ob.mean(-1) >= occ_frac
        key = cb[..., 0].astype(np.int32) * 65536 + cb[..., 1].astype(np.int32) * 256 + cb[..., 2]
        rgb = np.zeros((X, Y, Z, 3), np.uint8)
        for i, j, k in np.argwhere(occ):
            kk = key[i, j, k][ob[i, j, k]]
            v, c = np.unique(kk, return_counts=True)
            best = int(v[np.argmax(c)])
            rgb[i, j, k] = (best >> 16, (best >> 8) & 255, best & 255)
        self.occ, self.rgb = occ, rgb
        self.log['ops'].append(f'downsample {f} (occupancy >= {occ_frac}, majority colour)')
        return self

    @property
    def shape(self):
        return self.occ.shape


class Kit:
    def __init__(self):
        self.vox = {}            # (x, y, z) -> rgb tuple
        self.pieces = []
        self.marks = {}          # named boxes (in kit coordinates) for the weapon spec

    def paste(self, piece, at, name=None, under=False):
        """Paste piece with its (0,0,0) at kit coordinate `at`. under=True keeps voxels already there."""
        at = np.asarray(at, int)
        idx = np.argwhere(piece.occ)
        for p in idx:
            key = tuple(int(v) for v in p + at)
            if under and key in self.vox:
                continue
            self.vox[key] = tuple(int(c) for c in piece.rgb[tuple(p)])
        lo = at
        hi = at + np.array(piece.shape) - 1
        if name:
            self.marks[name] = (lo.tolist(), hi.tolist())
        self.pieces.append(dict(name=name, at=at.tolist(), size=list(piece.shape), **piece.log))
        return lo, hi

    def remove(self, fn):
        """Drop voxels where fn(x, y, z, rgb) is true."""
        for key in [k for k, c in self.vox.items() if fn(*k, c)]:
            del self.vox[key]

    def grid(self, palette):
        """-> read_kvx-like dict in KVX convention, origin shifted to 0; `shift` = kit -> grid offset."""
        P = np.array(list(self.vox.keys()))
        lo = P.min(0)
        size = P.max(0) - lo + 1
        g = np.full(tuple(size), -1, np.int16)
        cols = np.array(list(self.vox.values()), np.uint8)
        g[tuple((P - lo).T)] = nearest_index(cols, palette[:255])
        solid = fill_solid(g >= 0)
        # hidden interior cells take the nearest stored colour (never seen; keeps patches clean)
        from scipy import ndimage
        _, ind = ndimage.distance_transform_edt(g < 0, return_indices=True)
        g = np.where(solid, g[tuple(ind)], -1).astype(np.int16)
        return dict(grid=g, solid=solid, palette=palette, size=tuple(int(v) for v in size),
                    pivot=tuple(float(v) / 2 for v in size), shift=(-lo).tolist())

    def box(self, name, shift, pad=(0, 0, 0)):
        lo, hi = self.marks[name]
        return {a: (lo[i] + shift[i] - pad[i], hi[i] + shift[i] + pad[i]) for i, a in enumerate('xyz')}


class Shape(Piece):
    """A small procedural piece (occupancy + colours chosen from voxel colours), e.g. a button cap."""

    def __init__(self, occ, rgb, note):
        self.occ = np.asarray(occ, bool)
        self.rgb = np.asarray(rgb, np.uint8)
        self.grid = np.where(self.occ, 0, -1).astype(np.int16)
        self.log = dict(source='procedural', box=None, ops=[note])


def ramp(rgb, occ, select):
    """Colours of the selected voxels sorted dark -> light (unique), e.g. a piece's red ramp."""
    c = rgb[occ & select(rgb.astype(int))]
    u = np.unique(c.reshape(-1, 3), axis=0)
    return u[np.argsort(u.astype(int).sum(1))]


def by_luminance(rgb, ramp_cols):
    """Each colour -> the ramp colour of the nearest luminance."""
    lum = rgb.astype(int).sum(-1)
    rl = ramp_cols.astype(int).sum(-1)
    return ramp_cols[np.abs(lum[..., None] - rl).argmin(-1)]
