"""Axis-separated AABB collision: Y first, then the larger horizontal axis, then the other."""

EPS = 1.0e-7
AXES = {"x": 0, "y": 1, "z": 2}


def make_box(x: float, y: float, z: float, half_w: float, height: float):
    return (x - half_w, y, z - half_w, x + half_w, y + height, z + half_w)


def offset(box, dx: float, dy: float, dz: float):
    return (box[0] + dx, box[1] + dy, box[2] + dz, box[3] + dx, box[4] + dy, box[5] + dz)


def _overlaps(box, other, axis: int) -> bool:
    for a in range(3):
        if a == axis:
            continue
        if not (box[a] + EPS < other[a + 3] and box[a + 3] - EPS > other[a]):
            return False
    return True


def clip_axis(box, obstacles, axis: int, d: float) -> float:
    """Largest movement along `axis` (signed, |result| <= |d|) that does not enter an obstacle."""
    if abs(d) < EPS:
        return 0.0
    for o in obstacles:
        if not _overlaps(box, o, axis):
            continue
        if d > 0 and box[axis + 3] - EPS <= o[axis]:
            d = min(d, o[axis] - box[axis + 3])
        elif d < 0 and box[axis] + EPS >= o[axis + 3]:
            d = max(d, o[axis + 3] - box[axis])
    return d


def axis_order(mx: float, mz: float):
    return ("y", "z", "x") if abs(mx) < abs(mz) else ("y", "x", "z")


def collide(box, movement, obstacles):
    """Return the collided movement vector (mx, my, mz)."""
    res = [0.0, 0.0, 0.0]
    for name in axis_order(movement[0], movement[2]):
        a = AXES[name]
        d = movement[a]
        if d != 0.0:
            res[a] = clip_axis(offset(box, *res), obstacles, a, d)
    return tuple(res)
