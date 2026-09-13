fn f1() {}

fn f2() {
    if foo {}
}

fn f3() {
    if foo && bar {}
}

fn f4() {
    while true {}
}

fn f5() {
    let y;

    if x {
        y = 1;
    } else {
        y = 2;
    }
}

fn f6() {
    let y;

    if x {
        y = 1;
    } else if z {
        y = 2;
    }
}

fn f7() {
    let y;
    if x {
        y = 1;
    } else if z {
        y = 2;
    } else {
        y = 3;
    }
}

fn f8() {
    for animal in &["dog", "cat", "bear"] {
        println!("{}", animal);
    }
}

fn f9() {
    let animals = vec!["dog", "cat", "bear"];
    let _ = animals
        .iter()
        .map(|animal| {
            println!("{}", animal);
            animal
        })
        .collect::<Vec<_>>();
}

fn f10() {
    let animals = vec!["dog", "cat", "bear", "tiger"];

    let filtered_animals: Vec<_> = animals.iter().filter(|&&animal| animal.len() > 3).collect();
    for animal in &filtered_animals {
        println!("{}", animal);
    }

    if animals.contains(&"cat") {
        println!("Found a cat!");
    }
}
