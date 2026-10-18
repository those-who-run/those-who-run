"""``those-who-run cars``: GT7 car names by car code."""

from __future__ import annotations

import argparse

from those_who_run.config import Settings

HELP = "GT7 car names by car code"
SETTINGS: tuple[str, ...] = ()


def configure(parser: argparse.ArgumentParser) -> None:
    crs = parser.add_subparsers(dest="cars_command", required=True)
    crs.add_parser("list", help="print the car table")
    cf = crs.add_parser("find", help="cars whose maker or model contains every word given")
    cf.add_argument("text", nargs="+")
    cn = crs.add_parser("name", help="the name for one car code")
    cn.add_argument("code", type=int)


def run(args: argparse.Namespace, settings: Settings) -> int:
    from those_who_run.cars import car_name, find_cars, load_cars

    if args.cars_command == "name":
        print(car_name(args.code) or "none")
        return 0
    cars = load_cars() if args.cars_command == "list" else find_cars(" ".join(args.text))
    for c in cars:
        print(f"{c.id:5d}  {c.full_name}")
    return 0 if cars else 1
