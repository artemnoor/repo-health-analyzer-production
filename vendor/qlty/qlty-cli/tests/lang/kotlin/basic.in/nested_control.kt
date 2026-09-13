fun notNested(foo: String, bar: String) {
    if ((foo == "cat" && bar == "dog") || (foo == "dog" && bar == "cat")) {
        println("Got a cat and a dog!")
    } else {
        println("Got nothing")
    }
}

fun f0() {
    if (bar) {
        if (baz) {
            if (qux) {
                if (quux) {
                    println("Not deeply nested enough!")
                }
            }
        }
    }
}

fun f1() {
    if (bar) {
        if (baz) {
            if (qux) {
                if (quux) {
                    println("Deeply nested!")
                }
            }
        }
    }
}

fun f2(foo: Int) {
    // match should never trigger this rule
    val result = when (foo) {
        1 -> "bar1"
        2 -> "bar2"
        3 -> "bar3"
        4 -> "bar4"
        5 -> "bar5"
        6 -> "bar6"
        7 -> "bar7"
        8 -> "bar8"
        9 -> "bar9"
        10 -> "bar10"
        else -> throw IllegalArgumentException("Invalid foo value")
    }
}
