# SOP calibration fixtures (Fixture A and Fixture B)

The method comes from the `ehs-seo-blog-optimized` skill's maintenance rule: before trusting a change to a
check, run two fixtures. **Fixture A**, a finished, editorially approved article, passes when the checks
raise zero failures that describe no real defect. **Fixture B**, a deliberately bad draft, passes when every
planted defect is caught. Loosening a check fails Fixture B; tightening it past the house style fails
Fixture A. `tests/test_sop_fixtures.py` runs both on every test run, with no model calls.

## Folders

- `a/`: approved articles. **Zero blocking findings allowed.** Only articles the owner approved go here.
- `b/`: deliberately bad drafts. Every `checks` entry must fire, every `scans` id must appear, and no block
  may fire that isn't listed in `checks` or `also_fires`. `known_gaps` lists planted defects nothing
  deterministic catches yet; the test prints them so the gap list stays visible.

## Adding a Fixture A article

Paste the approved article as Markdown (H1 first, `##` sections, the FAQ as `### Question` lines inside
`:::faq` … `:::` if the article has one) under a front-matter block:

```
---
step: review_edit          # draft, review_edit or localise: which step's checks apply
content_type: seo_blog     # seo_blog or outbound
pkeyword: sds retention requirements
region: US
wordcount: 1800            # optional
anchors:                   # guest posts: the brief's anchors, in order
  - {text: "SDS management software", url: "https://sdsmanager.com/us/"}
---
# The article's H1
...
```

Without `allowed_urls` and `allowed_citations` the URL- and citation-sourcing checks are skipped, since an
approved article's links were checked when it was approved.

When a Fixture A article trips a check, the check is wrong (loosen it, or turn it into an advisory) unless
the owner agrees the article breaks a house rule that changed after it was approved; then record that in
the fixture's front matter as `accepted_blocks` with the reason.

Also see `python manage.py sop_replay`, which runs the same checks over every stored run.
