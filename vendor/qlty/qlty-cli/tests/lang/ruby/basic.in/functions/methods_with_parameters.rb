class Foo
  def initialize(dog, cat)
    @dog = "Ruff"
    @cat = "Meow"
  end

  def bar(dog, cat)
    [dog, cat].map { |animal| animal.to_s }
  end
end
