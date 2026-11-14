from diffeoforge.convergence_advice import Observation, observations, summarize


def test_rounded_equal_values_do_not_establish_plateau():
    rows = tuple(Observation(i, -100.0, 0.05) for i in range(51))
    text = summarize(rows)
    assert "plateau is not established" in text
    assert "Last 50 iterations" in text
    assert "rounding ±0.1" in text


def test_advice_uses_maximizing_native_objective_and_declared_denominator():
    text = summarize(tuple(Observation(i, -100.0 + i, 0.0001) for i in range(51)))
    assert "still improving" in text
    assert "50% of |starting objective|" in text
    assert "Consider +300" in text


def test_sparse_reset_and_nonmonotone_histories_are_not_pooled():
    assert "Too few" in summarize((Observation(0, -100, 0.1), Observation(500, -90, 0.1)))
    text = "\n".join(
        f"--- Iteration: {i} ---\nLog-likelihood = {x} attachment = -1 regularity = -2"
        for i, x in [(0, "-1.000E+02"), (10, "-9.000E+01"), (0, "-8.000E+01")]
    )
    rows = observations(text)
    assert len(rows) == 1 and rows[0].iteration == 0
    assert rows[0].rounding == 0.005
    values = [Observation(i, -100 + i, 0.001) for i in range(51)]
    values[48] = Observation(48, -80, 0.001)
    assert "decreased" in summarize(tuple(values))


def test_recent_slowing_is_an_explicit_heuristic_not_convergence():
    rows = tuple(
        Observation(i, -100 + min(i, 40) + max(0, i - 40) * 0.05, 0.0001) for i in range(51)
    )
    text = summarize(rows)
    assert "flattening" in text and "quarter-rate cutoff is a heuristic" in text
    assert "11 observations" in text and "51 observations" in text
    assert "+300 is optional" in text
    assert "does not establish native convergence" in text
    # Coarse output precision cannot establish the apparent rate reduction.
    coarse = tuple(Observation(r.iteration, r.objective, 5.0) for r in rows)
    assert "flattening" not in summarize(coarse)
