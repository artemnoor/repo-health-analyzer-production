fn simple() {}

fn complex() {
    if let Some(bar) = Some(42) {
        if bar > 10 {
            if bar < 20 {
                if bar % 2 == 0 {
                    if bar % 3 == 0 {
                        println!("Nested!");
                    }
                }
            }
        }
    }
}
