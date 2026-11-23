# Bundled Geist fonts

Unmodified variable fonts from Google Fonts, downloaded on 2026-10-08:

- https://github.com/google/fonts/blob/main/ofl/geist/Geist%5Bwght%5D.ttf
- https://github.com/google/fonts/blob/main/ofl/geistmono/GeistMono%5Bwght%5D.ttf

Both families use the SIL Open Font License 1.1; see the adjacent OFL files.
The full fonts include Czech glyphs and weights 100–900. `next/font/local`
self-hosts them with the application, preserving the existing CSS variables
and font families without a Google Fonts download during production builds.

## Oxanium (MRK-131)

Display face for headings, metric values and the brand: unmodified variable WOFF2 subsets (latin + latin-ext,
weights 200–800) from the `@fontsource-variable/oxanium` 5.3.0 npm package, copied 2026-11-23:

- `Oxanium-latin.woff2`, `Oxanium-latin-ext.woff2` (Czech diacritics live in latin-ext)
- license: `Oxanium-OFL.txt` (SIL Open Font License 1.1)

They are declared in `app/tokens.css` with `@font-face` + `unicode-range` (next/font/local cannot split one
family by unicode range), self-hosted, no download during the build.
