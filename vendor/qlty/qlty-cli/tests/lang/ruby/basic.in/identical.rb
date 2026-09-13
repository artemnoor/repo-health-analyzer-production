def f0(numbers)
    mean = numbers.sum.to_f / numbers.size

    sorted_numbers = numbers.sort
    median = if sorted_numbers.size % 2 == 0
        mid_index = sorted_numbers.size / 2
        (sorted_numbers[mid_index - 1] + sorted_numbers[mid_index]) / 2
    else
        sorted_numbers[sorted_numbers.size / 2]
    end

    [mean, median]
end

def f1(numbers)
    mean = numbers.sum.to_f / numbers.size

    sorted_numbers = numbers.sort
    median = if sorted_numbers.size % 2 == 0
        mid_index = sorted_numbers.size / 2
        (sorted_numbers[mid_index - 1] + sorted_numbers[mid_index]) / 2
    else
        sorted_numbers[sorted_numbers.size / 2]
    end

    [mean, median]
end
