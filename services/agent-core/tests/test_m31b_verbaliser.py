"""VOC-08 golden conventions and fail-closed speech formatting, without audio or a model runtime."""

import re

import pytest
from agent_core.engine.verbaliser import FALLBACK, MAX_TEXT, SpeechText, verbalise
from hypothesis import given, settings
from hypothesis import strategies as st

WORDS = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
)

# These expected readings are authored independently of the parser and its number tables.
CONVENTIONS = [
    (r"x^2", "x squared"),
    (r"x^3", "x cubed"),
    (r"x^n", "x to the power n"),
    (r"\frac{3}{4}", "three quarters"),
    (r"\frac{1}{2}", "one half"),
    (r"\frac{1}{3}", "one third"),
    (r"\frac{2}{3}", "two thirds"),
    (r"\frac{a}{b}", "a over b"),
    (r"9.8\,\text{m s}^{-2}", "nine point eight metres per second squared"),
    (r"C_3H_8", "C three H eight"),
    (r"C_{3}H_{8}", "C three H eight"),
    (r"CO_2", "C O two"),
    (r"CH_4", "C H four"),
    (r"NH_3", "N H three"),
    (r"H_2O", "H two O"),
    (r"Fe_2O_3", "Fe two O three"),
    (r"Mg^{2+}", "Mg two plus"),
    (r"Al^{3+}", "Al three plus"),
    (r"Cl^{-}", "Cl minus"),
    (r"Na^{+}", "Na plus"),
    (r"SO_4^{2-}", "S O four two minus"),
    (r"CH_4 + 2O_2 \rightarrow CO_2 + 2H_2O", "C H four plus two O two gives C O two plus two H two O"),
    (r"\rightarrow", "gives"),
    ("$12,500", "twelve thousand five hundred dollars"),
    (r"\sqrt{x+1}", "the square root of x plus one, end root"),
    ("-3", "negative three"),
    ("5-3", "five minus three"),
    (r"\le", "is less than or equal to"),
    (r"\ne", "is not equal to"),
    (r"\geq", "is greater than or equal to"),
    (r"\approx", "is approximately equal to"),
    (r"\pi r^2", "pi r squared"),
    (r"\frac{x+1}{y-2}", "the fraction x plus one over y minus two, end fraction"),
    (r"\sqrt{\frac{a}{b}}", "the square root of a over b, end root"),
    (r"\frac{1}{\sqrt{x}}", "the fraction one over the square root of x, end root, end fraction"),
    (r"x^{n+1}", "x to the power n plus one, end power"),
    (r"x^{-2}", "x to the power negative two, end power"),
    (r"x_i", "x sub i"),
    (r"x_{12}", "x sub twelve"),
    (r"x^23", "x squared three"),
    (r"\left(x+1\right)^2", "open bracket x plus one close bracket squared"),
    ("2*(3+4)", "two times open bracket three plus four close bracket"),
    ("2+-3", "two plus negative three"),
    (r"2\times 10^{3}", "two times ten cubed"),
    ("0.005", "zero point zero zero five"),
    ("100.20", "one hundred point two zero"),
    ("1,001", "one thousand one"),
    ("1,000,000", "one million"),
    ("1,000,000,000", "one billion"),
    ("1,000,000,000,000", "one trillion"),
    ("999", "nine hundred ninety nine"),
    ("$1", "one dollar"),
    ("$5.25", "five point two five dollars"),
    ("We have $12,500 and $3.", "We have twelve thousand five hundred dollars and three dollars."),
    ("Try -3 next.", "Try negative three next."),
    ("Don't change the student's answer.", "Don't change the student's answer."),
    (r"Try $x^2$ next.", "Try x squared next."),
    (r"Use \(x^2\) then \[y^3\].", "Use x squared then y cubed."),
    (r"$$2+2=4$$", "two plus two equals four"),
    ("$2+2$", "two plus two"),
    (r"## Try **$x^2$**", "Try x squared"),
    ("See [the board](https://example.invalid/private).", "See the board."),
    (r"Use `x^2`.", "Use x squared."),
    ("Try *again*.", "Try again."),
    (r"\dfrac{a}{b}", "a over b"),
    (r"\tfrac{a}{b}", "a over b"),
    (r"\text{kg}", "kilograms"),
    (r"\mathrm{cm}^2", "centimetres squared"),
    (r"\text{m s}^{-1}", "metres per second"),
    (r"\text{m s}^{-3}", "metres per second cubed"),
    (r"\theta", "theta"),
    (r"\pi-1", "pi minus one"),
    (r"\infty-1", "infinity minus one"),
    # Read-aloud samples (D95 voice bake-off): a prose colon is a pause, never the ratio word; a coefficient glued to
    # letters is a product of variables, never an English word; ratios still read as ratios.
    (
        "Every transaction touches two accounts: when cash comes in",
        "Every transaction touches two accounts: when cash comes in",
    ),
    ("Note: add 2 to both sides.", "Note: add two to both sides."),
    ("Step 1: subtract.", "Step one: subtract."),
    ("The ratio is 3:4.", "The ratio is three to four."),
    ("Mix them in the ratio 2 : 3 : 5.", "Mix them in the ratio two to three to five."),
    (r"$x:y = 1:2$", "x to y equals one to two"),
    (r"$(a+b):c$", "open bracket a plus b close bracket to c"),
    (r"$v^2 = u^2 + 2as$", "v squared equals u squared plus two a s"),
    (r"$s = ut + \frac{1}{2}at^2$", "s equals u t plus one half a t squared"),
    (r"$b^2 - 4ac$", "b squared minus four a c"),
    ("2ab", "two a b"),
    (r"$\text{cash} + x$", "cash plus x"),
    ("C₃H₈", FALLBACK),  # unsupported Unicode subscripts must never reach speech raw
    ("x²", FALLBACK),
    ("", ""),
]


def golden_cases():
    cases = list(CONVENTIONS)
    for n, word in enumerate(WORDS):
        cases.extend(
            [
                (str(n), word),
                (f"-{n}", f"negative {word}"),
                (f"{n}.05", f"{word} point zero five"),
                (f"{n}%", f"{word} percent"),
            ]
        )
        for written, spoken in [
            ("+", "plus"),
            ("-", "minus"),
            ("=", "equals"),
            ("/", "over"),
            ("<=", "is less than or equal to"),
            ("!=", "is not equal to"),
        ]:
            cases.append((f"{n}{written}2", f"{word} {spoken} two"))
    for variable in "abcdefghijklmnopqrstuvwxyz":
        for power, reading in [("2", "squared"), ("3", "cubed"), ("n", "to the power n")]:
            cases.append((f"{variable}^{power}", f"{variable} {reading}"))
        cases.extend(
            [
                (rf"\frac{{{variable}}}{{b}}", f"{variable} over b"),
                (rf"\sqrt{{{variable}+1}}", f"the square root of {variable} plus one, end root"),
                (f"{variable}_i", f"{variable} sub i"),
            ]
        )
    for n, word in enumerate(WORDS[1:], 1):
        for denominator, reading in [("7", "seven"), ("11", "eleven"), ("13", "thirteen"), ("17", "seventeen")]:
            cases.append((rf"\frac{{{n}}}{{{denominator}}}", f"{word} over {reading}"))
    return cases


@pytest.mark.parametrize(("written", "spoken"), golden_cases())
def voc08_verbaliser_golden(written, spoken):
    assert verbalise(written).text == spoken


def test_golden_set_has_at_least_500_distinct_expressions():
    assert len({written for written, _ in golden_cases()}) >= 500


@pytest.mark.parametrize(
    "expression",
    [
        r"\unknown{secret}",
        r"\frac{1}",
        r"\frac{}{2}",
        r"\sqrt{}",
        r"\sqrt[3]{x}",
        r"\begin{matrix}1&2\end{matrix}",
        r"\input{private}",
        r"x^{",
        "x^",
        "^2",
        "(x+1",
        "x+1)",
        r"\frac{a}{b}}",
        "<script>private</script>",
        "x & y",
        "1234567890123456",
        "x\x00y",
        "x`2",
        "2**3",
        "2**3**4",
        r"\text{m s}^{-4}",
    ],
)
def test_unsupported_maths_is_replaced_whole(expression):
    result = verbalise(expression)
    assert result.text == FALLBACK
    assert result.fallbacks
    assert "private" not in repr(result) and "secret" not in repr(result)


def test_fallback_preserves_surrounding_prose_and_never_partial_maths():
    result = verbalise(r"First $\unknown{x}+7$ then $x^2$.")
    assert result == SpeechText(f"First {FALLBACK} then x squared.", ("unsupported_command",))


@pytest.mark.parametrize("expression", ["$x^2", r"\(x^2", r"\[x^2", "$$x^2"])
def test_unclosed_delimiter_is_not_spoken(expression):
    assert verbalise(expression) == SpeechText(FALLBACK, ("unclosed_math",))


def test_limits_are_reason_only_and_do_not_raise():
    assert verbalise("x" * (MAX_TEXT + 1)) == SpeechText(FALLBACK, ("text_limit",))
    assert verbalise("{" * 1000 + "x" + "}" * 1000) == SpeechText(FALLBACK, ("nesting_limit",))
    assert verbalise(r"\sqrt{" * 1000 + "x" + "}" * 1000).fallbacks == ("nesting_limit",)


def test_pointer_is_removed_before_speech():
    text = 'Look <point at="stp_01JZ0000000000000000000001"/> here.'
    assert verbalise(text) == SpeechText("Look here.")
    # D103: cue markers also name diagram parts and wrap write cues; every well-formed marker is removed unspoken.
    assert verbalise('Here <point at="vis_01JZ0000000000000000000002:left_ventricle"/> it is.').text == "Here it is."
    assert verbalise('<write at="2">Two x equals eight.</write>').text == "Two x equals eight."
    # Anything else shaped like markup is never read out: the passage is replaced whole (VOC-08).
    assert verbalise('<point href="x">').text == FALLBACK


@given(st.text(max_size=300))
@settings(max_examples=250, deadline=None, database=None)
def test_arbitrary_text_never_raises_or_emits_raw_markup(text):
    result = verbalise(text)
    assert not re.search(r"[\\$^_{}<>*`#]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", result.text)
    assert verbalise(text) == result


# The read-aloud lines the D95 samples exposed, and lines like them: none may speak "as" for 2as or "to" for a colon.
SAMPLE_LINES = [
    (r"Use $v^2 = u^2 + 2as$ with $u = 0$.", "Use v squared equals u squared plus two a s with u equals zero."),
    (
        "Every transaction touches at least two accounts: when cash comes in, something else goes up.",
        "Every transaction touches at least two accounts: when cash comes in, something else goes up.",
    ),
    ("Remember: the units stay with every step.", "Remember: the units stay with every step."),
    (r"Here is the plan: use $F = ma$ first.", "Here is the plan: use F equals m a first."),
    (r"Rearrange $2as = v^2 - u^2$: then divide.", "Rearrange two a s equals v squared minus u squared: then divide."),
    (
        "Share it in the ratio 3:2, then check: the parts add up.",
        "Share it in the ratio three to two, then check: the parts add up.",
    ),
]


@pytest.mark.parametrize(("written", "spoken"), SAMPLE_LINES)
def voc08_read_aloud_samples(written, spoken):
    text = verbalise(written).text
    assert text == spoken
    assert not re.search(r"\btwo as\b", text)
