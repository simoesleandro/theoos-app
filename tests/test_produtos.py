"""Testes de matching de produtos (pós-OCR)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from theoos import produtos  # noqa: E402


def _catalog(*entries):
    return [
        {
            "nome": nome,
            "marca": marca,
            "unidade": unidade,
            "categoria": "Supermercado",
            "aliases": list(aliases or []),
        }
        for nome, unidade, marca, aliases in entries
    ]


def test_banana_prata_matches_despite_kg_suffix():
    catalog = _catalog(
        ("Banana Prata", "kg", None, ["BANANA PRATA", "BAN PRATA"]),
    )
    nome, matched = produtos.resolve_nome_normalizado(
        "BANANA PRATA KG",
        "Banana Prata",
        None,
        "kg",
        catalog,
    )
    assert nome == "Banana Prata"
    assert matched is not None


def test_azeite_extra_virgem_not_merged_with_simple():
    catalog = _catalog(
        ("Azeite Português", "l", None, []),
    )
    nome, matched = produtos.resolve_nome_normalizado(
        "AZEITE PORT EXTRA VIRGEM 500ML",
        "Azeite Português Extra Virgem",
        None,
        "ml",
        catalog,
    )
    assert nome == "Azeite Português Extra Virgem"
    assert matched is None


def test_exact_alias_match():
    catalog = _catalog(
        ("Leite Integral", "l", "Lider", ["LEITE UHT INT LIDER 1L"]),
    )
    nome, matched = produtos.resolve_nome_normalizado(
        "LEITE UHT INT LIDER 1L",
        "Leite Integral",
        "Lider",
        "l",
        catalog,
    )
    assert nome == "Leite Integral"
    assert matched is not None


def test_combined_similarity_substring_with_one_extra_unit():
    assert produtos.combined_similarity("banana prata", "banana prata kg") >= 0.9


def test_combined_similarity_different_products():
    score = produtos.combined_similarity(
        "azeite portugues",
        "azeite portugues extra virgem",
    )
    assert score < produtos.AUTO_MATCH_THRESHOLD


def test_parse_aliases_json_and_csv():
    assert produtos.parse_aliases('["BANANA PRATA", "BAN PRATA"]') == ["BANANA PRATA", "BAN PRATA"]
    assert produtos.parse_aliases("A, B, C") == ["A", "B", "C"]
    assert produtos.parse_aliases(None) == []


def test_dump_aliases_dedupes():
    assert produtos.dump_aliases(["A", "A", " B "]) == '["A", "B"]'
