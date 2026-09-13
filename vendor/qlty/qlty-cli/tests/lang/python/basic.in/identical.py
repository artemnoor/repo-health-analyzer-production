def f0(numbers):
    mean = sum(numbers) / len(numbers)

    sorted_numbers = sorted(numbers)
    if len(sorted_numbers) % 2 == 0:
        mid_index = len(sorted_numbers) // 2
        median = (sorted_numbers[mid_index - 1] + sorted_numbers[mid_index]) / 2
    else:
        median = sorted_numbers[len(sorted_numbers) // 2]

    return mean, median

def f1(numbers):
    mean = sum(numbers) / len(numbers)

    sorted_numbers = sorted(numbers)
    if len(sorted_numbers) % 2 == 0:
        mid_index = len(sorted_numbers) // 2
        median = (sorted_numbers[mid_index - 1] + sorted_numbers[mid_index]) / 2
    else:
        median = sorted_numbers[len(sorted_numbers) // 2]

    return mean, median
