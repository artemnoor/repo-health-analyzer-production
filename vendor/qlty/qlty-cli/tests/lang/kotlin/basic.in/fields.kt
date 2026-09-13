data class Foo(val bar: Int, val baz: Int)

fun doSomething() {
    val foo = Foo(bar = 42, baz = 0)
    println("${foo.bar} ${foo.baz}")
}
