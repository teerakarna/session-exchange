"""What one table entry is. Its own module so the tables and the harness can both import it.

Separate from `__init__.py` rather than declared there, because `__init__.py` imports every table
and every table needs this: declaring it alongside the imports works only while the imports come
second, which is an ordering nobody should have to know about. A file with one class in it and no
imports of its own cannot participate in a cycle at all.
"""

from __future__ import annotations

from typing import NamedTuple


class Mutation(NamedTuple):
    """One rule, broken one way, and the test file that has to object.

    `caught_by` is pinned to a file rather than an individual check name: a file is stable enough to
    be worth asserting, while pinning the check name would turn every rename of a check into a red
    build. Membership only, so a mutation caught by its named file *and* two others still passes -
    which is the honest description, since nothing prints the extra names on a pass.
    """

    module: str
    rule: str
    old: str
    new: str
    caught_by: str
