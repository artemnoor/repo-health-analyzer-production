package foo

import "fmt"

func foo(a int) {
	for true  {     // +1
		fmt.Printf("This loop will run forever.")
	}
}
