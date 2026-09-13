package foo

import "fmt"

func foo() {
	select {           // +1
	case 1:
		true
	case 2:
		break           // +0
	case 3:
		false
	}
}
