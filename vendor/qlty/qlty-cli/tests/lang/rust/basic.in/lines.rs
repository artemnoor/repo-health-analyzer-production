fn f1() {
    let source_file = File::from_string("ruby", "foo(*args)");
    let tree = source_file.parse();

    bar();
}

// Foo
fn f2() {
    bar(); // does not count as comment line
}

// multi-line comment
/*
line1
line2

line4
*/
fn f3() {
    bar();
}
