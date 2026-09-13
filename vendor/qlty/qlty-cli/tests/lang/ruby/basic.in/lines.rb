def f1
    source_file = Tempfile.new(["ruby", ".kt"])
    source_file.write("foo(*args)")
    tree = source_file.parse

    bar
end

# Foo
def f2
    bar # does not count as comment line
end

# multi-line comment
=begin

line1
line2

line4
=end

def f3
    bar
end
