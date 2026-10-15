"""One reading-grade counting for the whole studio (docs/reading-grade-options.md, option C).

The grade stays Flesch-Kincaid (FKGL = 0.39 x words per sentence + 11.8 x syllables per word - 15.59), the
formula the briefs, the guest-post sheet and the blog skill speak, but counted accurately and with the
diagnosis Hemingway and Yoast give a writer:

- Syllables: a house lexicon for EHS acronyms (SDS is read S-D-S, 3), the CMU Pronouncing Dictionary
  (`data/syllables.tsv`: only the words where it disagrees with the skill's vowel-group heuristic), then that
  heuristic. Short or vowel-less acronyms are read letter by letter (W counts 3).
- A number is one word with the syllables of its spoken form; citations ("1910.1200(c)(1)", "29 CFR
  1910.1200"), URLs and parenthetical sources ("(OSHA, 2024)") are references, not prose, and aren't counted.
- Sentences never end at an abbreviation (e.g., U.S., No., Fig.) or an initial.
- No grade below MIN_WORDS words: FKGL on a short section is noise.
- Diagnosis: each sentence's own grade, flagged hard or very hard relative to the target (Hemingway); the
  grade split into its two drivers, sentence length and word length (Yoast's reason for dropping one number);
  complex words (Yoast's rule, EHS terms exempt) and the passive-voice share. All advisory: never a block.

Everything here is deterministic and needs no model; `build_wordlists.py` regenerates the data files.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

DATA = Path(__file__).parent / "data"

MIN_WORDS = 100  # graded from here (docs/content-editing-plan.md, reading grade step 6)
MARGIN = 0.5  # FKGL is an estimate: shown as grade ± this
LONG_SENTENCE = 25  # words; the share over it is what tuning changes
# Sentence flags relative to the brief's target, calibrated on Fixture A (the owner's approved articles): a
# few hard sentences per section there, very hard ones rare. See docs/reading-grade-options.md › Built.
HARD_ABOVE = 6.0
VERY_HARD_ABOVE = 10.0
MIN_FLAG_WORDS = 12  # a short sentence is never flagged, however long its words
COMPLEX_LETTERS = 7  # Yoast: a word longer than this, outside the frequent words, not capitalised
COMPLEX_SHARE = 10.0  # percent of words; Yoast's warning level
PASSIVE_SHARE = 10.0  # percent of sentences; Yoast's recommended maximum


# ---- Syllables ----

# How EHS acronyms are read aloud (letter by letter unless spoken as a word).
LEXICON = {
    "SDS": 3, "PPE": 3, "GHS": 3, "HSE": 3, "CLP": 3, "JSA": 3, "JHA": 3, "EHS": 3,
    "OSHA": 2, "WHMIS": 2, "COSHH": 1, "REACH": 1, "SWMS": 1, "WHS": 3, "HAZCOM": 3, "HazCom": 3,
    "NIOSH": 2, "ANSI": 2, "NEBOSH": 2, "RIDDOR": 2, "DSEAR": 2, "HAZMAT": 3, "HAZOP": 3, "LOTO": 2,
    "MSDS": 4, "SKU": 3, "ISO": 3, "EPA": 3, "DOT": 3, "CFR": 3, "NFPA": 4, "OHS": 3, "AU": 2, "UK": 2,
    "US": 2, "EU": 2,
}  # fmt: skip
LETTER_SYLLABLES = {"W": 3}


def heuristic_syllables(word):
    """The blog skill's vowel-group count with its silent-e rule (vendor/ehs_seo_blog/scripts/metrics.py),
    used for words the dictionary doesn't know."""
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not word.endswith(("le", "ee", "ie")) and count > 1:
        count -= 1
    return max(1, count)


@cache
def _dictionary():
    """{word: syllables} from the CMU Pronouncing Dictionary, only where it differs from the heuristic."""
    table = {}
    path = DATA / "syllables.tsv"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                word, _, count = line.partition("\t")
                table[word] = int(count)
    return table


def _letters(token):
    return sum(LETTER_SYLLABLES.get(letter, 1) for letter in token.upper() if letter.isalpha())


def syllables(word):
    """Syllables in one word as it is read aloud."""
    if word in LEXICON:
        return LEXICON[word]
    bare = re.sub(r"['’]s$|(?<=[A-Z])s$", "", word)  # SDS's, SDSs
    if bare in LEXICON:
        return LEXICON[bare] + (0 if bare == word else 1)
    lower = word.lower().replace("’", "'")
    if bare.isupper() and len(bare) >= 2:
        if len(bare) <= 3 or not re.search(r"[AEIOUY]", bare) or lower not in _known():
            return _letters(bare)
    table = _dictionary()
    if lower in table:
        return table[lower]
    return heuristic_syllables(lower)


@cache
def _known():
    """Words the dictionary can read (for acronyms read as words, such as REACH): the table's words plus
    the frequent words, a good stand-in for "a real word" without shipping the whole dictionary."""
    return set(_dictionary()) | _frequent()


# ---- Numbers ----

ONES = {0: 2, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 2, 8: 1, 9: 1, 10: 1, 11: 3, 12: 1, 13: 2, 14: 2, 15: 2}
ONES |= {16: 2, 17: 3, 18: 2, 19: 2}
TENS = {2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 3, 8: 2, 9: 2}
SCALES = [(10**9, 2), (10**6, 2), (1000, 2)]  # billion, million, thousand


def _integer_syllables(n):
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + (ONES[n % 10] if n % 10 else 0)
    if n < 1000:
        return ONES[n // 100] + 2 + (_integer_syllables(n % 100) if n % 100 else 0)  # "hundred"
    for scale, cost in SCALES:
        if n >= scale:
            rest = n % scale
            return _integer_syllables(n // scale) + cost + (_integer_syllables(rest) if rest else 0)
    return ONES[0]


NUMBER_CAP = 2  # a figure is read at a glance, not spelled out


def number_syllables(token):
    """Syllables of a number: its spoken form ("seven" 2, "40%" forty percent), capped at NUMBER_CAP. Counted
    in full, "146,700 claims in 2023 to 2024" read as a grade-26 sentence on Fixture A, though a reader takes
    in a figure at a glance."""
    return min(spoken_syllables(token), NUMBER_CAP)


def spoken_syllables(token):
    """Syllables of a number as it is said: "2024" twenty twenty-four, "3.5" three point five, "40%"
    forty percent, "1,000" one thousand."""
    percent = token.endswith("%")
    digits = token.rstrip("%").replace(",", "")
    whole, _, decimals = digits.partition(".")
    count = 0
    if whole:
        n = int(whole)
        year = len(whole) == 4 and not decimals and "," not in token and 1100 <= n <= 2099
        if year and n % 100 >= 10:
            count = _integer_syllables(n // 100) + _integer_syllables(n % 100)  # "twenty twenty-four"
        elif year and n % 100 == 0 and n % 1000:
            count = _integer_syllables(n // 100) + 2  # "nineteen hundred"
        else:
            count = _integer_syllables(n)
    if decimals:
        count += 1 + sum(ONES[int(d)] for d in decimals)  # "point" and each digit
    return count + (2 if percent else 0)


# ---- Text to sentences and words ----

URL = re.compile(r"(?:https?|wagtail)://\S+|\bwww\.\S+")
# "29 CFR 1910.1200(h)(3)", "1910.1200(c)(1)", "Reg. 32(1)(b)" ids, "§ 1910.134": references, not prose.
CITATION = re.compile(
    r"(?:\b\d+\s+(?:CFR|U\.S\.C\.|USC)\s+)?§*\s?\b\d+(?:\.\d+)+(?:\([0-9a-zA-Z]+\))*"
    r"|\b\d+(?:\([0-9a-zA-Z]{1,4}\))+"  # "32(1)(b)"
    r"|(?<=\w)(?:\([0-9a-z]{1,4}\))+(?=[\s,.;:)]|$)"
)
SOURCE = re.compile(r"\(\s*(?:[A-Z][^()]{0,80}?,?\s*)?(?:19|20)\d{2}[a-z]?\s*\)")
ABBREVIATIONS = {
    "e.g", "i.e", "etc", "vs", "no", "nos", "u.s", "u.k", "u.s.a", "reg", "regs", "fig", "figs", "dr", "mr",
    "mrs", "ms", "st", "approx", "inc", "ltd", "co", "corp", "sec", "art", "pt", "vol", "dept", "est", "jan",
    "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "cf", "ca", "al", "p", "pp",
}  # fmt: skip
# Abbreviations only before a number: "No. 5" goes on, but an FAQ answer's "No. Employers…" ends a sentence.
BEFORE_NUMBER = {"no", "nos", "reg", "regs", "fig", "figs", "sec", "art", "pt", "vol", "p", "pp"}
SENTENCE_END = re.compile(r"([.!?])([\"'”’)\]]*)\s+(?=[\"'“‘(\[]?[A-Z0-9])")
WORD = re.compile(r"\d[\d,]*(?:\.\d+)?%?|[A-Za-z]+(?:['’][A-Za-z]+)*")


def strip_markdown(text):
    """The skill's light Markdown strip (links to their anchor text, no code, headings or table pipes)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"[*_>#|]", " ", text)
    return re.sub(r"(?m)^\s*[-+]\s+", "", text)


def references_out(text):
    """Leave URLs, citations and parenthetical sources out of the count; the sentence around them stays."""
    text = URL.sub(" ", text)
    text = SOURCE.sub(" ", text)
    return CITATION.sub(" ", text)


def split_sentences(text):
    """Sentences of plain text; an abbreviation, an initial or a decimal never ends one."""
    text = re.sub(r"\s+", " ", text).strip()
    sentences, start = [], 0
    for match in SENTENCE_END.finditer(text):
        before = text[start : match.start(1)]
        last = re.search(r"([A-Za-z.]+)$", before)
        if match.group(1) == "." and last:
            token = last.group(1).lower().strip(".")
            before_number = text[match.end()].isdigit()
            if token in BEFORE_NUMBER and not before_number:
                pass
            elif (
                token in ABBREVIATIONS
                or re.fullmatch(r"[A-Z]", last.group(1))
                or re.fullmatch(r"(?:[a-z]\.)+[a-z]", token)
            ):
                continue
        sentences.append(text[start : match.end(2)].strip())
        start = match.end()
    sentences.append(text[start:].strip())
    return [s for s in sentences if re.search(r"[A-Za-z]", s)]


def words(sentence):
    return WORD.findall(sentence)


def word_syllables(token):
    return number_syllables(token) if token[0].isdigit() else syllables(token)


def formula(n_words, n_sentences, n_syllables):
    """Flesch-Kincaid grade level (Kincaid et al., 1975)."""
    return 0.39 * n_words / n_sentences + 11.8 * n_syllables / n_words - 15.59


# ---- Word complexity and passive voice ----


@cache
def _frequent():
    """The 5,000 most frequent English words (wordfreq, see data/frequent-words.txt)."""
    path = DATA / "frequent-words.txt"
    if not path.exists():
        return frozenset()
    return frozenset(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line and line[0] != "#"
    )


@cache
def _ehs_terms():
    """Domain words a newcomer article needs and glosses (data/ehs-terms.txt): never counted as complex."""
    path = DATA / "ehs-terms.txt"
    if not path.exists():
        return frozenset()
    return frozenset(
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and line[0] != "#"
    )


SUFFIXES = ("'s", "s", "es", "ed", "d", "ing", "ly", "er", "ers", "ies", "ied", "ation", "ations")


def _common(word):
    """In the frequent words, or an inflection of one ("sensibly", "regulations")."""
    frequent = _frequent()
    if word in frequent:
        return True
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            stem = word[: -len(suffix)]
            if {stem, stem + "e", stem + "y"} & frequent or (
                suffix in ("ies", "ied") and stem + "y" in frequent
            ):
                return True
    return False


def complex_words(text, terms=()):
    """Yoast's complex words: longer than COMPLEX_LETTERS letters, not among the frequent words, not
    capitalised. EHS terms, the brief's keywords and terms the text glosses in brackets are exempt."""
    glossed = {m.lower() for m in re.findall(r"\b([A-Za-z-]+)\s+\(", text)}
    exempt = _ehs_terms() | glossed | {w.lower() for term in terms for w in re.findall(r"[A-Za-z]+", term)}
    found = []
    for token in re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)*", text):
        lower = token.lower().replace("’", "'")
        if len(token) <= COMPLEX_LETTERS or token[0].isupper() or lower in exempt:
            continue
        stem = re.sub(r"(?:'s|s)$", "", lower)
        if stem in exempt or _common(lower):
            continue
        found.append(token)
    return found


BE = r"(?:am|is|are|was|were|be|been|being|isn't|aren't|wasn't|weren't|get|gets|got|gotten|getting)"
IRREGULAR = (
    "known given taken made done seen written shown held kept found built sent set put paid told run "
    "brought bought caught taught thought left lost meant met read sold spent understood worn torn drawn "
    "driven broken chosen frozen spoken stolen forgotten hidden fallen forbidden shaken thrown grown "
    "withdrawn begun hung struck stuck bound fed led shed cut hit hurt let shut split spread cast cost "
    "overseen undertaken"
).split()
NOT_PASSIVE = {"interested", "tired", "concerned", "used", "supposed", "based", "related", "involved", "aged"}
PASSIVE = re.compile(
    rf"\b{BE}\s+(?:not\s+|never\s+|also\s+|often\s+|usually\s+|\w+ly\s+)?([a-z]+ed|{'|'.join(IRREGULAR)})\b",
    re.I,
)


def is_passive(sentence):
    return any(m.group(1).lower() not in NOT_PASSIVE for m in PASSIVE.finditer(sentence))


# ---- Measuring ----


@dataclass
class Sentence:
    text: str
    words: int
    syllables: int
    grade: float
    passive: bool = False


@dataclass
class Measure:
    sentences: list = field(default_factory=list)
    words: int = 0
    syllables: int = 0
    complex: list = field(default_factory=list)

    @property
    def fkgl(self):
        """The grade, or None below MIN_WORDS words."""
        if self.words < MIN_WORDS or not self.sentences:
            return None
        return round(formula(self.words, len(self.sentences), self.syllables), 1)

    @property
    def words_per_sentence(self):
        return round(self.words / len(self.sentences), 1) if self.sentences else None

    @property
    def syllables_per_word(self):
        return round(self.syllables / self.words, 2) if self.words else None

    def long_share(self, limit=LONG_SENTENCE):
        """Percent of sentences over `limit` words."""
        if not self.sentences:
            return 0
        return round(100 * sum(s.words > limit for s in self.sentences) / len(self.sentences))

    @property
    def passive_share(self):
        if not self.sentences:
            return 0
        return round(100 * sum(s.passive for s in self.sentences) / len(self.sentences))

    @property
    def complex_share(self):
        return round(100 * len(self.complex) / self.words, 1) if self.words else 0

    def hard(self, target):
        """(hard, very hard) sentences relative to `target`, in reading order."""
        if target is None:
            return [], []
        long_enough = [s for s in self.sentences if s.words >= MIN_FLAG_WORDS]
        very = [s for s in long_enough if s.grade >= float(target) + VERY_HARD_ABOVE]
        hard = [
            s for s in long_enough if float(target) + HARD_ABOVE <= s.grade < float(target) + VERY_HARD_ABOVE
        ]
        return hard, very


def length_distribution(sentences):
    """The skill's sentence-length bands (metrics.py), over this module's sentences and words."""
    lengths = [s.words for s in sentences]
    if not lengths:
        return {}
    buckets = {"1-8": 0, "9-15": 0, "16-24": 0, "25+": 0}
    for n in lengths:
        band = "1-8" if n <= 8 else "9-15" if n <= 15 else "16-24" if n <= 24 else "25+"
        buckets[band] += 1
    return {
        "count": len(lengths),
        "mean": round(sum(lengths) / len(lengths), 1),
        "buckets": buckets,
        "flatness_ratio": round(max(buckets.values()) / len(lengths), 2),
    }


def measure(text, terms=()):
    """Measure plain or lightly marked-up prose (callers strip headings, tables and markers first)."""
    plain = strip_markdown(text)
    result = Measure()
    # Split before the references come out, so a flagged sentence reads as the writer wrote it.
    for sentence in split_sentences(plain):
        tokens = words(references_out(sentence))
        if not tokens:
            continue
        count = sum(word_syllables(t) for t in tokens)
        result.sentences.append(
            Sentence(
                sentence, len(tokens), count, round(formula(len(tokens), 1, count), 1), is_passive(sentence)
            )
        )
        result.words += len(tokens)
        result.syllables += count
    result.complex = complex_words(references_out(plain), terms)
    return result


def fkgl(text):
    """FKGL of a text with the studio's counting; None below MIN_WORDS words."""
    return measure(text).fkgl
