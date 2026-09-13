def foo():
    animals = ["dog", "cat", "bear", "tiger"]

    filtered_animals = filter(lambda animal: len(animal) > 3, animals)
    for animal in filtered_animals:
        print(animal)

    if "cat" in animals:
        print("Found a cat!")
