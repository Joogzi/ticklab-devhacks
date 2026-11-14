"""World fixtures. `flat_stone_v1`: stone floor (top at y=100) covering x,z in [-48, 49), air above."""
from .fmath import f32

STONE_FRICTION = f32(0.6)


class World:
    def __init__(self, fixture: str = "flat_stone_v1"):
        if fixture not in ("flat_stone_v1", "stone_platform_v1"):
            raise ValueError(f"unknown fixture {fixture!r}")
        self.fixture = fixture
        # (min_x, min_y, min_z, max_x, max_y, max_z): one merged box for the whole floor layer
        self.boxes = [(-48.0, 99.0, -48.0, 49.0, 100.0, 49.0)]

    def friction_below(self, x: float, y: float, z: float) -> float:
        return STONE_FRICTION
