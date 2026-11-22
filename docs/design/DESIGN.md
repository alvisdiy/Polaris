# Design System: Polaris — Scholarship Intelligence

## 1. Visual Theme & Atmosphere

A research archive you can search. Warm paper, ink, hairline rules, one vermilion
accent — the interface should feel like a well-kept reading room, not a startup
dashboard. Density 5, variance 6, motion 4: asymmetric editorial layouts with
restrained motion that never competes with the data.

The product's promise is traceability, so the design's job is to make provenance
visible: every record shows its source host, its deadline state, and whether a
field was stated by the page or left unknown. Nothing is decorated away.

## 2. Color Palette & Roles

- **Paper** (#F3EDDF) — page background; warm, never white
- **Slip** (#FBF7EC) — card and panel fill; a sheet laid on the paper
- **Slip Raised** (#FFFDF6) — inputs, hover surfaces
- **Ink** (#1A1512) — primary text; off-black, never #000
- **Ink Secondary** (#5B5145) — metadata, captions, secondary prose
- **Rule** (#D9CEBA) — hairline borders; **Rule Strong** (#B9AB92) — structural rules
- **Vermilion** (#B8402A) — single accent: actions, active nav, key numbers
- **On brand** — text on a vermilion fill: white in light, ink (#14110D) in dark;
  white on the dark accent reads 3.2:1 and is not allowed
- **Moss** (#2C5347) — evidence and "verified" semantics, never decorative
- **Deadline semantics** — Active #1F6B3A, Rolling #2C5347, Unknown #8A5A00,
  Expired #6A6258; always paired with a word and an icon, never colour alone

Dark theme: Paper #14110D, Slip #1C1813, Ink #F2EAD9, accent #E0704F. Geometry
and type are identical in both themes.

## 3. Typography Rules

- **Display:** Fraunces — headings and the wordmark only. Optical size on,
  weight 500–600, tracking −1.5% to −3%. Hierarchy comes from size and colour,
  not from bolding everything.
- **Body:** Instrument Sans — 16px base, 1.62 leading, max 68ch.
- **Mono:** IBM Plex Mono — every machine fact: provider, country, degree, funding,
  counts, dates, labels. Uppercase with 0.1em tracking at 0.68–0.72rem.
- **Banned:** Inter, generic serifs, all-caps body copy, gradient text.

## 4. Component Stylings

- **Buttons:** 46px min height, 2px radius, flat. Primary is ink fill; on hover it
  becomes vermilion and lifts 1px. Secondary is a hairline outline that darkens.
- **Cards:** paper slips, 1px rule, 2px ink top edge, 3px radius. Hover: lift 2px,
  soft shadow, top edge turns vermilion. No shadows at rest.
- **Chips / metadata:** mono, uppercase, 0.64rem, paper fill inside the slip.
- **Inputs:** label above, hairline border, 2px radius, focus ring in vermilion at
  3px offset. No floating labels.
- **Deadline badge:** mono uppercase with a 14px line icon and the date in ink.
- **Loaders:** skeleton blocks matching card geometry, shimmer via transform only.
- **Empty states:** dashed frame, serif title, one sentence of instruction.
- **Errors:** hairline panel with a 3px vermilion left edge; message in secondary ink.

## 5. Layout Principles

- Max width 74rem, 1.5rem gutters.
- Discover uses an asymmetric split: 17rem sticky filter rail + fluid results.
- Home uses an editorial hero: 7/5 split, headline left, live registry facts right.
- Detail uses 8/4: prose and facts left, "at a glance" rail right.
- No 3-equal-card feature rows; use 2-column zig-zag or a rule-separated list.
- Collapse to a single column below 900px; no horizontal scroll at any width.

## 6. Motion & Interaction

- One entrance: results and hero blocks rise 8px with a 420ms ease-out, staggered
  40ms per item via CSS `animation-delay` where lists are short.
- Hover is transform + colour only; nothing animates width/height/top.
- `prefers-reduced-motion` reduces everything to 0.01ms.
- No infinite decorative loops except the loading shimmer.

### 6.1 The one 3D element (ThreeUI / Three.js)

ThreeUI is a Three.js library, not a UI kit, so it is used for a single accent
rather than the interface: the home hero carries a wireframe globe with a
vermilion point cloud, built with `three` in `components/HeroGlobe.vue`.

Rules that keep it from becoming decoration for its own sake:

- it occupies its own grid column — it never sits under text;
- it is decorative only: `aria-hidden`, no pointer events, no data;
- it is skipped entirely below 900px and for `prefers-reduced-motion`;
- `three` is a dynamic import, so it loads after first paint and never blocks
the catalogue;
- the scene is drawn in the interface's own ink and vermilion, so light and dark
themes both work without a second palette;
- no WebGL post-processing, no bloom, no neon — those are banned above.

## 7. Anti-Patterns (Banned)

- Emojis anywhere; Inter; pure black; neon glows; purple gradients.
- Three equal cards in a row; centered hero; overlapping elements; fake numbers.
- Marketing clichés ("Elevate", "Seamless", "Unlock", "Next-Gen").
- Filler UI ("Scroll to explore", bouncing chevrons).
- Hiding an unknown field: if the page did not state a deadline, the UI says so.
