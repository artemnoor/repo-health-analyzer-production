def foo
  ["dog", "cat", "bear"].map do |animal|
    puts animal
    animal
  end
end
