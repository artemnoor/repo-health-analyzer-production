class Shark:
    def __init__(self, name, age):
        self.name = name
        self.age = age
        self.name = name
        self.age = age

    def foo(self, name, age):
        self.name = name
        self.age = age


new_shark = Shark("Sammy", 5)
print(new_shark.name)
print(new_shark.age)
print(new_shark.name)
print(new_shark.age)

stevie = Shark("Stevie", 8)
print(stevie.name)
print(stevie.age)
print(stevie.name)
print(stevie.age)
