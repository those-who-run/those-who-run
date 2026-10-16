import pytest

from those_who_run.__main__ import build_parser, main
from those_who_run.cars import Car, car_name, find_cars, load_cars


def test_table_loads_with_makers():
    cars = load_cars()
    assert len(cars) >= 590
    assert all(c.id > 0 and c.maker and c.name for c in cars)
    assert len({c.id for c in cars}) == len(cars)


@pytest.mark.parametrize(
    ("code", "name"),
    [
        # the cars driven on 2026-10-15
        (683, "Honda Civic Si Group A version '87"),
        (3609, "Mazda RX-VISION GT3 EVO '26"),
        (3339, "Subaru BRZ Drift Car '17"),
        (3359, "Porsche 911 GT3 (997) '09"),
        (2160, "Hyundai Genesis Gr.3"),
    ],
)
def test_known_cars(code, name):
    assert car_name(code) == name


def test_unknown_and_missing_codes():
    assert car_name(99999) == "car 99999", "newer than the table"
    assert car_name(0) is None and car_name(None) is None


def test_maker_is_not_doubled():
    assert Car(1, "Mazda", "Mazda Roadster").full_name == "Mazda Roadster"
    assert Car(1, "", "Mystery").full_name == "Mystery"


def test_find_matches_every_word():
    assert [c.id for c in find_cars("rx-vision evo")] == [3609]
    assert find_cars("no such car anywhere") == []


def test_cars_cli(capsys):
    assert build_parser().parse_args(["cars", "find", "brz", "drift"]).text == ["brz", "drift"]
    assert main(["cars", "name", "3339"]) == 0
    assert capsys.readouterr().out.strip() == "Subaru BRZ Drift Car '17"
    assert main(["cars", "find", "zzzz"]) == 1
