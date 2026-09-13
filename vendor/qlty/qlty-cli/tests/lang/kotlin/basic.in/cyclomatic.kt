fun f1() {}

fun f2(foo: Boolean) {
    if (foo) {}
}

fun f3(foo: Boolean, bar: Boolean) {
    if (foo && bar) {}
}

fun f4() {
    while (true) {}
}

fun f5(x: Boolean) {
    val y: Int

    if (x) {
        y = 1
    } else {
        y = 2
    }
}

fun f6(x: Boolean, z: Boolean) {
    val y: Int

    if (x) {
        y = 1
    } else if (z) {
        y = 2
    }
}

fun f7(x: Boolean, z: Boolean) {
    val y: Int
    if (x) {
        y = 1
    } else if (z) {
        y = 2
    } else {
        y = 3
    }
}

fun f8() {
    val animals = arrayOf("dog", "cat", "bear")
    for (animal in animals) {
        println(animal)
    }
}

fun f9() {
    val animals = listOf("dog", "cat", "bear")
    animals.map(fun(animal: String): String {
        println(animal)
        return animal
    })
}

fun f10() {
    val animals = listOf("dog", "cat", "bear", "tiger")

    val filteredAnimals = animals.filter { it.length > 3 }
    for (animal in filteredAnimals) {
        println(animal)
    }

    if ("cat" in animals) {
        println("Found a cat!")
    }
}
