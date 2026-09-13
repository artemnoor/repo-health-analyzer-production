fun f0(foo: Int?): String? {
    return when (foo) {
        in 80..100 -> "Most complex!"
        in 60..79 -> "Very complex"
        in 40..59 -> "Somewhat complex"
        in 20..39 -> "Not complex"
        in 0..19 -> "Least complex!"
        else -> null
    }
}

// count_non_sequential_logical_operators_rust
fun f1(): Boolean {
    return true || false && true && false || true
}
