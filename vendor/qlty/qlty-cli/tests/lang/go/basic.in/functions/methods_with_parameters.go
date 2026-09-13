type Foo struct {
	dog string
	cat string
}

func NewFoo(dog, cat string) *Foo {
	return &Foo{
		dog: "Ruff",
		cat: "Meow",
	}
}

func (f *Foo) Bar(dog, cat interface{}) []string {
	return []string{toString(dog), toString(cat)}
}
