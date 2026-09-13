fun f1() {
    val sourceFile = File.createTempFile("ruby", ".kt")
    sourceFile.writeText("foo(*args)")
    val tree = sourceFile.parse()

    bar()
}

// Foo
fun f2() {
    bar() // does not count as comment line
}

// multi-line comment
/*
line1
line2

line4
*/
fun f3() {
    bar()
}
