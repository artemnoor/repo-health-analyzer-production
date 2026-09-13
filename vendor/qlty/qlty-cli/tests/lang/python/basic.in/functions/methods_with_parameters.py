class Foo:
    def __init__(self, dog, cat):
        self.dog = "Ruff"
        self.cat = "Meow"

    def bar(self, dog, cat):
        return [str(animal) for animal in [dog, cat]]
