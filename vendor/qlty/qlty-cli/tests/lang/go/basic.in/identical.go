func f0(numbers []float64) (float64, float64) {
	sum := 0.0
	for _, num := range numbers {
		sum += num
	}
	mean := sum / float64(len(numbers))

	sortedNumbers := make([]float64, len(numbers))
	copy(sortedNumbers, numbers)
	sort.Float64s(sortedNumbers)

	var median float64
	midIndex := len(sortedNumbers) / 2
	if len(sortedNumbers)%2 == 0 {
		median = (sortedNumbers[midIndex-1] + sortedNumbers[midIndex]) / 2
	} else {
		median = sortedNumbers[midIndex]
	}

	return mean, median
}

func f1(numbers []float64) (float64, float64) {
	sum := 0.0
	for _, num := range numbers {
		sum += num
	}
	mean := sum / float64(len(numbers))

	sortedNumbers := make([]float64, len(numbers))
	copy(sortedNumbers, numbers)
	sort.Float64s(sortedNumbers)

	var median float64
	midIndex := len(sortedNumbers) / 2
	if len(sortedNumbers)%2 == 0 {
		median = (sortedNumbers[midIndex-1] + sortedNumbers[midIndex]) / 2
	} else {
		median = sortedNumbers[midIndex]
	}

	return mean, median
}
