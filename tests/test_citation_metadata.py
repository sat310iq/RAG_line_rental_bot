"""citation_metadata: 項境界と前文分割。"""

from src.citation_metadata import (
    chunk_paragraph_assignment,
    paragraph_boundaries_in_article_body,
    parse_article_seq_from_heading_line,
    split_preliminary_sections,
)


def test_paragraph_boundaries_granmare_style_article4() -> None:
    body = """## 第4条（賃料）

乙は、頭書(3)の記載に従い、賃料を甲に支払わなければならない。
2 １ヶ月に満たない期間の賃料は、当該月を実日数で日割り計算した額とする。
3 甲及び乙は、次の各号の一に該当する場合には、協議の上、賃料を改定することができる。
"""
    bounds = paragraph_boundaries_in_article_body(body)
    assert len(bounds) >= 3
    para_nums = [b[2] for b in bounds]
    assert para_nums == [1, 2, 3]


def test_chunk_maps_to_second_paragraph() -> None:
    body = """## 第4条（賃料）

乙は、頭書(3)の記載に従い、賃料を甲に支払わなければならない。
2 １ヶ月に満たない期間の賃料は、当該月を実日数で日割り計算した額とする。
"""
    bounds = paragraph_boundaries_in_article_body(body)
    chunk = "2 １ヶ月に満たない期間"
    pos = body.find(chunk)
    p, conf = chunk_paragraph_assignment(pos, pos + len(chunk), bounds)
    assert p == 2
    assert conf == "inferred"


def test_parse_article_seq_from_heading() -> None:
    assert parse_article_seq_from_heading_line("## 第17条（原状回復義務等）") == 17


def test_split_preliminary_has_multiple_blocks() -> None:
    pre = """# 【頭書（物件・契約条件）】

## （1）テスト

本文。

# 別表第1（参考）

別表本文。
"""
    blocks = split_preliminary_sections(pre)
    assert len(blocks) >= 2
    kinds = [b[2].get("cite_kind") for b in blocks]
    assert "head" in kinds or "appendix" in kinds
