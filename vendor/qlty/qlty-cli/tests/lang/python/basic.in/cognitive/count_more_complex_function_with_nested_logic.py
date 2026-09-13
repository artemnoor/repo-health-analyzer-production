def more_complex(foo, bar):
    if foo is None:  # +1 (for the if)
        return None
    elif 80 <= foo <= 100:  # +1 (for the elif)
        if (
            bar == "A"
        ):  # +2 (for the if nested inside an elif: +1 for the if and +1 for nesting)
            return "Most complex, Class A!"
        elif (
            bar == "B"
        ):  # +2 (for the elif nested inside an elif: +1 for the elif and +1 for nesting)
            return "Most complex, Class B!"
        else:  # +1 (for the else nested inside an elif, no increment for nesting since it's on the same level as the previous if/elif)
            return "Most complex, Unclassed!"
    elif 60 <= foo <= 79 and bar != "C":  # +1 (for the elif)
        return "Very complex"
    elif 40 <= foo <= 59 or bar == "D":  # +1 (for the elif)
        return "Somewhat complex"
    elif 20 <= foo <= 39:  # +1 (for the elif)
        if bar.startswith(
            "X"
        ):  # +2 (for the if nested inside an elif: +1 for the if and +1 for nesting)
            return "Not complex, Special X"
        else:
            return "Not complex"
    elif 0 <= foo <= 19:  # +1 (for the elif)
        return "Least complex!"
    else:
        raise ValueError(
            "Invalid input!"
        )  # +1 (for the else, after a series of if/elifs)
