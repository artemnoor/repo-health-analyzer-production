fn foo(x: i32) -> i32 {
    if x > 30 {
        x * 3
    } else if x > 20 {
        x * 2
    } else if x > 10 {
        x * 1
    } else if x > 5 {
        x + 1
    } else {
        x - 1
    }
}

fn bar(x: i32) -> i32 {
    if x > 30 {
        x * 3
    } else if x > 20 {
        x * 2
    } else if x > 10 {
        x * 1
    } else if x > 5 {
        x + 1
    } else {
        x - 1
    }
}
