def foo():
    global bar, foo
    if not bar:
        bar = 10
    if foo:
        foo = 10
