"""World fixtures.

`flat_stone_v1`: stone floor (top at y=100) covering x,z in [-48, 49), air above.
`wall_v1`:       the same floor plus a stone wall, 3 blocks tall (y 100..103), filling the block row z = 4
                 (its near face is the plane z = 4) for x in [-48, 49).
"""
from .fmath import f32

STONE_FRICTION = f32(0.6)
FLOOR = (-48.0, 99.0, -48.0, 49.0, 100.0, 49.0)
WALL = (-48.0, 100.0, 4.0, 49.0, 103.0, 5.0)
FIXTURES = {"flat_stone_v1": [FLOOR], "stone_platform_v1": [FLOOR], "wall_v1": [FLOOR, WALL]}


class World:
    def __init__(self, fixture: str = "flat_stone_v1"):
        if fixture not in FIXTURES:
            raise ValueError(f"unknown fixture {fixture!r}")
        self.fixture = fixture
        # (min_x, min_y, min_z, max_x, max_y, max_z) solid boxes
        self.boxes = list(FIXTURES[fixture])

    def friction_below(self, x: float, y: float, z: float) -> float:
        return STONE_FRICTION
