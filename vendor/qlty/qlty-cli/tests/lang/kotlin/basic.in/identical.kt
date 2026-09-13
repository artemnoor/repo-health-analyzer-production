fun f0(numbers: IntArray): Pair<Double, Int?> {
    val mean: Double = numbers.sum().toDouble() / numbers.size.toDouble()

    val sortedNumbers = numbers.sorted()
    val median: Int? = if (sortedNumbers.size % 2 == 0) {
        val midIndex = sortedNumbers.size / 2
        (sortedNumbers[midIndex - 1] + sortedNumbers[midIndex]) / 2
    } else {
        sortedNumbers[sortedNumbers.size / 2]
    }

    return Pair(mean, median)
}

fun f1(numbers: IntArray): Pair<Double, Int?> {
    val mean: Double = numbers.sum().toDouble() / numbers.size.toDouble()

    val sortedNumbers = numbers.sorted()
    val median: Int? = if (sortedNumbers.size % 2 == 0) {
        val midIndex = sortedNumbers.size / 2
        (sortedNumbers[midIndex - 1] + sortedNumbers[midIndex]) / 2
    } else {
        sortedNumbers[sortedNumbers.size / 2]
    }

    return Pair(mean, median)
}
