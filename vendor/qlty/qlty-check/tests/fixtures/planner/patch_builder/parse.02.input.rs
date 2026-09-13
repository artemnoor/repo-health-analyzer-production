pub enum MyEnum {
    A,
    B,
}

impl Default for MyEnum {
    fn default() -> Self {
        MyEnum::A
    }
}
