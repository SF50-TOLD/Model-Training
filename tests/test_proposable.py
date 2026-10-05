import argparse

import pytest

from conversion.proposable import proposable_fields


def test_lists_fields_in_schema_order_without_duplicates():
    assert proposable_fields("rwyCC, partialClosure,rwyCC") == ["partialClosure", "rwyCC"]


def test_an_empty_list_proposes_nothing():
    assert proposable_fields("") == []


def test_refuses_a_field_that_is_never_proposed():
    with pytest.raises(argparse.ArgumentTypeError, match="obstacleDistance"):
        proposable_fields("partialClosure,obstacleDistance")
