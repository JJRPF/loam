# Loam brand quick reference

Working name: Loam (pending trademark and SEO checks). Keep the name in one config constant so a rename is cheap.

## Mark
A mountain profile above a surface strip. The strip is the app's signature element: it shows terrain along a route (Lichen = singletrack, Slate = gravel, Blaze = road). The strip in the logo is decorative; it is not data.

## Colors
| Name   | Hex       | Use                                               |
|--------|-----------|---------------------------------------------------|
| Spruce | `#1D3B34` | Icon background, wordmark on light                 |
| Fog    | `#E7ECEC` | Mountain, wordmark on dark, light base             |
| Lichen | `#A9BF7A` | Strip segments (fills only, never text)            |
| Slate  | `#3F6C8F` | Strip segment                                      |
| Blaze  | `#FF5B14` | Strip segment, selected route (lines and large UI) |

Blaze with white text is only about 3:1 contrast. Use `#C73E00` for buttons with white text.

## Files
- `loam-icon.svg`: app icon, rounded square, 512 grid
- `loam-icon-maskable.svg`: full-bleed square with artwork inside the safe zone (PWA maskable and apple-touch)
- `favicon.svg`, `favicon.ico`: simplified, thicker strip for 16-48 px
- `loam-logo-horizontal.svg`: icon + wordmark on light backgrounds
- `loam-logo-horizontal-reversed.svg`: for dark backgrounds
- `loam-wordmark.svg`, `loam-wordmark-reversed.svg`: wordmark only (outlined shapes, no font dependency)
- `loam-mark-mono-spruce.svg`, `loam-mark-mono-fog.svg`: one-color mark for stamps, print, README badges
- `loam-social-card.svg`: 1200x630 social share image
- `png/`: rendered exports (192, 512, maskable, apple-touch 180, favicons, lockups, social card)

## Rules
- Clear space around the lockup: at least a quarter of the icon's height on every side.
- Minimum sizes: icon 16 px (use `favicon.svg` below 48 px), horizontal lockup 120 px wide.
- Use the one-color marks when color is unavailable. Do not recolor the strip segments.
- Do not stretch, rotate, add shadows or gradients, or place the standard icon on a Spruce background without the reversed outline version.
- The wordmark is always lowercase.
