def foo
  while true # +1
    while true # +2 (nesting=1)
      while true # +3 (nesting=2)
      end
    end
  end
end
