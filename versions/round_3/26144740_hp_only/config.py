inv_skew_factors = [0.5, 0.75, 1, 1.25, 1.5]

# Make sure a `CONFIG` variable is defined, otherwise it will be empty.
CONFIG = [
    {
        "inv_skew_factor": isf,
    }
    for isf in inv_skew_factors
]
