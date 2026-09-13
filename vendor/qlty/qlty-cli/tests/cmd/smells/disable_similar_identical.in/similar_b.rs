fn foo(y: i32) -> i32 {
    if y > 30 {
        y * 3
    } else if y > 20 {
        y * 2
    } else if y > 10 {
        y * 1
    } else if y > 5 {
        y + 1
    } else {
        y - 1
    }
}

fn bar(y: i32) -> i32 {
    if y > 30 {
        y * 3
    } else if y > 20 {
        y * 2
    } else if y > 10 {
        y * 1
    } else if y > 5 {
        y + 1
    } else {
        y - 1
    }
}
