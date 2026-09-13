def foo
  File.open('some_file.txt', 'r') do |file|
    puts file.read
  end
end
