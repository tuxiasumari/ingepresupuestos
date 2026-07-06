"""Tests básicos de la capa core (sin GUI)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.formatting import fmt, parse_num, pad_codigo


def test_fmt_soles():
    assert fmt(1234.5, 'Soles') == "S/ 1,234.50"

def test_fmt_euros():
    assert fmt(1234.5, 'Euros') == "€ 1.234,50"

def test_parse_num_punto():
    assert parse_num("21.36") == 21.36

def test_parse_num_coma():
    assert parse_num("21,36") == 21.36

def test_pad_codigo():
    assert pad_codigo("47") == "4700000"
    assert pad_codigo("4700023") == "4700023"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                print(f"  FAIL {name}: {e}")
