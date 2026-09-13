struct Foo {
    bar: i32,
    baz: i32,
}

fn do_something() {
    let foo = Foo { bar: 42, baz: 0 };
    println!("{} {}", foo.bar, foo.baz);
}
