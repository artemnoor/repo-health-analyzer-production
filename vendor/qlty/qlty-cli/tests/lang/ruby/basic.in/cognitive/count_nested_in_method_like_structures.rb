def foo
  Proc.new do
    if true # +2 (nesting=1)
    end
  end

  lambda do
    if true # +2 (nesting=1)
    end
  end

  [1,2,3].each do |number|
    if true # +2 (nesting=1)
    end
  end
end
