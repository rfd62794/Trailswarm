from pokeagent.screencontext import MenuKind, ScreenType, classify_screen
from pokeagent.screentext import CHARMAP


def screen(*lines):
    inverse = {v: k for k, v in CHARMAP.items() if len(v) == 1}
    data = bytearray([0x7F] * 360)
    data[:2] = b'\x79\x7a'
    for r, text in enumerate(lines, 1):
        row = bytes([0x7C]) + bytes(inverse[c] for c in text) + bytes([0x7C])
        data[r * 20:r * 20 + len(row)] = row
    return bytes(data)


def test_unknown_does_not_invent_overworld():
    assert classify_screen(bytes(360)).screen == ScreenType.UNKNOWN
    assert classify_screen(b'').confidence == 0


def test_start_signature_and_battle_precedence():
    data = screen('POKEDEX', 'SAVE', 'OPTION')
    assert classify_screen(data).menu == MenuKind.START
    assert classify_screen(data, 1).screen == ScreenType.BATTLE


def test_shop_pc_and_battle_controls():
    assert classify_screen(screen('BUY SELL QUIT')).menu == MenuKind.SHOP
    assert classify_screen(screen('WITHDRAW ITEM', 'DEPOSIT')).menu == MenuKind.PC
    assert classify_screen(screen('FIGHT RUN'), 2).menu == MenuKind.BATTLE_COMMAND


def test_cursor_and_unknown_menu():
    data = bytearray(screen('HELLO'))
    data[42] = 0xED
    context = classify_screen(bytes(data))
    assert context.screen == ScreenType.MENU
    assert context.menu == MenuKind.UNKNOWN
    assert context.cursor == (2, 2)
    assert len(context.observation()) == 5
