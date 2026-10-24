"""Shell analysis of an original (v6) single-surface MD3: which closed shells it has and in which frames
each one is shown (pure numpy).

parts(md3) -> dict(frames, tag_order, tags[frame]{name: xyz metres}, tags_constant,
                   shells=[dict(verts (index array), tris (index array), shown[frame] bool, extent[frame] m,
                                centre[frame] metres, ref (frame index where the shell is largest))],
                   body (index of the main shell))
Shells are found by welding vertices by their quantised positions over ALL frames (a vertex that only
coincides with another in some frames is a different vertex), then joining triangles that share welded
vertices. A shell is "shown" in a frame when its extent is above 0.5 mm (v6 hides effects by collapsing
them to a point). The body is the shell with the largest rest-frame surface area.
"""
import numpy as np
from md3np import read

SHOWN_M = 0.0005


def _components(tris, nv):
    par = np.arange(nv)

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for a, b, c in tris:
        ra, rb, rc = find(a), find(b), find(c)
        par[rb] = ra
        par[find(rc)] = ra
    return np.array([find(x) for x in range(nv)])


def tri_area(P, tris):
    return 0.5 * np.linalg.norm(np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]]), axis=1)


def parts(path):
    m = read(path)
    assert m['num_surfaces'] == 1, (path, m['num_surfaces'])
    s = m['surfaces'][0]
    X = s['xyz'] / 64.0                                   # [nf, nv, 3] metres
    nf, nv = X.shape[:2]
    key = np.round(np.transpose(X, (1, 0, 2)).reshape(nv, -1) * 64 * 64).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    tris = s['tris'].astype(np.int64)
    root = _components(inv[tris], inv.max() + 1)
    comp_of_vert = root[inv]
    shells = []
    for r in np.unique(comp_of_vert):
        vi = np.nonzero(comp_of_vert == r)[0]
        ti = np.nonzero(comp_of_vert[tris[:, 0]] == r)[0]
        ext = np.array([float(np.ptp(X[f, vi], 0).max()) for f in range(nf)])
        cen = np.array([(X[f, vi].min(0) + X[f, vi].max(0)) / 2 for f in range(nf)])
        shells.append(dict(verts=vi, tris=ti, shown=ext > SHOWN_M, extent=ext, centre=cen, ref=int(np.argmax(ext)),
                           area=float(tri_area(X[int(np.argmax(ext))], tris[ti]).sum())))
    body = int(np.argmax([sh['area'] if sh['shown'][0] else 0.0 for sh in shells]))
    tag_order = list(m['tags'][0].keys())
    tags = [{k: np.array(v['origin']) / 64.0 for k, v in m['tags'][f].items()} for f in range(nf)]
    const = all(np.allclose(tags[f][k], tags[0][k], atol=1e-6) for f in range(nf) for k in tag_order)
    return dict(frames=[f['name'] for f in m['frames']], tag_order=tag_order, tags=tags, tags_constant=const,
                shells=shells, body=body, X=X, tris=tris, st=np.asarray(s['st'], float), md3=m)
