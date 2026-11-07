"""item_policies (explorer/items.py already exists, so not "items"): item-use policies by category. One small module per policy; each has a shield (what is never allowed) and a pure
``should_use(...) -> (item, target_slot, reason) | None``. ``behaviours/use_items.py`` runs them (outside battle, outside menus);
X items are the battle exception (``xitems_battle`` is called from behaviours/battle.py).

  ids           item ids and names
  view          Mon: the party as plain data, and which slot is the fighter
  key_items     key items are never sold / tossed / deposited; BICYCLE use; campaign hooks (flute, scope, card key)
  rare_candy    hold; use on the fighter when the gap is closable or the grind is long
  vitamins      use at once on the fighter (stat-exp cap shield)
  stones        evolve when the evolved form is not worse for the next boss and no needed move is at risk
  moves_shield  which moves may be overwritten by a taught move
  hm_teach      HM (and flagged TM) teaching: learner, overwrite slot
  teach_flow    the screen-by-screen teach flow with the move-forget YES/NO guard
  repel         Repel on a travel leg at readiness, never while grinding
  xitems        X items in boss/trainer battles when the margin is thin
  policy        the world snapshot -> the one pick to act on now
  uselog        every use goes through the economy ledger (item, category, reason, before/after)
"""
