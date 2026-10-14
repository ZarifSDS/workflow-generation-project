---
# Fixture B (docs/sop-audit.md, phase 1): a deliberately bad sdsmanager.com blog draft. Every defect below is
# planted on purpose, and each must be caught. `checks` are the SOP's deterministic checks (sop.check,
# matched on the check text); `scans` are the edit step's deslop scans (lexical/structure finding ids).
# `known_gaps` lists planted defects nothing catches yet: the test reports them instead of failing, so the
# list is the honest to-do. Keep one defect per line of the article where possible.
step: draft
content_type: seo_blog
pkeyword: how to read a safety data sheet
region: US
wordcount: 1200
allowed_urls:
  - https://sdsmanager.com/us/ehs-software/
  - https://sdsmanager.com/us/sds-management-articles/sds-retention/
  - https://www.osha.gov/hazcom
allowed_citations:
  - 1910.1200(g)(8)
checks:
  - "no scope sentence with the literal words"            # intro without "this article"
  - "uses coverage framing"                               # Key Takeaways bullet describing the article
  - "leans on another bullet"                             # Key Takeaways bullet starting "That"
  - "joins a topic and its qualifier with a comma"        # "Worked Example, Acetone SDS"
  - "exists only to point at another page"                # "For more details, see our ... guide"
  - "two links in one sentence"                           # link_check
  - "meta narration"                                      # "In this section, we will look at"
  - "opens with a bare Yes/No"                            # FAQ answer "Yes, ..."
  - "contains a link"                                     # link inside an FAQ answer
  - "is generic"                                          # "## Conclusion"
  - "links no product page"                               # close without a product link
  - "headings; keep it in two or three"                   # keyword in more than three headings
  - "isn't in the inputs (invented URL)"                  # sdsmanager.com URL not in the inputs
  - "is a bare path or a marker"                          # (/resources/training)
  - "isn't in the research or the search results"         # 1910.1200(c)(1), unsourced
scans:
  - "banned-A:pivotal"         # puffery: "a pivotal, game-changing cornerstone"
  - "banned-B:vibrant"         # puffery: "a vibrant safety culture"
# Blocks the draft trips besides the planted ones; each is a real defect here. A block on this fixture
# that is in neither list fails the test, so a new false positive shows up at once.
also_fires:
  - "the primary keyword isn't in the first"              # the intro never uses the keyword phrase
  - "anchors sit in two adjacent sections"                # storage and worked-example sections both link
  - "two links back to back in one paragraph"             # link_check, same paragraph as the pointer
  - "a sentence that is little more than its link"        # link_check, the pointer sentence again
  - "sdsmanager.com links; one per section"               # link_check, the storage section
# Planted defects nothing deterministic catches yet (the deslop rewrite and the reviewer are asked to):
known_gaps:
  - "vague attribution: 'Experts agree' (deslop's lexical scan has no pattern for it)"
  - "tidy wrap-up: 'At the end of the day' (no pattern)"
  - "puffery outside the banned list: 'game-changing', 'cornerstone'"
  - "uniform sentence length: a run of five short sentences (structure_scan reads the whole article only)"
  - "unsourced statistic: 'cut incidents by 47%' with no [SRC:] or [VERIFY]"
---
# How to Read a Safety Data Sheet

A safety data sheet is a document. It lists the hazards of a product. It tells you how to store it. It explains what to wear. It says what to do in a spill. Experts agree that reading it is a pivotal, game-changing cornerstone of a vibrant safety culture.

## Key Takeaways

- This article covers the sixteen sections of a safety data sheet.
- That rule applies to every supplier and every product you receive.
- Section 8 lists the exposure limits and the protective equipment the product calls for.

## How to Read a Safety Data Sheet in Five Steps

In this section, we will look at the order a supervisor reads a sheet in. Start with Section 1 to match the product name to the container label. Then read Section 2 for the signal word and the pictograms. Training on these sheets is required by 29 CFR 1910.1200(c)(1). Teams that train this way cut incidents by 47%.

## How to Read a Safety Data Sheet for Storage Rules

Section 7 gives the storage conditions and the incompatible materials. For more details, see our [SDS retention guide](https://sdsmanager.com/us/sds-management-articles/sds-retention/). Keep [SDS software](https://sdsmanager.com/us/ehs-software/) and the [OSHA HazCom page](https://www.osha.gov/hazcom) open while you plan a store.

## Worked Example, Acetone SDS

The acetone sheet lists a flash point well below room temperature in Section 9. The [annotated acetone sheet](https://sdsmanager.com/us/made-up-page/) and the [training page](/resources/training) show the same values.

## How to Read a Safety Data Sheet Without Missing Section 16

Section 16 gives the revision date, so you can tell whether the sheet is current under 1910.1200(g)(8).

## How to Read a Safety Data Sheet for a New Hire

Walk a new starter through Sections 2, 4 and 8 on the first day, with a real container in hand.

## Conclusion

At the end of the day, reading the sheet keeps people safe. Every site should make it a habit.

## Frequently Asked Questions

:::faq
### Do I need to read the whole safety data sheet?

Yes, you should read every section before you handle a new product, as the [OSHA HazCom page](https://www.osha.gov/hazcom) explains.

### Where is the exposure limit on a safety data sheet?

The exposure limit on a safety data sheet sits in Section 8, next to the protective equipment.

### How do you read a safety data sheet quickly?

You read a safety data sheet quickly by going to Sections 2, 4, 7 and 8 first.
:::
