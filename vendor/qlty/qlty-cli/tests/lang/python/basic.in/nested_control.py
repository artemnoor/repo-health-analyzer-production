def not_nested(foo, bar):
    if (foo == "cat" and bar == "dog") or (foo == "dog" and bar == "cat"):
        print("Got a cat and a dog!")
    else:
        print("Got nothing")


def f0():
    if bar:
        if baz:
            if qux:
                if quux:
                    print("Not deeply nested enough!")


def f1():
    if bar:
        if baz:
            if qux:
                if quux:
                    print("Deeply nested!")


def f2(foo):
    if foo == 1:
        return "bar1"
    elif foo == 2:
        return "bar2"
    elif foo == 3:
        return "bar3"
    elif foo == 4:
        return "bar4"
    elif foo == 5:
        return "bar5"
    elif foo == 6:
        return "bar6"
    elif foo == 7:
        return "bar7"
    elif foo == 8:
        return "bar8"
    elif foo == 9:
        return "bar9"
    elif foo == 10:
        return "bar10"
    else:
        raise ValueError("Invalid foo value")
