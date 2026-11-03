from groundwork.grounding import check_grounding, factual_numbers, quote_in_source
from groundwork.models import Claim, Draft


def draft(parts, claims):
    return Draft(platform="x", format="thread", hook="How keys find servers.", parts=parts,
                 claims=claims)


def checks(findings):
    return {f.check for f in findings}


def test_verbatim_quote_passes(store):
    c = Claim(statement="Adding a server only moves nearby keys", source_id="S1",
              quote="When a server is added, only the keys between it and its predecessor have to move.")
    assert check_grounding(draft(["Only nearby keys move."], [c]), store) == []


def test_paraphrased_quote_fails(store):
    c = Claim(statement="Adding a server moves few keys", source_id="S1",
              quote="Adding servers barely moves any keys at all in the ring design.")
    assert "grounding.quote_not_found" in checks(check_grounding(draft(["x"], [c]), store))


def test_curly_quotes_and_whitespace_are_tolerated(store):
    assert quote_in_source("the  key’s position", store.get("S1").text)


def test_elided_quote(store):
    text = store.get("S1").text
    assert quote_in_source("Consistent hashing maps both keys ... from the key's position", text)
    assert not quote_in_source("Consistent hashing maps both keys ... invented on the moon", text)


def test_unknown_source_and_no_claims(store):
    assert "grounding.no_claims" in checks(check_grounding(draft(["x"], []), store))
    c = Claim(statement="s", source_id="S9", quote="When a server is added, only the keys")
    assert "grounding.unknown_source" in checks(check_grounding(draft(["x"], [c]), store))


def test_unbacked_number_is_flagged(store):
    c = Claim(statement="mod N remaps most keys", source_id="S2",
              quote="Adding a fifth server to a four-server pool remaps roughly 80% of keys")
    ok = draft(["Going from 4 to 5 servers remaps roughly 80% of keys."], [c])
    assert check_grounding(ok, store) == []
    bad = draft(["Going from 4 to 5 servers remaps roughly 95% of keys."], [c])
    assert "grounding.unbacked_number" in checks(check_grounding(bad, store))


def test_thread_counters_and_small_counts_are_not_facts():
    assert factual_numbers("1/7 Here are 3 ideas") == set()
    assert factual_numbers("latency fell 40% to 120ms in 2024") == {"40", "120", "2024"}
