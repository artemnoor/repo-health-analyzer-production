package main

import (
	"fmt"
)

type Foo struct {
	Bar  string
	Baz  string
	quux string
	Quuz string
}

func doSomething() string {
	foo := &Foo{}
	foo.Bar = "Hello"
	foo.Baz = "World"
	return foo.Bar + foo.Baz
}
