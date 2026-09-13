package foo

import "fmt"

func foo() {
	if true {       // +1
		if true {     // +2 (nesting = 1)
			if true {   // +3 (nesting = 2)
				true
			}
		}
	}

	if true {    // +1
		true
	}
}
.go
