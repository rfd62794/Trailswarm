"""shop.buy: parsing helpers on a fake screen, the guard rails, and (if the ROM + checkpoint exist) the real Viridian Mart."""
from pathlib import Path

import pytest

from pokeagent.emulator import Button, FakeEmulator, PyBoyEmulator
from pokeagent.explorer import shop
from pokeagent.screentext import CHARMAP

REV = {v: k for k, v in CHARMAP.items() if len(v) == 1 and v.strip()}
ROOT = Path(__file__).resolve().parents[1]


def put(emu, row, col, text):
    for i, ch in enumerate(text):
        emu.set(shop.TILEMAP + row * 20 + col + i, shop.YEN if ch == "$" else 0x7F if ch == " " else REV[ch])


def test_quantity_box_reads_quantity_and_total_price():
    emu = FakeEmulator()
    assert shop.quantity_box(emu) is None
    put(emu, 16, 8, "x05 $1000")
    assert shop.quantity_box(emu) == (5, 1000)


def test_stock_reads_the_clerks_item_list_and_ignores_garbage():
    emu = FakeEmulator({shop.ITEM_STOCK: 3, shop.ITEM_STOCK + 1: 4, shop.ITEM_STOCK + 2: 11, shop.ITEM_STOCK + 3: 15})
    assert shop.stock(emu) == [4, 11, 15]
    assert shop.stock(FakeEmulator({shop.ITEM_STOCK: 200})) == []


def test_bad_quantity_and_no_clerk_menu_fail_without_buying():
    emu = FakeEmulator()
    assert shop.buy(emu, 4, 0).reason == "bad_quantity"
    assert shop.buy(emu, 4, 100).reason == "bad_quantity"
    res = shop.buy(emu, 4, 1)  # nothing on screen: never reaches the BUY menu, so it presses only A (then B to back out)
    assert not res.ok and res.reason == "no_buy_menu"
    assert set(emu.presses) <= {Button.A, Button.B} and res.presses <= shop.MAX_PRESSES


def _rom_emu(state):
    rom, st = ROOT / "roms" / "Pokemon Red.gb", ROOT / "runs" / "checkpoints" / f"{state}.state"
    if not (rom.exists() and st.exists()):
        pytest.skip("ROM or checkpoint not present")
    emu = PyBoyEmulator(rom, headless=True)
    emu.load_state(st)
    return emu


def test_buy_five_pokeballs_in_viridian_mart():
    emu = _rom_emu("oaks_parcel")  # standing at the clerk (2,5) in map 42
    try:
        emu._pyboy.memory[0xD74E] |= 1  # EVENT_OAK_GOT_PARCEL: the clerk opens the shop only after the delivery
        res = shop.buy(emu, 0x04, 5)
        assert res.ok, res.reason
        assert (res.money_before - res.money_after, res.bag_after[4] - res.bag_before.get(4, 0)) == (1000, 5)
        poor = shop.buy(emu, 0x04, 99)
        assert poor.reason.startswith("insufficient_money") and poor.money_after == res.money_after
    finally:
        emu.close()
