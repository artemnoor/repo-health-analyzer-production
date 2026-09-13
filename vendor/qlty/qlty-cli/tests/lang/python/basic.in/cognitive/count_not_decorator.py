def not_decorator(a, b):
    x = 1 + 1

    def wrapper(f):
        if foo:
            print(a)
        f()

    return wrapper
