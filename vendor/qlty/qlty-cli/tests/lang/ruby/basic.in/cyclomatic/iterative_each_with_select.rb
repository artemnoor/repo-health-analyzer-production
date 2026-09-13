def foo
  ["dog", "cat", "bear", "fish", "bird"].each do |animal|
    selected_animals = ["dog", "cat", "bear"].select do |selection|
      animal == selection
    end

    selected_animals.each do |selected|
      puts selected
    end
  end
end
