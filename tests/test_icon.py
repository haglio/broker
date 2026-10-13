from __future__ import annotations

from PyQt6.QtGui import QIcon

from osr2_broker.win32 import ICON_PATH

INSET = 31
CELL = (256 - 2 * INSET) / 5


def _letter_drawn_in(image) -> list[str]:
    return ["".join("#" if image.pixelColor(int(INSET + (column + 0.5) * CELL),
                                            int(INSET + (row + 0.5) * CELL)).alpha() > 128
                    else "." for column in range(5))
            for row in range(5)]


def test_the_broker_s_b_has_no_right_hand_corners_so_it_reads_as_a_b_not_an_8(qapp):
    image = QIcon(str(ICON_PATH)).pixmap(256, 256).toImage()

    assert _letter_drawn_in(image) == ["####.", "#...#", "#####", "#...#", "####."]
