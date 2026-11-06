"""Pure layout maths and focus state for the card grid."""
from __future__ import annotations

# A card is two 10:9 panels side by side (Render | Sees) over a text block 0.75 of a
# frame tall, so card aspect = 2*10 : (9 + 0.75*9) = 20 : 15.75 = 80 : 63.
CARD_ASPECT = (80, 63)


def grid(n: int, width: int, height: int, aspect: tuple[int, int] = CARD_ASPECT) -> tuple[int, int, int, int]:
    """Return (cols, rows, card_w, card_h) maximising card area for ``n`` cards.

    ``aspect`` is the card's (width, height) in arbitrary units; cards keep that
    aspect and the grid reflows to the column count with the largest total card area."""
    if n <= 0:
        return (0, 0, 0, 0)
    ratio = aspect[1] / aspect[0]  # card_h / card_w
    best = (0.0, 1, n, 0, 0)
    for cols in range(1, n + 1):
        rows = -(-n // cols)
        card_w = int(min(width / cols, height / (rows * ratio)))
        card_h = int(card_w * ratio)
        area = card_w * card_h
        if area > best[0]:
            best = (area, cols, rows, card_w, card_h)
    _, cols, rows, card_w, card_h = best
    return cols, rows, card_w, card_h


class FocusState:
    def __init__(self) -> None:
        self.focused: str | None = None

    def focus(self, agent_id: str) -> None:
        self.focused = agent_id

    def back(self) -> None:
        self.focused = None

    def toggle(self, agent_id: str) -> None:
        """Double-click: focusing the focused card returns to multi-view."""
        self.focused = None if self.focused == agent_id else agent_id
