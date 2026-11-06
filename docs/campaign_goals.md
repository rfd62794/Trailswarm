# Campaign goals

The goal ladder lives in `src/pokeagent/data/campaign.json` (128 goals, New Game to Hall of Fame). `pokeagent.goals.GOALS`
is read from it; `pokeagent.campaign` holds the generic detectors and reachability. Goals 1-25 are the original ladder and keep
their hand-coded detectors in `goals.check_goals` (ids, names and order are frozen); goals 26+ use the data file.

Each goal: `id`, `name`, `after` (the previous id, so the file is a chain), `detector`, `needs`, `note`.

Detectors: `map` (any listed map entered this run), `badge` (wObtainedBadges 0xD356 bit, 0 Boulder ... 7 Earth), `item`
(in the bag now or earlier this run; a list means any), `flag`, `party`, `map_and_badge`, or `"unverified"`. Unverified goals
have no RAM detector we trust (HM items sit above the kb item-name table; battle wins have no verified flag), so
`check_goals` marks them reached once any later goal is, and the segment picker never targets them. A `candidate` field records
the pokered value to confirm. No event flag from `ram_findings.json` is verified for a story event, so no goal uses `flag` yet.
Where a door only opens after a win (Elite Four rooms), the next room's map stands in for the win.

`needs` are capability tags the current agent behaviours may lack. `reachable(goal, caps)` checks one goal's needs;
`selectable(goal, caps)` also requires every earlier goal to be reachable (it is a chain) and the detector to be verified;
`tools/swarm.py --segment auto` and `tools/overnight.py` pick only selectable goals. The agent has no capabilities by default;
`POKEAGENT_CAPS=cut,surf` overrides. Tags: `cut`, `surf`, `strength`, `flash`, `poke_flute`, `silph_scope`, `bike`, plus
`puzzle` (switch, warp-pad, spinner and quiz mazes), `safari` (the step-limited Safari Zone) and `dex10` (Oak's aide).

Map ids come from the ROM map headers (`atlas/map_names.json`, checked against `rom_maps.valid_map_ids` by the tests), item ids
from `kb/rom_tables.json`.

| # | id | goal | where | detector | needs |
|---|----|------|-------|----------|-------|
| 1 | `potion` | Potion in the bag | - | item 0x14 POTION (hand-coded) | - |
| 2 | `left_house` | Left the house | - | special: left_house (hand-coded) | - |
| 3 | `first_pokemon` | First Pokemon | - | special: party_count (hand-coded) | - |
| 4 | `won_battle` | Won a battle | - | special: battles_won (hand-coded) | - |
| 5 | `to_route1` | Route 1 | ROUTE_1 (0x0C) | map entered (hand-coded) | - |
| 6 | `to_viridian` | Viridian City | VIRIDIAN_CITY (0x01) | map entered (hand-coded) | - |
| 7 | `oaks_parcel` | Oak's Parcel | - | item 0x46 OAK? PARCEL (hand-coded) | - |
| 8 | `deliver_parcel` | Parcel delivered | - | special: parcel_delivered (hand-coded) | - |
| 9 | `to_route2` | Route 2 | ROUTE_2 (0x0D) | map entered (hand-coded) | - |
| 10 | `to_pewter` | Pewter City | PEWTER_CITY (0x02) | map entered (hand-coded) | - |
| 11 | `to_gym` | Pewter Gym | PEWTER_GYM (0x36) | map entered (hand-coded) | - |
| 12 | `beat_brock` | Boulder Badge | - | badge bit0 (Boulder) (hand-coded) | - |
| 13 | `to_route3` | Route 3 | ROUTE_3 (0x0E) | map entered (hand-coded) | - |
| 14 | `to_route4` | Route 4 | ROUTE_4 (0x0F) | map entered (hand-coded) | - |
| 15 | `buy_magikarp` | Magikarp bought (or no longer possible) | - | special: magikarp (hand-coded) | - |
| 16 | `to_mt_moon` | Mt Moon 1F | MT_MOON_1F (0x3B) | map entered (hand-coded) | - |
| 17 | `mt_moon_b1f` | Mt Moon B1F | MT_MOON_B1F (0x3C) | map entered (hand-coded) | - |
| 18 | `mt_moon_b2f` | Mt Moon B2F | MT_MOON_B2F (0x3D) | map entered (hand-coded) | - |
| 19 | `through_mt_moon` | Through Mt Moon | - | special: through_mt_moon (hand-coded) | - |
| 20 | `to_cerulean` | Cerulean City | CERULEAN_CITY (0x03) | map entered (hand-coded) | - |
| 21 | `heal_cerulean` | Healed at the Cerulean Pokecenter | - | special: healed_cerulean (hand-coded) | - |
| 22 | `beat_misty` | Cascade Badge | - | badge bit1 (Cascade) (hand-coded) | - |
| 23 | `nugget_bridge` | Route 24 (Nugget Bridge) | ROUTE_24 (0x23) | map entered (hand-coded) | - |
| 24 | `to_bill` | Bill's House | BILLS_HOUSE (0x58) | map entered (hand-coded) | - |
| 25 | `ss_ticket` | S.S. Ticket | - | item 0x3F S.S.TICKET (hand-coded) | - |
| 26 | `to_route5` | Route 5 | ROUTE_5 (0x10) | map entered | - |
| 27 | `to_route6` | Route 6 | ROUTE_6 (0x11) | map entered | - |
| 28 | `to_vermilion` | Vermilion City | VERMILION_CITY (0x05) | map entered | - |
| 29 | `to_ss_anne` | S.S. Anne 1F | SS_ANNE_1F (0x5F) | map entered | - |
| 30 | `ss_anne_2f` | S.S. Anne 2F | SS_ANNE_2F (0x60) | map entered | - |
| 31 | `rival_ss_anne` | Rival battle on the S.S. Anne | - | unverified | - |
| 32 | `ss_anne_captain` | Captain's cabin | SS_ANNE_CAPTAINS_ROOM (0x65) | map entered | - |
| 33 | `hm01_cut` | HM01 Cut | - | unverified (candidate item 0xC4) | - |
| 34 | `pokemon_fan_club` | Pokemon Fan Club | POKEMON_FAN_CLUB (0x5A) | map entered | - |
| 35 | `bike_voucher` | Bike Voucher | - | item 0x2D BIKE VOUCHER | - |
| 36 | `bike_shop` | Cerulean Bike Shop | BIKE_SHOP (0x42) | map entered | - |
| 37 | `bicycle` | Bicycle | - | item 0x06 BICYCLE | - |
| 38 | `vermilion_gym_entry` | Vermilion Gym | VERMILION_GYM (0x5C) | map entered | cut |
| 39 | `beat_surge` | Thunder Badge | - | badge bit2 (Thunder) | cut, puzzle |
| 40 | `route2_gate` | Route 2 gate | ROUTE_2_GATE (0x31) | map entered | - |
| 41 | `hm05_flash` | HM05 Flash | - | unverified (candidate item 0xC8) | dex10 |
| 42 | `to_route9` | Route 9 | ROUTE_9 (0x14) | map entered | cut |
| 43 | `to_route10` | Route 10 | ROUTE_10 (0x15) | map entered | - |
| 44 | `to_rock_tunnel` | Rock Tunnel 1F | ROCK_TUNNEL_1F (0x52) | map entered | flash |
| 45 | `rock_tunnel_b1f` | Rock Tunnel B1F | ROCK_TUNNEL_B1F (0xE8) | map entered | flash |
| 46 | `to_lavender` | Lavender Town | LAVENDER_TOWN (0x04) | map entered | - |
| 47 | `to_route8` | Route 8 | ROUTE_8 (0x13) | map entered | - |
| 48 | `underground_route8` | Underground Path (Routes 7-8) | UNDERGROUND_PATH_WEST_EAST (0x79) | map entered | - |
| 49 | `to_route7` | Route 7 | ROUTE_7 (0x12) | map entered | - |
| 50 | `to_celadon` | Celadon City | CELADON_CITY (0x06) | map entered | - |
| 51 | `celadon_gym_entry` | Celadon Gym | CELADON_GYM (0x86) | map entered | cut |
| 52 | `beat_erika` | Rainbow Badge | - | badge bit3 (Rainbow) | cut |
| 53 | `celadon_mart_roof` | Celadon Mart roof | CELADON_MART_ROOF (0x7E) | map entered | - |
| 54 | `buy_drink` | A drink (Fresh Water, Soda Pop or Lemonade) | - | item 0x3C FRESH WATER/0x3D SODA POP/0x3E LEMONADE | - |
| 55 | `game_corner` | Rocket Game Corner | GAME_CORNER (0x87) | map entered | - |
| 56 | `rocket_hideout_b1f` | Rocket Hideout B1F | ROCKET_HIDEOUT_B1F (0xC7) | map entered | - |
| 57 | `rocket_hideout_b2f` | Rocket Hideout B2F | ROCKET_HIDEOUT_B2F (0xC8) | map entered | - |
| 58 | `rocket_hideout_b3f` | Rocket Hideout B3F | ROCKET_HIDEOUT_B3F (0xC9) | map entered | puzzle |
| 59 | `rocket_hideout_b4f` | Rocket Hideout B4F | ROCKET_HIDEOUT_B4F (0xCA) | map entered | puzzle |
| 60 | `lift_key` | Lift Key | - | item 0x4A LIFT KEY | - |
| 61 | `silph_scope` | Silph Scope (Giovanni #1 beaten) | - | item 0x48 SILPH SCOPE | - |
| 62 | `to_pokemon_tower` | Pokemon Tower 1F | POKEMON_TOWER_1F (0x8E) | map entered | - |
| 63 | `tower_2f` | Pokemon Tower 2F | POKEMON_TOWER_2F (0x8F) | map entered | - |
| 64 | `rival_pokemon_tower` | Rival battle in Pokemon Tower | - | unverified | - |
| 65 | `tower_3f` | Pokemon Tower 3F | POKEMON_TOWER_3F (0x90) | map entered | - |
| 66 | `tower_4f` | Pokemon Tower 4F | POKEMON_TOWER_4F (0x91) | map entered | - |
| 67 | `tower_5f` | Pokemon Tower 5F | POKEMON_TOWER_5F (0x92) | map entered | - |
| 68 | `tower_6f` | Pokemon Tower 6F | POKEMON_TOWER_6F (0x93) | map entered | silph_scope |
| 69 | `tower_7f` | Pokemon Tower 7F | POKEMON_TOWER_7F (0x94) | map entered | silph_scope |
| 70 | `mr_fujis_house` | Mr. Fuji's House | MR_FUJIS_HOUSE (0x95) | map entered | - |
| 71 | `poke_flute` | Poke Flute | - | item 0x49 POKé FLUTE | - |
| 72 | `snorlax_route12` | Wake Snorlax on Route 12 | - | unverified | poke_flute |
| 73 | `to_route12` | Route 12 | ROUTE_12 (0x17) | map entered | - |
| 74 | `to_route13` | Route 13 | ROUTE_13 (0x18) | map entered | - |
| 75 | `to_route14` | Route 14 | ROUTE_14 (0x19) | map entered | - |
| 76 | `to_route15` | Route 15 | ROUTE_15 (0x1A) | map entered | - |
| 77 | `to_fuchsia` | Fuchsia City | FUCHSIA_CITY (0x07) | map entered | - |
| 78 | `fuchsia_gym_entry` | Fuchsia Gym | FUCHSIA_GYM (0x9D) | map entered | - |
| 79 | `beat_koga` | Soul Badge | - | badge bit4 (Soul) | puzzle |
| 80 | `safari_zone_gate` | Safari Zone gate | SAFARI_ZONE_GATE (0x9C) | map entered | safari |
| 81 | `safari_center` | Safari Zone center | SAFARI_ZONE_CENTER (0xDC) | map entered | safari |
| 82 | `safari_west` | Safari Zone west | SAFARI_ZONE_WEST (0xDB) | map entered | safari |
| 83 | `gold_teeth` | Gold Teeth | - | item 0x40 GOLD TEETH | safari |
| 84 | `safari_secret_house` | Safari Zone secret house | SAFARI_ZONE_SECRET_HOUSE (0xDE) | map entered | safari |
| 85 | `hm03_surf` | HM03 Surf | - | unverified (candidate item 0xC6) | safari |
| 86 | `wardens_house` | Warden's House | WARDENS_HOUSE (0x9B) | map entered | safari |
| 87 | `hm04_strength` | HM04 Strength | - | unverified (candidate item 0xC7) | safari |
| 88 | `to_route18` | Route 18 | ROUTE_18 (0x1D) | map entered | - |
| 89 | `to_route17` | Route 17 (Cycling Road) | ROUTE_17 (0x1C) | map entered | bike |
| 90 | `snorlax_route16` | Wake Snorlax on Route 16 | - | unverified | poke_flute, bike |
| 91 | `to_route16` | Route 16 | ROUTE_16 (0x1B) | map entered | - |
| 92 | `route7_gate` | Route 7 gate (Saffron guard) | ROUTE_7_GATE (0x4C) | map entered | - |
| 93 | `to_saffron` | Saffron City | SAFFRON_CITY (0x0A) | map entered | - |
| 94 | `silph_1f` | Silph Co. 1F | SILPH_CO_1F (0xB5) | map entered | - |
| 95 | `silph_5f` | Silph Co. 5F | SILPH_CO_5F (0xD2) | map entered | puzzle |
| 96 | `card_key` | Card Key | - | item 0x30 CARD KEY | puzzle |
| 97 | `silph_7f` | Silph Co. 7F | SILPH_CO_7F (0xD4) | map entered | puzzle |
| 98 | `rival_silph` | Rival battle in Silph Co. | - | unverified | puzzle |
| 99 | `silph_11f` | Silph Co. 11F | SILPH_CO_11F (0xEB) | map entered | puzzle |
| 100 | `master_ball` | Master Ball (Giovanni #2 beaten) | - | item 0x01 MASTER BALL | puzzle |
| 101 | `saffron_gym_entry` | Saffron Gym | SAFFRON_GYM (0xB2) | map entered | - |
| 102 | `beat_sabrina` | Marsh Badge | - | badge bit5 (Marsh) | puzzle |
| 103 | `to_route19` | Route 19 | ROUTE_19 (0x1E) | map entered | surf |
| 104 | `to_route20` | Route 20 | ROUTE_20 (0x1F) | map entered | surf |
| 105 | `to_cinnabar` | Cinnabar Island | CINNABAR_ISLAND (0x08) | map entered | surf |
| 106 | `mansion_1f` | Pokemon Mansion 1F | POKEMON_MANSION_1F (0xA5) | map entered | - |
| 107 | `mansion_b1f` | Pokemon Mansion B1F | POKEMON_MANSION_B1F (0xD8) | map entered | puzzle |
| 108 | `secret_key` | Secret Key | - | item 0x2B SECRET KEY | puzzle |
| 109 | `cinnabar_gym_entry` | Cinnabar Gym | CINNABAR_GYM (0xA6) | map entered | - |
| 110 | `beat_blaine` | Volcano Badge | - | badge bit6 (Volcano) | puzzle |
| 111 | `to_route21` | Route 21 | ROUTE_21 (0x20) | map entered | surf |
| 112 | `viridian_gym_entry` | Viridian Gym | VIRIDIAN_GYM (0x2D) | map entered | - |
| 113 | `beat_giovanni` | Earth Badge (Giovanni #3 beaten) | - | badge bit7 (Earth) | puzzle |
| 114 | `to_route22` | Route 22 | ROUTE_22 (0x21) | map entered | - |
| 115 | `rival_route22` | Rival battle on Route 22 | - | unverified | - |
| 116 | `route22_gate` | Route 22 gate | ROUTE_22_GATE (0xC1) | map entered | - |
| 117 | `to_route23` | Route 23 | ROUTE_23 (0x22) | map entered | - |
| 118 | `victory_road_1f` | Victory Road 1F | VICTORY_ROAD_1F (0x6C) | map entered | strength |
| 119 | `victory_road_2f` | Victory Road 2F | VICTORY_ROAD_2F (0xC2) | map entered | strength |
| 120 | `victory_road_3f` | Victory Road 3F | VICTORY_ROAD_3F (0xC6) | map entered | strength |
| 121 | `to_indigo_plateau` | Indigo Plateau | INDIGO_PLATEAU (0x09) | map entered | - |
| 122 | `indigo_lobby` | Indigo Plateau lobby | INDIGO_PLATEAU_LOBBY (0xAE) | map entered | - |
| 123 | `e4_lorelei` | Lorelei's room | LORELEIS_ROOM (0xF5) | map entered | - |
| 124 | `beat_lorelei` | Lorelei beaten (Bruno's room reached) | BRUNOS_ROOM (0xF6) | map entered | - |
| 125 | `beat_bruno` | Bruno beaten (Agatha's room reached) | AGATHAS_ROOM (0xF7) | map entered | - |
| 126 | `beat_agatha` | Agatha beaten (Lance's room reached) | LANCES_ROOM (0x71) | map entered | - |
| 127 | `beat_lance` | Lance beaten (Champion's room reached) | CHAMPIONS_ROOM (0x78) | map entered | - |
| 128 | `beat_champion` | Champion beaten (Hall of Fame reached) | HALL_OF_FAME (0x76) | map entered | - |
