"""The native Dear PyGui window over a ``Panels``: five tabs, textures from Pillow images.

Thin on purpose: every picture is built in view.py; this only uploads them as static
textures and wires the frame stepper and the colouring toggle. ``run`` is the one piece
no test calls (it opens a window).
"""
from __future__ import annotations

from pokeagent.vision_model.view_draw import to_rgba_floats

MODES = ("net right / wrong", "coarse prediction")


def _tex(dpg, img, tag: str) -> tuple[int, int]:
    w, h, flat = to_rgba_floats(img)
    dpg.add_static_texture(w, h, flat, tag=tag, parent="vv_tex")
    return w, h


def _picture(dpg, img, tag: str) -> None:
    w, h = _tex(dpg, img, tag)
    dpg.add_image(tag, width=w, height=h)


def run(panels, title: str = "Vision viewer") -> int:
    """Open the window and block until it is closed."""
    import dearpygui.dearpygui as dpg

    dpg.create_context()
    state = {"i": 0, "mode": MODES[0]}
    with dpg.texture_registry(tag="vv_tex"):
        pass
    for n, (_, a, b, _) in enumerate(panels.frames):
        _tex(dpg, a, f"f{n}s")
        _tex(dpg, b, f"f{n}c")

    def show() -> None:
        n, t, _a, _b, boxes = state["i"], *panels.frames[state["i"]]
        kind = "s" if state["mode"] == MODES[0] else "c"
        dpg.configure_item("vv_frame", texture_tag=f"f{n}{kind}")
        w, h, _ = to_rgba_floats(panels.frames[n][1])
        dpg.configure_item("vv_frame", width=w, height=h)
        dpg.set_value("vv_frame_label",
                      f"frame {n + 1}/{len(panels.frames)}: {t}   ({boxes} crops matched)")

    def step(d: int):
        def cb(*_):
            state["i"] = (state["i"] + d) % len(panels.frames)
            show()
        return cb

    def pick(_s, value, _u=None):
        state["mode"] = value
        show()

    with dpg.window(tag="vv_root"):
        with dpg.tab_bar():
            with dpg.tab(label="Model's-eye view"):
                dpg.add_text("Outlines: green = net right, red = net wrong, grey = class never seen in "
                             "training. Coarse mode fills each crop by its predicted coarse class "
                             "(enemy orange, npc magenta, item yellow, player cyan, terrain blue).",
                             wrap=900)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="< prev", callback=step(-1))
                    dpg.add_button(label="next >", callback=step(1))
                    dpg.add_radio_button(MODES, horizontal=True, default_value=MODES[0], callback=pick)
                dpg.add_text("", tag="vv_frame_label")
                first = panels.frames[0]
                dpg.add_image("f0s", tag="vv_frame", width=first[1].width, height=first[1].height)
            for label, img, note in (
                    ("Class gallery", panels.gallery, "Top classes by held-out support."),
                    ("Worst confusions", panels.confusions, "Most frequent true -> predicted pairs."),
                    ("First-layer filters", None, "")):
                with dpg.tab(label=label):
                    if img is not None:
                        dpg.add_text(note)
                        with dpg.child_window(border=False):
                            _picture(dpg, img, f"img_{label}")
                    else:
                        _picture(dpg, panels.filters, "img_filters")
                        _picture(dpg, panels.activations, "img_acts")
            with dpg.tab(label="Architecture + numbers"):
                dpg.add_text("Layers (shapes from a real forward pass on a 16x16 crop)")
                with dpg.table(header_row=True, borders_innerH=True):
                    for c in ("layer", "output (C,H,W)", "params"):
                        dpg.add_table_column(label=c)
                    for name, shape, n in panels.arch:
                        with dpg.table_row():
                            for v in (name, str(shape), str(n)):
                                dpg.add_text(v)
                dpg.add_spacer(height=10)
                dpg.add_text("Held-out results (report.json)")
                with dpg.table(header_row=True, borders_innerH=True):
                    for c in ("metric", "template", "net"):
                        dpg.add_table_column(label=c)
                    for row in panels.numbers:
                        with dpg.table_row():
                            for v in row:
                                dpg.add_text(v)
    show()
    dpg.create_viewport(title=title, width=1100, height=820)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("vv_root", True)
    try:
        while dpg.is_dearpygui_running():
            dpg.render_dearpygui_frame()
    finally:
        dpg.destroy_context()
    return 0
