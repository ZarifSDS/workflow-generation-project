"""The studio's one reading-grade counting and its diagnosis (apps/quality/readability.py,
docs/reading-grade-options.md). The small gold set below is counted by hand."""

from pathlib import Path

import pytest

from apps.quality import readability as r
from apps.quality import review

FIXTURE_A = sorted((Path(__file__).parent / "fixtures" / "sop").glob("a*/*.md"))


# ---- Counting (gold set, counted by hand) ----


@pytest.mark.parametrize(
    "word, count",
    [
        ("SDS", 3),  # read S-D-S
        ("PPE", 3),
        ("OSHA", 2),
        ("COSHH", 1),
        ("REACH", 1),
        ("SDSs", 4),
        ("ASTM", 4),  # no house entry, not a word: letter by letter
        ("WWW", 9),  # W is three syllables
        ("safety", 2),  # the vowel-group heuristic says 3; the dictionary says 2
        ("hazardous", 3),
        ("employer", 3),
        ("labels", 2),
    ],
)
def test_syllables_gold(word, count):
    assert r.syllables(word) == count


@pytest.mark.parametrize(
    "token, spoken",
    [("7", 2), ("11", 3), ("40%", 4), ("2024", 5), ("1,000", 3), ("3.5", 3), ("146,700", 12), ("1900", 4)],
)
def test_numbers_are_counted_as_spoken(token, spoken):
    assert r.spoken_syllables(token) == spoken
    assert r.number_syllables(token) == min(spoken, r.NUMBER_CAP)  # a figure is read at a glance


def test_abbreviations_initials_and_decimals_never_end_a_sentence():
    text = (
        "The U.S. rule applies to every site. See No. 5 for e.g. labels and pictograms. "
        "J. Smith set the limit at 2.5 ppm. Dr. Jones agreed. Is it optional? No. Employers must do it."
    )
    assert r.split_sentences(text) == [
        "The U.S. rule applies to every site.",
        "See No. 5 for e.g. labels and pictograms.",
        "J. Smith set the limit at 2.5 ppm.",
        "Dr. Jones agreed.",
        "Is it optional?",
        "No.",  # an answer, not "No. 5"
        "Employers must do it.",
    ]


def test_references_are_left_out_of_the_count_but_kept_in_the_sentence():
    sentence = "Under 29 CFR 1910.1200(h)(3), employers train workers (OSHA, 2024). See https://osha.gov/a."
    m = r.measure(sentence)
    assert [s.words for s in m.sentences] == [4, 1]  # Under employers train workers / See
    assert "1910.1200(h)(3)" in m.sentences[0].text  # a flagged sentence reads as written
    assert r.words(r.references_out("Section 1910.1200(c)(1) and Reg. 32(1)(b) apply.")) == [
        "Section", "and", "Reg", "apply",
    ]  # fmt: skip


def test_no_grade_below_min_words_and_one_counting_everywhere():
    short = "Workers read the label. " * 10  # 40 words
    assert r.fkgl(short) is None
    long = "Workers read the label before they open a new container of solvent. " * 10  # 120 words
    m = r.measure(long)
    assert m.words == 120 and len(m.sentences) == 10
    assert m.fkgl == round(r.formula(m.words, 10, m.syllables), 1)
    from apps.ai.evaluation import metrics as eval_metrics
    from apps.quality import scripts

    assert scripts.fkgl(long) == m.fkgl == eval_metrics.fkgl(long) == review.grade(long)


# ---- Diagnosis ----


def test_hard_and_very_hard_sentences_are_relative_to_the_target():
    easy = r.measure("Read the label first. Then put on your gloves and open the drum.")
    assert easy.hard(9) == ([], [])
    stacked = (
        "Employers that manufacture, import or distribute hazardous chemicals must classify each chemical, "
        "prepare a compliant safety data sheet and label, and communicate the hazard information downstream "
        "to every employer who receives the product."
    )
    grade = r.measure(stacked).sentences[0].grade
    assert grade > 16
    hard, very = r.measure(stacked).hard(grade - r.VERY_HARD_ABOVE - 0.1)
    assert very and not hard
    hard, very = r.measure(stacked).hard(grade - r.HARD_ABOVE - 0.1)
    assert hard and not very  # the same sentence against a higher (technical) target
    assert r.measure(stacked).hard(grade - r.HARD_ABOVE + 0.5) == ([], [])
    assert r.measure("Notification of unannounced organizational reclassifications is necessary.").hard(
        4
    ) == (
        [],
        [],
    )  # fewer than MIN_FLAG_WORDS words: never flagged


def test_complex_words_follow_yoast_with_ehs_terms_and_keywords_exempt():
    text = "The trajectory looked sensible. Trajectory matters. Store hazardous waste with its manifest."
    found = [w.lower() for w in r.complex_words(text, terms=["waste manifest"])]
    assert "trajectory" in found and "sensible" in found
    assert found.count("trajectory") == 1  # the capitalised one isn't counted
    assert "hazardous" not in found  # EHS term
    assert "manifest" not in found  # one of the brief's keywords
    assert "glossary" not in r.complex_words("Check the glossary (a list of terms) first.")  # glossed


@pytest.mark.parametrize(
    "sentence, passive",
    [
        ("Workers were consulted before the change.", True),
        ("The risk was not known.", True),
        ("Labels are usually written in English.", True),
        ("Employers train workers every year.", False),
        ("The supervisor is interested in the results.", False),
        ("Most sites are based in Ohio.", False),
    ],
)
def test_passive_voice(sentence, passive):
    assert r.is_passive(sentence) is passive


def test_tuning_gets_the_hard_sentences_hardest_first():
    section = (
        "## Storage\n\nKeep drums closed. "
        "Employers that manufacture, import or distribute hazardous chemicals must classify each chemical, "
        "prepare a compliant safety data sheet and label, and communicate the hazard information downstream "
        "to every employer who receives the product. Store acids low.\n"
    )
    assert review.stacked_sentences(section, target=9) == [
        "Employers that manufacture, import or distribute hazardous chemicals must classify each chemical, "
        "prepare a compliant safety data sheet and label, and communicate the hazard information downstream "
        "to every employer who receives the product."
    ]


def test_short_h3s_are_graded_with_the_next_ones_and_the_text_reassembles():
    answer = "A short answer that a newcomer can read in one go without stopping to think. " * 6  # 90 words
    faq = "## Frequently Asked Questions\n\n" + "".join(
        f"### Question {i}?\n\n{answer}\n\n" for i in range(4)
    )
    text = "## Intro part\n\n" + "Plain words. " * 20 + "\n\n" + faq
    units = review.section_units(text)
    assert "".join(h + b for h, b in units) == text
    rows = review.unit_rows(text, 9)
    faq_rows = [
        row for row in rows if "Question" in row["name"] or row["name"] == "Frequently Asked Questions"
    ]
    assert all(row["grade"] is not None for row in faq_rows)  # none left "too short to grade"
    # The empty H2 piece pools with questions 0 and 1; question 2 with question 3.
    assert [(row["name"], row["pooled"]) for row in faq_rows] == [
        ("Frequently Asked Questions", 2),
        ("Question 2?", 1),
    ]


# ---- Calibration on Fixture A (the owner's approved articles) ----


@pytest.mark.skipif(not FIXTURE_A, reason="no Fixture A articles")
def test_fixture_a_calibration():
    """The flags are advisory and calibrated so the owner's approved articles show a few hard sentences per
    section, very hard ones rarely, and complex words under Yoast's 10% (docs/reading-grade-options.md)."""
    sections = hard = very = 0
    for path in FIXTURE_A:
        body = path.read_text(encoding="utf-8").split("---\n", 2)[2]
        article = review.article_metrics(body, 9)
        assert not article["complex_over"], path.stem
        for row in review.unit_rows(body, 9):
            if row["grade"] is None:
                continue
            sections += 1
            hard += len(row["hard"])
            very += len(row["very_hard"])
    assert sections >= 20
    assert hard / sections <= 2.5
    assert very / sections <= 1.0
