"""Shared layout, color, and building-label constants for the GUI."""

WINDOW_SIZE = (1080, 660)
# 棋盘格坐标统一由左上角像素位置和单格边长换算，供绘制与鼠标命中共用。
BOARD_LEFT, BOARD_TOP, CELL = 35, 132, 53
PANEL_LEFT = 720
FPS = 60

# 界面调色板：地形、电网、敌人和供电状态使用固定颜色，避免各视图重复定义。
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

# 每项依次为建造类型、按钮文字、棋盘符号和符号底色。
BUILD_KINDS = (
    ("mine", "Mine", "M", (211, 173, 75)),
    ("power_plant", "Power Plant", "P", (93, 191, 127)),
    ("power_node", "Power Node", "N", (81, 173, 190)),
    ("gun_tower", "Gun Tower", "G", (112, 152, 227)),
    ("cannon_tower", "Cannon Tower", "A", (203, 127, 83)),
    ("slow_tower", "Slow Tower", "S", (167, 126, 213)),
)
SYMBOL_COLORS = {symbol: color for _, _, symbol, color in BUILD_KINDS}
# 核心不在建造菜单中，但也需要独立的棋盘标识色。
SYMBOL_COLORS["C"] = (94, 216, 172)
