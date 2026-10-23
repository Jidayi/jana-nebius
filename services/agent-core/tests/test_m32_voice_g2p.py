"""Words outside Kokoro's lexicon are spelled out, never dropped (D95: no espeak fallback; D103 tutor names)."""

from types import SimpleNamespace

import numpy as np
from agent_core.net.voice_g2p import GRAPHEMES, NAMES, PHONEMES, Fallback, SpellingModel, to_misaki


def test_arpabet_maps_to_misaki_with_stress_before_the_vowel():
    assert to_misaki(["JH", "AA1", "N", "AH0"]) == "ʤˈɑnə"
    assert to_misaki(["S", "T", "OW2", "K", "ER0"]) == "stˌOkəɹ"
    assert to_misaki(["HH", "EY1"]) == "hˈA"


def test_tutor_names_have_fixed_pronunciations_even_without_the_model():
    fallback = Fallback(None)
    assert fallback(SimpleNamespace(text="Jana")) == (NAMES["jana"], 4)

    assert fallback(SimpleNamespace(text="Chukwuemeka")) == (None, None)  # no weights: misaki keeps its own rule


def test_spelling_model_decodes_greedily_until_the_end_symbol(tmp_path):
    rng = np.random.default_rng(0)
    hidden, emb = 8, 4
    shapes = {
        "enc_emb": (len(GRAPHEMES), emb), "enc_w_ih": (3 * hidden, emb), "enc_w_hh": (3 * hidden, hidden),
        "enc_b_ih": (3 * hidden,), "enc_b_hh": (3 * hidden,), "dec_emb": (len(PHONEMES), emb),
        "dec_w_ih": (3 * hidden, emb), "dec_w_hh": (3 * hidden, hidden), "dec_b_ih": (3 * hidden,),
        "dec_b_hh": (3 * hidden,), "fc_w": (len(PHONEMES), hidden), "fc_b": (len(PHONEMES),),
    }  # fmt: skip
    weights = {name: rng.standard_normal(shape).astype(np.float32) for name, shape in shapes.items()}
    weights["fc_b"][3] = 50.0  # </s> wins at once
    np.savez(tmp_path / "w.npz", **weights)
    assert SpellingModel(tmp_path / "w.npz").arpabet("jana") == []
    weights["fc_b"][3], weights["fc_b"][PHONEMES.index("K")] = 0.0, 50.0
    np.savez(tmp_path / "w.npz", **weights)
    assert SpellingModel(tmp_path / "w.npz").arpabet("kite") == ["K"] * 20  # bounded at 20 symbols
    assert Fallback(tmp_path / "w.npz")(SimpleNamespace(text="Zed")) == ("k" * 20, 1)
    assert Fallback(tmp_path / "w.npz")(SimpleNamespace(text="x" * 40)) == (None, None)
