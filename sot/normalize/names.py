"""Parsing a person's name.

Names are where identity resolution either works or does not, and the four systems
each write them differently: given name first, family name first with a comma, shouted
in capitals, with a middle initial, with a credential trailing after it. All of those
have to reduce to the same comparison key while keeping a display form that a person
would recognise as their own name.

Two keys come out of this, and the distinction matters. The *comparison* key is folded
hard - accents stripped, punctuation removed, lowercased - because an exporting system
that cannot write accents has not given us a different person. The *display* form keeps
every accent and apostrophe, because getting somebody's name wrong on screen is its own
kind of failure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sot.canon import nfkd_fold, squeeze
from sot.normalize.result import Normalized, Quality, ambiguous, empty, invalid, ok, repaired

#: Generational suffixes, folded for comparison.
SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v", "2nd", "3rd"})

#: Clinical licences that nobody is named after. Safe to strip even when doing so
#: leaves a single word, because the alternative is a surname of "Rn".
UNAMBIGUOUS_CREDENTIALS = frozenset(
    {
        "rn",
        "lpn",
        "lvn",
        "cna",
        "stna",
        "cma",
        "aprn",
        "crna",
        "cnm",
        "bsn",
        "msn",
        "adn",
        "lmsw",
        "lcsw",
        "rna",
    }
)

#: Credentials that trail a name and are not part of it. The wider set includes
#: abbreviations that double as surnames or initials (MA, BS, DO), so those are only
#: stripped when enough words remain for the result to still be a name.
CREDENTIAL_TOKENS = frozenset(
    {
        "rn",
        "lpn",
        "lvn",
        "cna",
        "stna",
        "cma",
        "np",
        "aprn",
        "don",
        "rna",
        "bsn",
        "msn",
        "adn",
        "md",
        "do",
        "pa",
        "pt",
        "ot",
        "slp",
        "rd",
        "lmsw",
        "lcsw",
        "crna",
        "cnm",
        "phd",
        "ma",
        "ba",
        "bs",
        "ms",
    }
)

#: Lowercase particles that belong to the family name rather than being given names.
#: Multi-word particles are matched longest-first.
PARTICLES = (
    "van der",
    "van den",
    "van de",
    "de la",
    "de los",
    "de las",
    "de le",
    "del",
    "della",
    "dos",
    "das",
    "de",
    "da",
    "di",
    "du",
    "van",
    "von",
    "le",
    "la",
    "los",
    "las",
    "bin",
    "ibn",
    "al",
    "st.",
    "st",
    "mc",
    "o'",
)

#: Characters after which a name capitalises again - a double-barrelled surname or
#: an Irish one. Includes the curly apostrophe, which is what a word processor
#: produces when somebody retypes a name.
APOSTROPHES_AND_HYPHENS = "'-" + chr(0x2019)

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_NON_ALNUM = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True)
class PersonName:
    """A parsed name, in both the form we compare and the form we show."""

    raw: str
    given: str = ""
    middle: str = ""
    family: str = ""
    suffix: str = ""
    credentials: tuple[str, ...] = ()

    @property
    def display(self) -> str:
        """How the name should be written on screen."""
        parts = [self.given, self.middle, self.family]
        name = " ".join(part for part in parts if part)
        return f"{name} {self.suffix}".strip() if self.suffix else name

    @property
    def family_key(self) -> str:
        return fold(self.family)

    @property
    def given_key(self) -> str:
        return fold(self.given)

    @property
    def middle_initial(self) -> str:
        return fold(self.middle)[:1]

    @property
    def key(self) -> str:
        """Comparison key: family then given, folded. Stable across all four systems."""
        return f"{self.family_key} {self.given_key}".strip()

    @property
    def is_complete(self) -> bool:
        return bool(self.family and self.given)


def fold(text: str) -> str:
    """Comparison form: accents stripped, punctuation removed, lowercased."""
    return _NON_ALNUM.sub("", nfkd_fold(text).lower())


def name_key(text: str) -> str:
    """Comparison key for an unparsed name string."""
    parsed = parse_name(text)
    return parsed.value.key if parsed.value else fold(text)


def titlecase(text: str) -> str:
    """Capitalize a name the way a person writes it.

    Only applied when the source shouted or whispered - ALL CAPS or all lowercase.
    Mixed case is left exactly as it is, because a source that has bothered to write
    a lowercase particle or an internal capital already knows better than we do.
    """
    stripped = text.strip()
    if not stripped:
        return ""
    has_upper = any(ch.isupper() for ch in stripped)
    has_lower = any(ch.islower() for ch in stripped)
    if has_upper and has_lower:
        return stripped

    def cap_word(word: str) -> str:
        if not word:
            return word
        # Capitalize after an apostrophe or hyphen too, which double-barrelled and
        # Irish surnames need.
        out: list[str] = []
        capitalize_next = True
        for index, ch in enumerate(word):
            if capitalize_next and ch.isalpha():
                out.append(ch.upper())
                capitalize_next = False
            else:
                out.append(ch.lower())
            if ch in APOSTROPHES_AND_HYPHENS and index < len(word) - 1:
                capitalize_next = True
        rebuilt = "".join(out)
        # Mc and Mac take a second capital on the syllable that follows them.
        if len(rebuilt) > 2 and rebuilt[:2] == "Mc" and rebuilt[2].isalpha():
            rebuilt = "Mc" + rebuilt[2].upper() + rebuilt[3:]
        return rebuilt

    return " ".join(cap_word(word) for word in stripped.split())


def _strip_credentials(text: str) -> tuple[str, tuple[str, ...]]:
    """Remove trailing professional credentials, returning them separately."""
    found: list[str] = []
    working = text.strip().rstrip(",;")

    # Comma-separated trailing groups, as in "Family, Given, RN, BSN".
    while "," in working:
        head, _, tail = working.rpartition(",")
        tokens = [token for token in re.split(r"[\s/]+", tail.strip()) if token]
        folded = [fold(token) for token in tokens]
        if tokens and all(token in CREDENTIAL_TOKENS for token in folded if token):
            found = tokens + found
            working = head.rstrip(" ,;")
            continue
        break

    # Space-separated trailing credential, but only when it shouts: "Given Family RN".
    # A lowercase trailing token is far more likely to be part of the name.
    #
    # Two words is the delicate case. "DOE RN" is a name and a credential, but "ANN MA"
    # is a given name and a surname, and "JOHN BS" could be either. So a two-word value
    # only gives up its last token if that token is a clinical licence nobody is named
    # after; three or more words can afford to be less cautious.
    words = working.split()
    while len(words) > 1 and words[-1].isupper():
        token = fold(words[-1])
        if len(words) > 2 and token in CREDENTIAL_TOKENS:
            found.insert(0, words.pop())
            continue
        if token in UNAMBIGUOUS_CREDENTIALS:
            found.insert(0, words.pop())
            continue
        break
    return (" ".join(words), tuple(found))


def _split_suffix(tokens: list[str]) -> tuple[list[str], str]:
    """Pull a generational suffix off the end of a token list."""
    if len(tokens) > 1 and fold(tokens[-1]) in SUFFIXES:
        return tokens[:-1], tokens[-1].rstrip(".") if tokens[-1] != "V" else tokens[-1]
    return tokens, ""


def _absorb_particles(tokens: list[str]) -> tuple[list[str], str]:
    """Split ``[given..., particle..., family]`` into given tokens and a family name.

    A particle and everything after it is one family name. Scanning from the left for
    the first particle gets this right, and leaves names without particles alone.
    """
    folded = [fold(token) for token in tokens]
    for start in range(len(tokens) - 1):
        for particle in PARTICLES:
            words = particle.split()
            span = len(words)
            if start + span >= len(tokens):
                continue
            if [fold(word) for word in words] == folded[start : start + span]:
                return tokens[:start], " ".join(tokens[start:])
    return tokens[:-1], tokens[-1]


def parse_name(raw: str) -> Normalized[PersonName]:
    """Parse a name in any of the orders the four systems use."""
    if raw is None:
        return empty("")
    text = squeeze(str(raw))
    if not text:
        return empty(str(raw))
    if not any(ch.isalpha() for ch in text):
        return invalid(text, "no letters in the value")

    notes: list[str] = []
    quality = Quality.OK

    body, credentials = _strip_credentials(text)
    if credentials:
        notes.append(f"credentials {', '.join(credentials)} removed from the name")
        quality = Quality.REPAIRED
    if body != text and not credentials:
        quality = Quality.REPAIRED

    if "," in body:
        family_part, _, given_part = body.partition(",")
        family_tokens = [token for token in family_part.split() if token]
        given_tokens = [token for token in given_part.split() if token]
        given_tokens, suffix = _split_suffix(given_tokens)
        if not suffix:
            family_tokens, suffix = _split_suffix(family_tokens)
        family = " ".join(family_tokens)
        given = given_tokens[0] if given_tokens else ""
        middle = " ".join(given_tokens[1:])
    else:
        tokens = [token for token in body.split() if token]
        tokens, suffix = _split_suffix(tokens)
        if not tokens:
            return invalid(text, "nothing left after removing suffixes and credentials")
        if len(tokens) == 1:
            # One word. Treated as a family name, but nobody can be sure.
            return ambiguous(
                PersonName(
                    raw=text, family=titlecase(tokens[0]), suffix=suffix, credentials=credentials
                ),
                text,
                "single-word name; treated as a family name",
            )
        given_tokens, family = _absorb_particles(tokens)
        given = given_tokens[0] if given_tokens else ""
        middle = " ".join(given_tokens[1:])

    if not family:
        return invalid(text, "no family name could be identified")

    name = PersonName(
        raw=text,
        given=titlecase(given),
        middle=titlecase(middle),
        family=titlecase(family),
        suffix=suffix,
        credentials=credentials,
    )
    note = "; ".join(notes)
    if quality is Quality.REPAIRED:
        return repaired(name, text, note)
    return ok(name, text, note)


def looks_like_initial(token: str) -> bool:
    """True for a single letter, with or without a full stop: an initial rather than
    a given name."""
    cleaned = token.strip().rstrip(".")
    return len(cleaned) == 1 and cleaned.isalpha()
