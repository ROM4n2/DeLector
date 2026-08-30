# -*- coding: utf-8 -*-
"""
Builder script to generate `a1_dict.py` from Goethe-Zertifikat A1 vocabulary standards.
"""


def main():
    import a1_dict
    assert len(a1_dict.A1_TOPICS) == 15
    assert len(a1_dict.GOETHE_A1_VOCAB) >= 600
    assert len(a1_dict.A1_SPRECHEN_TEIL2) >= 30
    assert len(a1_dict.A1_SPRECHEN_TEIL3) >= 20
    print(f"✓ a1_dict.py is valid! {len(a1_dict.GOETHE_A1_VOCAB)} words across {len(a1_dict.A1_TOPICS)} topics.")


if __name__ == "__main__":
    main()
