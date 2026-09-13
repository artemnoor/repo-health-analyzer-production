def generator():
    def decorator(a, b):
        def wrapper(f):
            if foo:
                print(a)
            f()

        return wrapper

    return decorator
