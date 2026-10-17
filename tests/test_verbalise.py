from those_who_run.verbalise import delta_words, lap_time_words, laps_words, number_words


def test_number_words():
    assert number_words(0) == "zero"
    assert number_words(7) == "seven"
    assert number_words(13) == "thirteen"
    assert number_words(20) == "twenty"
    assert number_words(42) == "forty-two"
    assert number_words(100) == "one hundred"
    assert number_words(115) == "one hundred and fifteen"


def test_lap_time_words():
    assert lap_time_words(102300) == "one forty-two point three"
    assert lap_time_words(67200) == "one oh seven point two"
    assert lap_time_words(42300) == "forty-two point three"
    assert lap_time_words(100000) == "one forty point zero"
    assert lap_time_words(0) == "no time"


def test_lap_time_rounds_to_tenths():
    assert lap_time_words(102349) == "one forty-two point three"
    assert lap_time_words(102350) == "one forty-two point four"
    assert lap_time_words(119960) == "two oh zero point zero"


def test_delta_words():
    assert delta_words(-412) == "zero point four"
    assert delta_words(1500) == "one point five"
    assert delta_words(61000) == "over a minute"


def test_laps_words():
    assert laps_words(1) == "one lap"
    assert laps_words(3) == "three laps"


def test_percent_words_rounds_half_up():
    from those_who_run.verbalise import percent_words

    assert percent_words(37.5) == "thirty-eight percent"
    assert percent_words(0.4) == "zero percent"


def test_track_words_spells_out_what_the_voice_would_mangle():
    from those_who_run.verbalise import track_words

    assert track_words("Nurburgring 24h") == "Nurburgring twenty-four hour"
    assert track_words("Nurburgring GP") == "Nurburgring G P"
    assert track_words("Alsace - Village Reverse") == "Alsace. Village Reverse"
    assert track_words("Willow Springs International Raceway: Big Willow") == (
        "Willow Springs International Raceway. Big Willow"
    )
    assert (
        track_words("Kyoto Driving Park - Yamagiwa+Miyabi")
        == "Kyoto Driving Park. Yamagiwa and Miyabi"
    )
    assert track_words("24 Heures du Mans Racing Circuit No Chicane") == "Le Mans No Chicane"
    assert track_words("Fuji International Speedway (Short)") == "Fuji International Speedway Short"


def test_tidy_sentence():
    from those_who_run.verbalise import tidy_sentence

    assert tidy_sentence("Lap one.  one forty.  ") == "Lap one. one forty."
    assert tidy_sentence("Final lap") == "Final lap."


def test_tidy_sentence_drops_empty_slots_and_doubled_stops():
    from those_who_run.verbalise import tidy_sentence

    assert tidy_sentence("Lap one. fifty-seven point one. .") == "Lap one. fifty-seven point one."
    assert tidy_sentence("Lap two. x. zero point eight over best..") == (
        "Lap two. x. zero point eight over best."
    )
    assert tidy_sentence("Race over. . Best lap y.. ") == "Race over. Best lap y."
    assert tidy_sentence("Box!") == "Box!"
    assert tidy_sentence("Final lap") == "Final lap."


def test_tidy_sentence_with_nothing_left_is_empty():
    from those_who_run.verbalise import tidy_sentence

    assert tidy_sentence("") == ""
    assert tidy_sentence(" . . ") == ""
