package foo

func foo() {
	if true {    // +1
		true
	}

	if true {    // +1
		true
	}
}
