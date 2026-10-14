"""The research step's "Questions for the Requester" as a form.

Research ends with up to five questions the brief leaves open, each with the model's assumed answer, so an
autopilot run can go on without a person. When a person reviews the research, the studio shows those
questions as a form; the answers are written back into the research text as "Answer from the requester:"
lines and saved as an edited version. The outline and the draft read the approved research, so the answers
reach every later step without a prompt change.
"""

import re

SECTION = "Questions for the Requester"
HEADING = re.compile(r"(?im)^##\s+questions for the requester\s*:?\s*$")
ITEM = re.compile(r"(?m)^\s*(\d+)[.)]\s+")
LABEL = re.compile(
    r"\s*[-–—(]?\s*[*_]*\s*(answer from the requester|assumed answer|my assumption|assumption|assumed|"
    r"default)\s*[*_]*\s*[:：]\s*[*_]*\s*",
    re.I,
)
ANSWERED = "Answer from the requester"
MAX_QUESTIONS = 5


def _span(text):
    """(start, end) of the section body, or None."""
    match = HEADING.search(text or "")
    if not match:
        return None
    following = re.search(r"(?m)^##\s+", text[match.end() :])
    return match.end(), match.end() + following.start() if following else len(text)


def _plain(value):
    value = " ".join((value or "").split())
    return re.sub(r"^[*_]+|[*_]+$", "", value).strip().rstrip(")").strip()


def _assumption(rest):
    rest = " ".join((rest or "").split())
    wrapped = rest.lstrip(" ,;:–—-").startswith("(")
    rest = re.sub(r"^[\s,;:–—\-(*_]+", "", rest)
    if wrapped:
        rest = re.sub(r"\)\s*\.?\s*$", "", rest)
    rest = re.sub(r"(?i)^(?:assumed answer|assumption|assumed|assuming|assume|default)\b[\s:,]*", "", rest)
    rest = rest.replace("**", "").strip(" *_")
    # A lone "(body)" or "(FAQ)" is the questions-searchers-ask marker, not an assumption.
    return "" if re.fullmatch(r"(?i)body|faq", rest) else rest


def _from_table(body):
    rows = [r.strip().strip("|").split("|") for r in body.splitlines() if r.strip().startswith("|")]
    rows = [[_plain(c) for c in r] for r in rows if not all(re.fullmatch(r"\s*:?-{2,}:?\s*", c) for c in r)]
    if len(rows) < 2:
        return []
    header = [c.lower() for c in rows[0]]
    q = next((i for i, c in enumerate(header) if "question" in c), None)
    a = next((i for i, c in enumerate(header) if "assum" in c or "answer" in c), None)
    if q is None:
        return []
    return [
        {"question": r[q], "assumed": r[a] if a is not None and a < len(r) else "", "answered": False}
        for r in rows[1:]
        if q < len(r) and r[q]
    ]


def parse(text):
    """[{question, assumed, answered}] from the research text; [] when the section is missing or "None"."""
    span = _span(text)
    if not span:
        return []
    body = text[span[0] : span[1]].strip()
    if not body or re.match(r"(?i)^[*_]*none\b", body):
        return []
    starts = list(ITEM.finditer(body))
    if not starts:
        return _from_table(body)[:MAX_QUESTIONS]
    questions = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(body)
        item = body[match.end() : end].strip()
        label = LABEL.search(item)
        if label:  # "… Assumed answer: x", "*Assumed:* x"
            question, assumed = item[: label.start()], item[label.end() :]
        elif ask := re.match(r"(?s)^(.*?\?)[*_]*(.*)$", item):
            # What models write: "**Q?**, Assumed **yes** (…)", "**Q?** – assumed …", "**Q?** (Assumed …)",
            # "Q?, *Assume we …*". The question runs to its first "?"; the rest is the assumption.
            question, assumed = ask.group(1), _assumption(ask.group(2))
        else:
            question, assumed = item, ""
        questions.append(
            {
                "question": _plain(question),
                "assumed": _plain(assumed),
                "answered": bool(label and label.group(1).lower() == ANSWERED.lower()),
            }
        )
    return [q for q in questions if q["question"]][:MAX_QUESTIONS]


def apply_answers(text, answers):
    """The research text with the section rewritten: each question with the requester's answer, or with the
    model's assumed answer where the answer was left empty. `answers` follows parse()'s order."""
    span = _span(text)
    questions = parse(text)
    if not span or not questions:
        raise ValueError("This research has no questions for the requester.")
    lines = []
    for number, question in enumerate(questions, 1):
        answer = " ".join((answers[number - 1] if number - 1 < len(answers) else "").split())
        if answer:
            lines.append(f"{number}. {question['question']}\n   {ANSWERED}: {answer}")
        elif question["assumed"]:
            label = ANSWERED if question["answered"] else "Assumed answer"
            lines.append(f"{number}. {question['question']}\n   {label}: {question['assumed']}")
        else:
            lines.append(f"{number}. {question['question']}")
    return text[: span[0]] + "\n\n" + "\n\n".join(lines) + "\n\n" + text[span[1] :].lstrip("\n")
