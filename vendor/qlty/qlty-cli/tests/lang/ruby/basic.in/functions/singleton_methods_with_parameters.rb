class Foo
  def self.bar(dog, cat)
    [dog, cat].map { |animal| animal.to_s }
  end
end
