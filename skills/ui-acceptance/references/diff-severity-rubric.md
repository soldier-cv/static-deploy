# Severity rubric

Compare **structure and product UI**, not pixel-perfect identity.

## Severities

| Level | Meaning | Action |
|-------|---------|--------|
| `blocker` | Same-phase screen is missing a required region/control, broken navigation, unusable layout, or wrong information architecture | Must fix before calling the screen done |
| `major` | Required control exists but wrong place/state; theme/spacing clearly off vs expected; truncated critical labels | Fix in this iteration if phase owns it |
| `minor` | Alignment, density, icon size, corner radius, secondary copy tone | Optional polish; batch if many |
| `phase-ok` | Expected richer UI exists only in later phase / deferred feature / mock data | Document; do not treat as regression |
| `noise` | Status bar, clock, battery, window shadow, anti-alias, dynamic counts, avatars, ads, DevTools borders | Ignore for pass/fail |

## Decision order

1. Is this control/region in **current phase scope**? If no → `phase-ok`.
2. Is it **system chrome / dynamic content**? If yes → `noise`.
3. Does it break **task completion** or IA? → `blocker`.
4. Visible product mismatch on in-scope UI → `major` or `minor`.

## Pass criteria (default)

Screen **passes** visual acceptance when:

- No in-scope `blocker`
- No in-scope `major` **or** user explicitly accepts remaining majors
- `phase-ok` / `noise` may remain

## Common mappings

| Observation | Likely severity |
|-------------|-----------------|
| Actual is empty placeholder blurb; expected full dashboard; phase says shell only | `phase-ok` |
| Sidebar items missing / wrong order vs spec for current phase | `blocker` |
| Button label wrong but present | `major` |
| 4px padding drift | `minor` |
| Pending badge shows `3` vs `0` | `noise` (unless testing that metric) |
| Android status bar differs from design PNG | `noise` |
| WeChat capsule overlap with title | `major` if collision; else note platform constraint |

## Engines

- Semantic tools (`ui_diff_check`, multimodal read) own the verdict.
- Pixel threshold tools (Maestro `assertScreenshot`, etc.) are **hints** only unless the user asked for pixel regression gates.
