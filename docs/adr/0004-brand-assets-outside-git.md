# ADR 0004: Hero brand assets stay outside git

- Status: Accepted (M6)
- Date: 2026-10-13

## Context

The hero step brands generated photos with the sds-hero-stock skill's scripts, vendored unchanged in `apps/quality/vendor/sds_hero_stock/`. The scripts load their assets from `assets/` next to them: the SDS Manager logo (regular and negative, PNG and SVG), `overlay_A.png` and `veil_color.png` (overlay data measured from the live sdsmanager.com heroes), and the Inter Bold font. The GitHub repository is public, and the logo and the measured brand data are the company's, not the project's to publish.

## Decision

- The brand files in `assets/` are git-ignored. The Inter Bold font (SIL OFL 1.1, with its licence file) is committed.
- Each clone copies the assets from the skill once (`docs/setup.md`, step 5). The dev containers see them through the source mount; a production build copies them into the image from the build context.
- The vendored scripts stay byte-identical, so the assets stay at the path the scripts expect.
- Without the assets the hero step still generates and checks the photo, and the version note says branding was skipped.
- Tests copy the scripts into a temporary folder with generated placeholder assets, so CI never needs the real logo.

## Consequences

- A fresh clone produces unbranded heroes until the assets are copied; the note says so.
- If the repository becomes private, the assets can be committed and the setup step dropped.
