package main

import "fmt"

func fib(n uint) uint {
		if n == 0 {                // +1
			return 0
		} else if n == 1 {         // +1
		return 1
	} else {                     // +1
		return fib(n-1) + fib(n-2) // +2 (recursion)
	}
}

func main() {
	n := uint(10)
	fmt.Println(fib(n))
}
