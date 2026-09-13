package foo

import "fmt"

func foo() {
	Loop:
		for {                                 // +1 (increments nesting 1)
			select {                            // +2 (nesting = 1)
			case err = <-complete:
				break Loop                        // +1
			}
		}
}
