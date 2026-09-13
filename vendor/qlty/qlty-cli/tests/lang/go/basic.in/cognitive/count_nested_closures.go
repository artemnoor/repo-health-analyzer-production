package main

import "fmt"

// This function `intSeq` returns another function, which
// we define anonymously in the body of `intSeq`. The
// returned function closes over the variable `i` to
// form a closure.

func intSeq() func() int {
	i := 0
	return func() int {
		if true {                     // +2 (nesting = 1)
			true
		}
		i += 1
		return i
	}
}
