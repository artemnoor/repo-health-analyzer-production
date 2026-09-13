def not_nested(foo, bar)
    if (foo == 'cat' and bar == 'dog') or (foo == 'dog' and bar == 'cat')
        puts 'Got a cat and a dog!'
    else
        puts 'Got nothing'
    end
end

def f0
    if bar
        if baz
            if qux
                if quux
                    puts 'Not deeply nested enough!'
                end
            end
        end
    end
end

def f1
    if bar
        if baz
            if qux
                if quux
                    puts 'Deeply nested!'
                end
            end
        end
    end
end

def f2(foo)
    case foo
    when 1
        'bar1'
    when 2
        'bar2'
    when 3
        'bar3'
    when 4
        'bar4'
    when 5
        'bar5'
    when 6
        'bar6'
    when 7
        'bar7'
    when 8
        'bar8'
    when 9
        'bar9'
    when 10
        'bar10'
    else
        raise ArgumentError, 'Invalid foo value'
    end
end
