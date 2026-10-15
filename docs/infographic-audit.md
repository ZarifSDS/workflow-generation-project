# Audit: infographics and a photo-or-graphic judgement in the image generator (2026-10-15)

The owner's ask: the Image generator makes only environmental photos (and the hero's background photo). It should also judge when a section needs an infographic, and make one in the house branding, using the skills, the inner images of recent sdsmanager.com articles, or the taste-skill set, without breaking what works.

## What exists today

**In the studio.** `apps/studio/imagegen.py` plans images for an article (`prompts/image_plan.md`) and makes photos only: a branded hero, an unbranded lead image, or an in-article photo with the logo (`hero.brand_inner`). A section that needs a chart or diagram is listed under "Not photos" with the graphic to make by hand. The writer's `[VISUAL: type, description]` cues reach the plan; non-photo cues stop there.

**In the skills** (survey of `sds-hero-stock`, `ehs-seo-blog-optimized`, `ehs-outbound-blog`, the zipped whitepaper and lead-magnet skills, and the taste-skill plugin):
- No skill renders an infographic. `sds-hero-stock` brands photos and stamps the logo on finished inner images (`inner_logo.py`, with a corner-clash score and a WCAG contrast pick of the regular or negative logo). Its measured spec records that "large generated infographics" on the live site carry a small top-left logo.
- `ehs-seo-blog-optimized` sets when and what: a visual "only where it reduces cognitive load, breaks a dense passage or anchors an abstract concept"; data visualisation only from the article's own cited statistics ("a missing type is better than an invented one"); process diagram for steps; comparison or before/after; alt text a full sentence of 10-125 characters, never a file name; inline at least 1200 px wide, WebP under about 100 KB; zero em or en dashes, captions included.
- The fullest brand palette is in the whitepaper skill: Inter, title `#111827`, periwinkle `#626DF9` (headings, dividers, callouts; never body text or fills), navy `#1A3A6B`, amber `#EAA820` (sparingly), body `#1F2937`, muted `#6B7280`.
- taste-skill: web-UI directives without scripts. Only the WCAG contrast thresholds (4.5:1 body, 3:1 large) are mechanically checkable; some rules clash with the brand (it bans Inter for premium work and discourages "AI purple", which is close to periwinkle). Useful as a source of photo anti-clichés, not as a scorer.

**On the live site** (measured in the browser: 23 inner images in the seven posts of 6-14 October, US JSA and unsafe acts, UK safe system of work and risk-assessment law, AU JSEA and construction risk, CA FLHA; plus the September hierarchy-of-controls and RIDDOR posts). All inner images are served at 800 px wide (`width-800`), so 800 px is the display width any legibility check should use. Three styles are live:

| Style | Where | Look |
|---|---|---|
| **A. Hero-derived, newest** (about 13 of the 19 graphics from October) | US JSA, SSoW, AU JSEA, CA FLHA, US unsafe acts | Inter; near-black sentence-case title (`#303030`), sometimes with the key phrase in periwinkle as in the hero headline; grey subtitle; lavender cards and boxes (`#E0E0F0`-ish) with periwinkle borders; solid periwinkle (`#626DF9`/`#6060D0`) action boxes with white text; logo-yellow (`#F0C040`) number badges and warning callouts; dashed boxes for "no step" and loops; rounded corners; the hero's periwinkle glow bottom-left on some; logo top-left (full size) or small bottom-right. Readable at 800 px, no dashes. |
| **B. Navy and amber** (September) | US hierarchy of controls, UK RIDDOR | Arial-like bold; centred navy title (`#1B2A4A`); amber (`#F5A623`) accent; navy-to-teal ramp for tiers; grey caption with em dashes; logo small top-left or missing; flowchart text 5-6 px at 800 px. |
| **C. Other** | AU construction (3), UK risk-assessment law and fire comparison (2) | Navy cycle diagram with a condensed face and illustrated icons (looks image-model or template made); navy and rust stack; peach comparison. |

Across all three: alt text is mostly the file slug ("jsea-form-parts-job-safety-environmental-analy...") or empty, against the skill's rule, and the logo moves between top-left, bottom-right and absent. Style A is what the team has converged on in the last two weeks, it is the brand kit's palette (periwinkle and logo yellow, Inter), and it reuses the hero's own devices; it is the one to codify.

The September graphics in more detail (the first two posts measured): a consistent, undocumented system, made by hand (Canva exports, `-v2`/`-v3` file names).

| Trait | Live practice |
|---|---|
| Canvas | White, 1200-1400 px wide (1200x700, 1200x900, 1300x400, 1400x1000) |
| Colours | Navy about `#1B2A4A` for primary shapes and text; amber about `#F5A623` for the accent or action; a navy-to-teal ramp `#0B3A5C`, `#0B5A7A`, `#12839C`, `#2CA4A4` for ranked tiers; caption grey about `#8A92A3` |
| Type | Bold sans (Arial-like), centred navy title, uppercase white labels with a short description, small grey caption under the graphic |
| Logo | Small, top-left, on most; missing on the RIDDOR timeline and flowchart |
| Types | Inverted pyramid (ranked tiers), process flow (5 boxes in a row), bar comparison, timeline, branching flowchart (navy trigger, amber action, outlined outcome, dashed "no step") |
| Defects | Em dashes in captions and headings (house style bans them); alt text that is the file name; flowchart text about 11 px on a 1400 px canvas, about 5-6 px in the article column (unreadable on a phone) |

## Recommendation

Render infographics from templates, not with an image model. Image models still garble text (seen live on 2026-10-14) and drift off-brand; the house graphics are geometric, so a deterministic renderer reproduces them exactly, and every rule becomes a check. The model's job is the judgement and the content; the code's job is the drawing.

1. **Templates** (`apps/quality/infographic.py`) in style A: the types seen live (numbered steps in a row, yes/no decision flow, two-column comparison, form-parts or anatomy list, percentage or bar chart, ranked pyramid, cycle, timeline), from a small JSON spec (title, items with label and description, values, caption, source). SVG with text outlined to paths through fontTools (as `svgify.py` does for the hero headline, so no font has to be installed), rasterised by cairosvg (already installed) to PNG and WebP. The logo is the real vector `sds-manager-logo.svg`, small, top-left.
2. **Judgement** (the article planner): for each section, photo, one of the infographic types, or nothing, by the skill's rules; numbers only from the article; at most about one visual per 1,500 words; writer's `[VISUAL:]` cues first. A non-photo cue becomes an infographic idea instead of a "Not a photo" note.
3. **Checks before an infographic is offered** (deterministic, shown like the hero checks):
   - every text at least 12 px at the 800 px width the site serves inner images at (so at least 18 px on a 1200 px canvas);
   - WCAG contrast of every text on its fill: 4.5:1, or 3:1 for large text;
   - item counts and label lengths within the template (measured with the font, so nothing overflows);
   - every number and named rule in the spec appears in the article (no invented data);
   - house mechanics (no dashes, straight quotes), logo present, alt text a sentence of 10-125 characters built from the content, WebP under 100 KB.
4. **Where it shows up**: a new kind in the Image generator ("Infographic for a section", from a description or from the article plan), and later a "Make this visual" action on `[VISUAL:]` markers in Final cleanup. Photos, heroes and branding keep their code paths untouched; the new kind is additive, with its own tests.
5. **Photos**: keep the vision check and `check_photo.py`; add a short anti-cliché list to the photo prompt and the vision check (handshakes, posed thumbs-up, staged stock looks; from the outbound skill and taste-skill), counted as a minor finding.

## Decisions

1. **Palette**: the owner asked for the recent posts to be checked first (2026-10-15). Result: the October graphics converge on style A (periwinkle, lavender, logo yellow, near-black text, the hero's devices), so the recommendation changes from navy and amber to style A. Exact values to fix from the source files or the design tool before building: the lavender fill and border, the yellow (logo `#FFC93C` vs the measured `#F0C040`), the text black, and one logo position (top-left full logo, as on the newest ones, or small bottom-right).
2. **Typeface**: Inter (owner, 2026-10-15). Inter Regular and SemiBold need adding next to the bundled Inter Bold (SIL OFL, a download from the Inter release; ask before downloading).
3. **Scope**: audit only for now (owner, 2026-10-15). Nothing is built until the owner says so; the first build would be the templates for the three most frequent October types (numbered steps, decision flow, two-column comparison), the planner's photo-or-infographic choice and the checks.
