package foo

import "fmt"

func foo() {
		var c1, c2, c3 chan int
		var i1, i2 int
		select {                                                  // +1
			case i1 = <-c1:
					fmt.Printf("received ", i1, " from c1")
			case c2 <- i2:
					fmt.Printf("sent ", i2, " to c2")
			case i3, ok := (<-c3):
					if ok {                                            // +2 (nesting = 1)
						fmt.Printf("received ", i3, " from c3")
					} else {                                           // +1
						fmt.Printf("c3 is closed")
					}
			default:
					fmt.Printf("no communication")
		}
}
