def how_complex(foo)
  if foo.nil?                # +1 (for the if)
    return nil
  elsif foo >= 80            # +1 (for the elsif)
    return "Most complex!"
  elsif foo >= 60            # +1 (for the elsif)
    return "Very complex"
  end
end
