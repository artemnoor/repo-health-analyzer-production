def foo
  case true # +1
  when true
    case true # +2 (nesting=1)
    when true
      case true # +3 (nesting=2)
      when true
      end
    end
  end
end
