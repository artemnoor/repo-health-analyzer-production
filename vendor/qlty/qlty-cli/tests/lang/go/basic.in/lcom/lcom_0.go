// lcom = 0 for all the tests in this file, totalling 0

func foo() {
	bar()
}

type Klass1 struct{}

func (k *Klass1) Foo() interface{} {
	return nil
}

type Klass2 struct{}

func (k *Klass2) Foo() interface{} {
	return k.Bar().Baz()
}
