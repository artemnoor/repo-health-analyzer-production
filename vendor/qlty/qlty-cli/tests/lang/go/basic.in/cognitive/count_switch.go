package foo

import "fmt"

func foo() {
		i := 2
		fmt.Print("Write ", i, " as ")
		switch i {                            // +1
		case 1:
				fmt.Printf("foo")
		case 2:
				fmt.Println("two")
		case 3:
				fmt.Println("three")
		}
}
