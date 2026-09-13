def how_complex(foo):
    if foo is None:  # +1 (for the if)
        return None
    elif 80 <= foo <= 100:  # +1 (for the elif)
        return "Most complex!"
    elif 60 <= foo <= 79:  # +1 (for the elif)
        return "Very complex"
    elif 40 <= foo <= 59:  # +1 (for the elif)
        return "Somewhat complex"
    elif 20 <= foo <= 39:  # +1 (for the elif)
        return "Not complex"
    elif 0 <= foo <= 19:  # +1 (for the elif)
        return "Least complex!"
