func notNested(foo, bar string) {
	if (foo == "cat" && bar == "dog") || (foo == "dog" && bar == "cat") {
		fmt.Println("Got a cat and a dog!")
	} else {
		fmt.Println("Got nothing")
	}
}

func f0(bar, baz, qux, quux bool) {
	if bar {
		if baz {
			if qux {
				if quux {
					fmt.Println("Not deeply nested enough!")
				}
			}
		}
	}
}

func f1(bar, baz, qux, quux bool) {
	if bar {
		if baz {
			if qux {
				if quux {
					fmt.Println("Deeply nested!")
				}
			}
		}
	}
}

func f2(foo int) (string, error) {
	switch foo {
	case 1:
		return "bar1", nil
	case 2:
		return "bar2", nil
	case 3:
		return "bar3", nil
	case 4:
		return "bar4", nil
	case 5:
		return "bar5", nil
	case 6:
		return "bar6", nil
	case 7:
		return "bar7", nil
	case 8:
		return "bar8", nil
	case 9:
		return "bar9", nil
	case 10:
		return "bar10", nil
	default:
		return "", errors.New("invalid foo value")
	}
}
