"""Shared layout, color, and building-label constants for the GUI."""

WINDOW_SIZE = (1080, 660)
BOARD_LEFT, BOARD_TOP, CELL = 35, 132, 53
PANEL_LEFT = 720
FPS = 60

BACKGROUND = (16, 23, 34)
PANEL = (25, 36, 51)
TEXT = (232, 239, 244)
MUTED = (156, 174, 188)
GRID_LINE = (62, 79, 92)
GROUND = (42, 58, 68)
ROUTE = (105, 88, 74)
MINE_SITE = (113, 92, 45)
HIGH_GROUND = (57, 80, 102)
POWER_LINE = (95, 189, 143)
ENEMY_COLOR = (235, 105, 91)
ENEMY_COLORS = {
    "Basic": ENEMY_COLOR,
    "Fast": (245, 186, 83),
    "Armored": (162, 173, 203),
    "Saboteur": (197, 113, 206),
}

BUILD_KINDS = (
    ("mine", "Mine", "M", (211, 173, 75)),
    ("power_plant", "Power Plant", "P", (93, 191, 127)),
    ("power_node", "Power Node", "N", (81, 173, 190)),
    ("gun_tower", "Gun Tower", "G", (112, 152, 227)),
    ("cannon_tower", "Cannon Tower", "A", (203, 127, 83)),
    ("slow_tower", "Slow Tower", "S", (167, 126, 213)),
)
SYMBOL_COLORS = {symbol: color for _, _, symbol, color in BUILD_KINDS}
SYMBOL_COLORS["C"] = (94, 216, 172)
