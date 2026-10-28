from pharmadash import topics as T


def topic(headline, nums=(), sources=("n1", "n2", "n3"), conf="high"):
    return T.Topic(headline=headline, angle="a", why_now="w", dashboard_types=["bar"], risk_flags=[], confidence=conf,
                   sources=list(sources), key_numbers=[T.KeyNumber(text=n, source_url="n1") for n in nums],
                   scores=T.Scores(recency=5, financial_magnitude=5, relevance=5, dashboard_ability=5,
                                   freshness_vs_history=5, reader_interest=5))


def test_invented_numbers_are_dropped():
    t = topic("Novartis impairment", ["Impairment $1.9B", "Q3 net sales $14.5B in 2026"])
    T.check_numbers([t], "Novartis stands by $12B bet after $1.9B impairment hit")
    assert [k.text for k in t.key_numbers] == ["Impairment $1.9B"]
    assert t.confidence == "medium" and any("removed" in f for f in t.risk_flags)


def test_unknown_citation_ids_are_dropped():
    t = topic("X", ["1.9"], sources=("n1", "n99"))
    T.resolve_ids([t], {"n1": "http://a"})
    assert t.sources == ["http://a"] and t.key_numbers[0].source_url == "http://a"
    assert any("removed" in f for f in t.risk_flags)


def test_dedupe_and_selection():
    a, b = topic("Novartis lifts guidance after impairment hit"), topic("Novartis lifts guidance after $1.9B impairment")
    assert len(T.dedupe([a, b, topic("Lilly wins ad ruling")])) == 2
    assert T.parse_selection("top3", 10) == [1, 2, 3]
