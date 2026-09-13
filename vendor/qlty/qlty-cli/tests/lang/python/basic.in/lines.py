def f1():
    source_file = Tempfile.new(["ruby", ".kt"])
    source_file.write("foo(*args)")
    tree = source_file.parse

    bar


# Foo
def f2():
    bar  # does not count as comment line


# TODO: We don't seem to have support for multi-line comment in python
"""

line1
line2

line4
"""


def f3():
    bar
