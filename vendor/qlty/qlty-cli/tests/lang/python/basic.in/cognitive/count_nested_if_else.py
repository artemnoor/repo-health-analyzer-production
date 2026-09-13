def how_complex(foo)
  if foo.nil?                # +1
    if foo == 1            # +2 (nested inside 1 level)
      return nil
    else                   # No additional score here. The structures after an else are considered independent, not nested.
      if foo == 2        # +1 (because it's independent after an else, not nested)
        return "foo is 2"
      else               # No additional score here either
        return "foo is not 2"
      end
    end
  end
end
