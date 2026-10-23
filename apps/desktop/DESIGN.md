# Design contracts

The client's named design contracts (DSN-14). Each contract has a one-line rule, why it exists and the test that
enforces it. A new contract or an exception needs a Design lead review and a line in the change log below; exceptions
carry an expiry date.

## Contracts

1. **Colour belongs to meaning.** Components use role tokens only; seeds and raw colours never appear in components.
   Why: a theme or brand change must not recolour learning states. (test: `dsn01_no_seed_in_components`)
2. **Danger is for systems.** `danger` marks crashes, corrupt packs and full disks, never board, practice or feedback.
   Why: a student's mistake is not an emergency. (test: `dsn02_no_danger_in_learning`)
3. **Contrast is computed, not eyeballed.** Text roles meet 4.5:1 and indicators 3:1 on every listed surface, in both
   themes, and the recorded figures stay true. (test: `dsn03_token_contrast`)
4. **Named sizes.** Interface text uses the named sizes (seven since D89, display included); maths sizes come from the
   math tokens only. (test: `dsn07_named_sizes_only`)
5. **Radii, shadows and spacing come from tokens.** Surfaces are flat; only overlays carry a shadow.
   (test: `dsn08_radius_from_tokens`)
6. **Motion follows state.** Content is interactive the moment it exists; every animation has a reduced-motion rule
   and nothing transitions `all`. (test: `dsn09_motion_contract`)
7. **One home for motion.** Keyframes and transitions live only in the motion primitives. (test: `dsn10_primitives_only`)
8. **One icon pack, one glyph per concept.** Icons come only through the semantic name map.
   (test: `dsn11_icon_map_unique`)
9. **One of each primitive.** Loaders, empty, error and confirm patterns are the primitives; no native title tooltips.
   (test: `dsn12_primitive_monopoly`)
10. **Every string keyed.** No user-visible literal in a component; every key used exists and none is unused.
    (test: `loc01_no_literal_strings`)
11. **Cards never fold.** Questions, hints and failures stay visible when a turn's ephemeral lines fold into a summary.
    (test: `uxs04_run_summary_fold`)
12. **One live line.** A turn shows one status line; labels appear only after the label delay, so fast work never
    strobes. (test: `uxs03_no_strobe`)
13. **Settled text never moves.** A settled markdown block keeps its DOM node while the tail streams.
    (test: `uia13_settled_blocks_stable`)

## Pre-merge checklist

- Gallery states added for every new state (UXS-02).
- Both themes checked.
- Text scale 1.5 checked.
- Keyboard path checked.
- Copy keyed in the catalogue and in sentence case (UXS-05).

## Exceptions

None.

## Change log

- 2026-10-09: first set of contracts (M5).
