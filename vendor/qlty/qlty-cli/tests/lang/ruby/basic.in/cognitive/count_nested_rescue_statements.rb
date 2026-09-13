def foo
  begin
  rescue Exception => ex # +1
    begin
    rescue Exception => ex # +2 (nesting=1)
      begin
      rescue Exception => ex # +3 (nesting=2)
      end
    end
  end
end
