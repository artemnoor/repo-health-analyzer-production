# lcom = 0 for all the tests in this file, totalling 0

def foo
  self.bar
end

class Klass
  def foo
    nil
  end
end

class Klass
  def foo
    bar.baz
  end
end
