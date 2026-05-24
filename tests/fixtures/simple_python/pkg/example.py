def score(value):
    if value > 10:
        for item in range(value):
            if item % 2 == 0:
                return item
    return 0
