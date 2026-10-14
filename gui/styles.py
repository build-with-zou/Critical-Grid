"""Shared layout, color, and building-label constants for the GUI."""

WINDOW_SIZE = (1080, 660)
# Drawing and mouse hit detection share this board origin and cell size.
BOARD_LEFT, BOARD_TOP, CELL = 35, 132, 53
PANEL_LEFT = 720
FPS = 60

# Shared colors for terrain, the power grid, enemies, and charge status.
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
CHARGED_COLOR = (83, 220, 155)
UNCHARGED_COLOR = (243, 103, 101)
ENEMY_COLOR = (235, 105, 91)
ENEMY_COLORS = {
    "Basic": ENEMY_COLOR,
    "Fast": (245, 186, 83),
    "Armored": (162, 173, 203),
    "Saboteur": (197, 113, 206),
}

# Each entry contains the build kind, button label, board symbol, and symbol color.
BUILD_KINDS = (
    ("mine", "Mine", "M", (211, 173, 75)),
    ("power_plant", "Power Plant", "P", (93, 191, 127)),
    ("power_node", "Power Node", "N", (81, 173, 190)),
    ("gun_tower", "Gun Tower", "G", (112, 152, 227)),
    ("cannon_tower", "Cannon Tower", "A", (203, 127, 83)),
    ("slow_tower", "Slow Tower", "S", (167, 126, 213)),
)
SYMBOL_COLORS = {symbol: color for _, _, symbol, color in BUILD_KINDS}
# The core is not buildable but still needs its own board color.
SYMBOL_COLORS["C"] = (94, 216, 172)
