def logical_sequences
  true
  foo0 && foo1 &&     # +1
  foo2 || foo3 ||     # +1
  foo4 and foo9       # +1
  foo4 || foo9        # +1
  foo6 && foo7        # +1
  foo6 || foo7        # +1
  foo6 || foo7
  foo6 || foo7
  foo6 || foo7
  foo6 || foo7
  foo6 || foo7
  foo6 || foo7
  foo7 && foo8        # +1
end
