"""Acceptance script for the sort_items task (see RESEARCH.md)."""

from task import sort_items

assert sort_items([3, 1, 2]) == [1, 2, 3]
assert sort_items([]) == []
assert sort_items([5, 5, 1]) == [1, 5, 5]
original = [3, 1, 2]
sort_items(original)
assert original == [3, 1, 2], "input must not be mutated"

print("all sort_items assertions passed")
