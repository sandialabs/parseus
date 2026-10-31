"""
Runs transform preprocessor functions to make sure behaviour is constant/expected.
"""

from parseus.preprocessors.transform import one_to_many


def duplicate_transformer(doc):
    "Returns two copies of the document"
    return [doc, doc]


def empty_transformer(doc):
    "Returns no documents"
    return []


def modifying_transformer(doc, suffix):
    "Returns a transformed document with a suffix"
    return [f"{doc['name']}_{suffix}"]


def test_one_to_many_basic():
    "Tests one_to_many using the duplicating transformer"
    input_data = [{"name": "doc1"}, {"name": "doc2"}]
    result = list(one_to_many(input_data, duplicate_transformer))
    assert result == [
        {"name": "doc1"},
        {"name": "doc1"},
        {"name": "doc2"},
        {"name": "doc2"},
    ]


def test_one_to_many_empty_input():
    "Tests one_to_many using the duplicating transformer with empty input"
    input_data = []
    result = list(one_to_many(input_data, duplicate_transformer))
    assert result == []


def test_one_to_many_no_output():
    "Tests one_to_many using the empty transformer with actual input"
    input_data = [{"name": "doc1"}, {"name": "doc2"}]
    result = list(one_to_many(input_data, empty_transformer))
    assert result == []


def test_one_to_many_multiple_outputs():
    "Tests one_to_many using the modifying transformer with actual input"
    input_data = [{"name": "doc1"}, {"name": "doc2"}]
    result = list(one_to_many(input_data, modifying_transformer, suffix="v1"))
    assert result == ["doc1_v1", "doc2_v1"]


def test_one_to_many_with_kwargs():
    "Tests one_to_many using the modifying transformer with actual input using kwargs"
    input_data = [{"name": "doc1"}, {"name": "doc2"}]
    result = list(one_to_many(input_data, modifying_transformer, suffix="test"))
    assert result == ["doc1_test", "doc2_test"]
