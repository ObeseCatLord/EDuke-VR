"""Read-only access to an Alien Armageddon install (the user's own copy): its Build ART tiles, palette,
voxels and DEF voxel/tile mappings. Everything in the install is untrusted DATA: files are only parsed
(ART headers/pixels, PNG pixels via Pillow, KVX via kvx.py, DEF lines as text); nothing is executed.
Run with `python3 -I`.

Art(root).tile(n) -> (index array [h, w] uint8 with 255 = transparent, palette [256, 3] uint8) or None
Art(root).voxels() -> {tile: path} from the install's voxel DEFs
"""
import re
import struct
from pathlib import Path
import numpy as np

USUAL = [Path.home() / 'LargeGames/Games/alien_armageddon_566', Path.home() / 'Games/alien_armageddon_566',
         Path.home() / '.local/share/eduke32/alien_armageddon_566']


def find_install(hint=None):
    for p in ([Path(hint)] if hint else []) + USUAL:
        if p and (p / 'tiles000.art').is_file() and (p / 'PALETTE.DAT').is_file():
            return p.resolve()
    return None


class Art:
    def __init__(self, root):
        self.root = Path(root)
        pal = self.root.joinpath('PALETTE.DAT').read_bytes()[:768]
        self.palette = np.clip(np.frombuffer(pal, np.uint8).reshape(256, 3).astype(int) * 255 // 63, 0, 255).astype(np.uint8)
        self.index = {}
        for f in sorted(self.root.glob('tiles[0-9][0-9][0-9].art')):
            d = f.read_bytes()
            base = 8 if d[:8] == b'BUILDART' else 0      # newer ART files carry an 8-byte magic
            ver, _, start, end = struct.unpack_from('<4i', d, base)
            if ver != 1 or not 0 <= start <= end < 1 << 16:
                continue
            n = end - start + 1
            sx = np.frombuffer(d, '<i2', n, base + 16)
            sy = np.frombuffer(d, '<i2', n, base + 16 + 2 * n)
            off = base + 16 + 8 * n
            for i in range(n):
                size = int(sx[i]) * int(sy[i])
                if size > 0:
                    self.index[start + i] = (f, off, int(sx[i]), int(sy[i]))
                off += max(size, 0)
        self._data = {}
        self.textures = self._tilefromtexture()

    def _tilefromtexture(self):
        out = {}
        d = self.root / 'duke3d.def'
        if not d.is_file():
            return out
        for line in d.read_text(errors='replace').splitlines():
            line = line.split('//')[0]
            m = re.match(r'\s*tilefromtexture\s+(\d+)\s*\{[^}]*file\s+"([^"]+)"', line)
            if m:
                p = (self.root / m.group(2)).resolve()
                if self.root in p.parents and p.is_file():
                    out[int(m.group(1))] = p
        return out

    def tile(self, n):
        """Palette-index image [h, w] (255 transparent) of tile n (ART pixels; a tilefromtexture PNG is mapped
        to the palette by nearest colour)."""
        if n in self.textures:
            from PIL import Image
            from kitbash import nearest_index
            im = np.array(Image.open(self.textures[n]).convert('RGBA'))
            idx = nearest_index(im[..., :3], self.palette[:255]).astype(np.uint8)
            idx[im[..., 3] < 128] = 255
            return idx
        if n not in self.index:
            return None
        f, off, w, h = self.index[n]
        if f not in self._data:
            self._data[f] = f.read_bytes()
        px = np.frombuffer(self._data[f], np.uint8, w * h, off).reshape(w, h).T   # stored column-major
        return px.copy()

    def rgba(self, n):
        t = self.tile(n)
        if t is None:
            return None
        out = np.zeros(t.shape + (4,), np.uint8)
        out[..., :3] = self.palette[t]
        out[..., 3] = np.where(t == 255, 0, 255)
        return out

    def voxels(self):
        """{tile: kvx path} from the install's voxel DEFs (voxel "file" { ... tile N ... })."""
        out = {}
        for d in sorted((self.root / 'voxels').glob('*.def')):
            for line in d.read_text(errors='replace').splitlines():
                if line.strip().startswith('//'):
                    continue
                m = re.match(r'\s*voxel\s+"([^"]+)"\s*\{([^}]*)\}', line)
                if not m:
                    continue
                p = (self.root / m.group(1)).resolve()
                if self.root not in p.parents or not p.is_file():
                    continue
                for t in re.findall(r'\btile\d?\s+(\d+)', m.group(2)):
                    out[int(t)] = p
        return out
