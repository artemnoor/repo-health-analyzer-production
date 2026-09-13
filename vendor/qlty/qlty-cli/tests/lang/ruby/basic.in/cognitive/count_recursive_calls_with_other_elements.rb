def fibonacci(n)
  if [0, 1].include?(n)                      # +1
    n
  else                                       # +1
    fibonacci(n - 1) + fibonacci(n - 2)    # +2 (recursive calls)
  end
end
