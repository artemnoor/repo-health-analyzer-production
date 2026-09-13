class Foo(val bar: Int, val baz: RandomClass) {
    fun bee() {
        baz.foo
           .bar(this) // 1
           .blink()
    }
}

// This is apparently valid syntax according to
// https://github.com/JetBrains/kotlin/blob/master/analysis/analysis-api/testData/components/expressionInfoProvider/isUsedAsExpression/labelledThis.kt
// Although this shows errors in tree sitter kotlin playground
class C {
    fun String.test(): Int {
        return <expr>this@C</expr>.hashCode()
    }
}
