from gt7_race_engineer.verbalise import delta_words, lap_time_words, laps_words, number_words


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
