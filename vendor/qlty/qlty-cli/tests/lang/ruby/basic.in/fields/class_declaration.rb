class Foo
  attr_accessor :bar, :baz
  attr_writer :quux
  attr_reader :quuz
end

def do_something
  foo = Foo.new
  foo.bar = "Hello"
  foo.baz = "World"
  return foo.bar + foo.baz
end
