fn f0(numbers: &[i32]) -> (f64, Option<i32>) {
    let mean: f64 = numbers.iter().sum::<i32>() as f64 / numbers.len() as f64;

    let mut sorted_numbers = numbers.to_vec();
    sorted_numbers.sort();
    let median: Option<i32> = if sorted_numbers.len() % 2 == 0 {
        let mid_index = sorted_numbers.len() / 2;
        Some((sorted_numbers[mid_index - 1] + sorted_numbers[mid_index]) / 2)
    } else {
        Some(sorted_numbers[sorted_numbers.len() / 2])
    };

    (mean, median)
}

fn f1(numbers: &[i32]) -> (f64, Option<i32>) {
    let mean: f64 = numbers.iter().sum::<i32>() as f64 / numbers.len() as f64;

    let mut sorted_numbers = numbers.to_vec();
    sorted_numbers.sort();
    let median: Option<i32> = if sorted_numbers.len() % 2 == 0 {
        let mid_index = sorted_numbers.len() / 2;
        Some((sorted_numbers[mid_index - 1] + sorted_numbers[mid_index]) / 2)
    } else {
        Some(sorted_numbers[sorted_numbers.len() / 2])
    };

    (mean, median)
}
