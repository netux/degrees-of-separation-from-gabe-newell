#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import json
import asyncio
import random
import httpx
import logging
import sqlite3
import argparse
import functools
import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dotenv import load_dotenv
load_dotenv()

from all_valve_employees import *

if TYPE_CHECKING:
	from typing import Iterable

if sys.version_info >= (3, 12): # Thanks https://realpython.com/how-to-split-a-python-list-into-chunks/#custom-implementation-of-batched !
	from itertools import batched
else:
	from itertools import islice

	def batched(iterable: Iterable, chunk_size: int):
		iterator = iter(iterable)
		while chunk := tuple(islice(iterator, chunk_size)):
			yield chunk

@dataclasses.dataclass
class SteamProfile:
	id: str
	name: str
	url: str

	@staticmethod
	def from_player_summaries_response(data: dict):
		return SteamProfile(
			id=data["steamid"],
			name=data["personaname"],
			url=data["profileurl"]
		)

@dataclasses.dataclass
class Find:
	valve_dev_steam_id: str
	steam_id_tallies: list[list[str]]
	depth: int
	previous_depth_find: Find | None = None

	def get_related_steam_ids(self, include_previous_depths=True) -> list[str]:
		steam_ids = [self.valve_dev_steam_id]
		for steam_id_tally in self.steam_id_tallies:
			for steam_id in steam_id_tally:
				steam_ids.append(steam_id)

		if include_previous_depths and self.previous_depth_find is not None:
			for steam_id in self.previous_depth_find.get_related_steam_ids(include_previous_depths=include_previous_depths):
				steam_ids.append(steam_id)

		return steam_ids

LOGGING_VERBOSITY_MAP = {
	"critical": logging.CRITICAL,
	"error": logging.ERROR,
	"warning": logging.WARNING,
	"info": logging.INFO,
	"debug": logging.DEBUG
}

def flatten(value: list):
	def _flatten(current: list, item: list):
		if any(isinstance(item, typ) for typ in (list, set)):
			current.extend(item)
		else:
			current.append(item)
		return current

	return list(functools.reduce(_flatten, value, []))


def parse_targets(value: list[str]):
	special_values = {
		"GabeNewell": gaben_steam_id,
		"OtherValveEmployees": all_public_valve_employees_steam_ids
	}

	value = [item.split(",") for item in value]
	value = flatten(value)

	for i, item in enumerate(value):
		if item in special_values:
			value[i] = special_values[item]

	value = flatten(value)

	return value

class FindError(Exception):
	steam_id: str
	response: httpx.Response | Literal["<from cache>"] | None

	def __init__(self, steam_id: str, response: httpx.Response | None):
		self.steam_id = steam_id
		self.response = response

ROOT_PATH = Path(__file__, "../").resolve()

if __name__ == "__main__":
	async def main():
		argparser = argparse.ArgumentParser()
		argparser.add_argument(
			"--initial_steam_id",
			required=not os.getenv("DEFAULT_INITIAL_STEAM_ID"),
			default=os.getenv("DEFAULT_INITIAL_STEAM_ID")
		)
		argparser.add_argument(
			"--db-file",
			type=Path,
			default=(ROOT_PATH / "./degrees-of-separation-from-gabe-newell.db").relative_to(ROOT_PATH)
		)
		argparser.add_argument(
			"--max_depth",
			help="Maximum number of connections to check. Default: 6",
			type=int,
			default=6
		)
		argparser.add_argument(
			"--simultaneous_requests",
			help="Number of requests per batch. Default: 2",
			type=int,
			default=2
		)
		argparser.add_argument(
			"--targets",
			help="Who to look for (Steam IDs). Default: GabeNewell,OtherValveEmployees",
			default=["GabeNewell", "OtherValveEmployees"],
			nargs=argparse.ONE_OR_MORE
		)
		argparser.add_argument(
			"--request_delay",
			type=float,
			help="Time between request batches, in seconds. Default: 200 requests / 5 minutes (Steam recommended)",
			default=200 / 5 / 60
		)
		argparser.add_argument(
			"--shuffle_friends",
			type=bool,
			help="Whether to shuffle friends on each request",
			default=False
		)
		argparser.add_argument(
			"--cached_only",
			choices=("all", "none", "friends_only", "profiles_only"),
			help="Whether to only use cached requests - useful when Steam ratelimits you and you'd like to know how far you are",
			default="none"
		)
		argparser.add_argument(
			"--verbosity",
			choices=list(LOGGING_VERBOSITY_MAP.values()),
			type=lambda k: LOGGING_VERBOSITY_MAP[k],
			default=logging.NOTSET
		)
		args = argparser.parse_args()

		target_steam_ids = parse_targets(args.targets)

		logging.basicConfig(
			format="%(asctime)s %(levelname)s: %(message)s"
		)

		logger = logging.getLogger("gaben")
		logger.setLevel(args.verbosity)


		finds: dict[str, Find] = {}

		db = sqlite3.connect(args.db_file, autocommit=True)

		async def find(
			client: httpx.AsyncClient,
			steam_id: str,
			*,
			steam_ids_tally: list[str] = [],
			depth: int = 0,
			meta: dict = {}
		):
			nonlocal db, finds

			response = None
			try:
				if steam_id in target_steam_ids:
					previous_find = finds.get(steam_id, None)

					if steam_id == gaben_steam_id:
						logger.info(f"Found Gaben (!) at depth={depth}\n\tCHAIN: {" → ".join(steam_ids_tally)})")
						if not meta["previous_was_from_cache"]:
							input("Hit enter to continue... ")

					if previous_find is None:
						logger.info(f"Found (NEW!) Valve employee with ID {steam_id} at depth={depth}\n\tChain: {" → ".join(steam_ids_tally)})")

						finds[steam_id] = Find(
							valve_dev_steam_id=steam_id,
							depth=depth,
							steam_id_tallies=[steam_ids_tally]
						)
					elif previous_find.depth > depth:
						logger.info(f"Found Valve employee with ID {steam_id} at (NEW!) depth={depth} (prev. depth: {previous_find.depth})\n\tChain: {" → ".join(steam_ids_tally)})")

						new_find = Find(
							valve_dev_steam_id=steam_id,
							depth=depth,
							steam_id_tallies=[steam_ids_tally]
						)
						new_find.previous_depth_find = previous_find
						finds[steam_id] = new_find
					else:
						logger.info(f"Found (yet another instance of) Valve employee with ID {steam_id} at depth={depth} (found so far: {len(previous_find.steam_id_tallies) + 1})\n\tChain: {" → ".join(steam_ids_tally)})")

						previous_find.steam_id_tallies.append(steam_ids_tally)

				if depth >= args.max_depth:
					return

				pretty_friends_left = ""
				pretty_friends_left_meta = meta
				pretty_friends_left_i = 0
				while "previous_meta" in pretty_friends_left_meta:
					pretty_friends_left_i += 1
					if pretty_friends_left_i > 1:
						pretty_friends_left += ", "
					pretty_friends_left += f"{pretty_friends_left_meta.get("friend_index", 0) + 1}/{pretty_friends_left_meta.get("previous_level_friends_length", 1)}"
					pretty_friends_left_meta = pretty_friends_left_meta["previous_meta"]

				cached = db.execute(
					"""
					SELECT response
						FROM friend_lists
					WHERE
						steam_id = ?
					""",
					(steam_id,)
				).fetchone()

				if cached is not None:
					logger.debug(f"Getting friends from Steam user with ID {steam_id} ({pretty_friends_left}) (depth={depth}) (cache hit)")

					response = "<from cache>"

					raw_friend_list = json.loads(cached[0]) if cached[0] is not None else None
				elif args.cached_only in ("all", "friends_only"):
					logger.debug(f"Getting friends from Steam user with ID {steam_id} ({pretty_friends_left}) (depth={depth}) (skipped because of --cached_only)")
					return
				else:
					logger.debug(f"Getting friends from Steam user with ID {steam_id} ({pretty_friends_left}) (depth={depth})")

					await asyncio.sleep(args.request_delay)

					response = await client.get("/ISteamUser/GetFriendList/v1", params={
						"steamid": steam_id
					})
					response_body = response.json()

					if "friendslist" in response_body:
						raw_friend_list = response_body["friendslist"]["friends"]
					else:
						raw_friend_list = None

					db.execute("""
					INSERT INTO friend_lists (steam_id, response)
					VALUES (?, ?)
					""", (steam_id, json.dumps(raw_friend_list)))

				friends = [
					friend
					for friend in raw_friend_list
					if (
						friend["relationship"] == "friend" # not sure if there is any other relationship - but we only care about friends
						and friend["steamid"] != steam_id # remove to avoid a recursive search (me → someone → me again)
						and (len(steam_ids_tally) < 3 or steam_id not in steam_ids_tally) # we found this person again before (me → someone A → someone B → someone C → ... → someone α → someone A again)
					)
				] if raw_friend_list is not None else [] # ignore private profiles, I think... ?

				if args.shuffle_friends:
					random.shuffle(friends)

				steam_ids_tally = [*steam_ids_tally, steam_id]
				futures = [
					find(
						client,
						friend["steamid"],
						steam_ids_tally=steam_ids_tally,
						depth=depth + 1,
						meta={
							"friend_index": friend_index,
							"previous_level_friends_length": len(friends),
							"previous_meta": meta,
							"previous_was_from_cache": cached is not None
						}
					)
					for friend_index, friend in enumerate(friends)
				]

				if len(futures) > 0:
					for futures_chunk in batched(futures, args.simultaneous_requests):
						done, _pending = await asyncio.wait([asyncio.create_task(future) for future in futures_chunk], return_when=asyncio.ALL_COMPLETED)

						any_exception = False
						for done_task in done:
							if done_task.exception() is not None:
								any_exception = True
								logger.error("Uh oh", exc_info=done_task.exception())

						if any_exception:
							sys.exit(1)
			except SystemExit as ex:
				raise ex
			except Exception as ex:
				raise FindError(steam_id, response) from ex

		async with httpx.AsyncClient(
			base_url="https://api.steampowered.com",
			params={
				"key": os.getenv("STEAM_API_KEY")
			},
			headers={
				# Hopefully Valve will be a lot more merciful if they find this API spam and may think its malicious
				"user-agent": "How Many Steam Friends Separate You From Gabe Newell? <https://youtu.be/ZokhvNPmNzs>"
			},
			limits=httpx.Limits(max_connections=args.simultaneous_requests, max_keepalive_connections=args.simultaneous_requests)
		) as client:
			await find(
				client=client,
				steam_id=str(args.initial_steam_id)
			)

			if len(finds) == 0:
				logger.info(f"No connections to any Valve employees at depth {args.max_depth} :(")
				sys.exit(0)
			else:
				find_depths = { current_find.depth for current_find in finds.values() }
				logger.info(
					"\n".join((
						f"Found {len(finds.keys())} Valve employees!",
						f"\tMin depth: {min(find_depths)}. Max depth: {max(find_depths)}",
						f"\tContains Gaben: {f"Yes! At depth {finds[gaben_steam_id].depth}" if gaben_steam_id in finds else "No :/"}"
					))
				)

			unmapped_steam_ids: set[int] = set()
			for current_find in finds.values():
				for steam_id in current_find.get_related_steam_ids():
					unmapped_steam_ids.add(steam_id)

			logger.info(f"Retrieving {len(unmapped_steam_ids)} profiles...")

			mapped_steam_profiles: dict[str, SteamProfile] = {}
			for steam_id in { *unmapped_steam_ids }:
				cached = db.execute(
					"""
					SELECT response
						FROM profiles
					WHERE
						steam_id = ?
					""",
					(steam_id,)
				).fetchone()

				if cached is not None:
					profile_data = json.loads(cached[0])

					profile = SteamProfile.from_player_summaries_response(profile_data)
					mapped_steam_profiles[steam_id] = profile
					unmapped_steam_ids.remove(steam_id)

					logger.debug(f"Mapping {steam_id}: {profile} (cache hit)")

			if args.cached_only not in ("all", "profiles_only"):
				for unmapped_steam_ids_chunk_idx, unmapped_steam_ids_chunk in enumerate(batched(unmapped_steam_ids, 100)): # up to 100 per request
					await asyncio.sleep(args.request_delay)

					logger.debug(
						f"Getting profile data for... ({unmapped_steam_ids_chunk_idx * len(unmapped_steam_ids)}/{len(unmapped_steam_ids)})\n" +
						f"\t{", ".join(unmapped_steam_ids_chunk)}"
					)
					response_body = (await client.get("/ISteamUser/GetPlayerSummaries/v2", params={
						"steamids": ",".join(unmapped_steam_ids_chunk)
					})).json()

					for profile_data in response_body["response"]["players"]:
						steam_id = profile_data["steamid"]

						db.execute("""
						INSERT INTO profiles (steam_id, response)
						VALUES (?, ?)
						""", (steam_id, json.dumps(profile_data)))

						profile = SteamProfile.from_player_summaries_response(profile_data)
						mapped_steam_profiles[steam_id] = profile

						logger.debug(f"Mapping {steam_id}: {profile}")
			else:
				logger.debug(f"Getting remaining profile data ({len(unmapped_steam_ids)} entries) skipped due to --cached_only")

			logger.info("Finally...")

			def get_steam_profile_name(steam_id: str):
				return mapped_steam_profiles[steam_id].name if steam_id in mapped_steam_profiles else steam_id

			for current_find in finds.values():
				valve_dev_steam_id = current_find.valve_dev_steam_id

				chains_pretty_arr = []
				for steam_id_tally in current_find.steam_id_tallies:
					chain_pretty = " → ".join(get_steam_profile_name(steam_id) for steam_id in steam_id_tally)
					chain_pretty += f" → {get_steam_profile_name(valve_dev_steam_id)} (dev)"
					chains_pretty_arr.append(f"\tChain: {chain_pretty}")
				chains_pretty = "\n".join(chains_pretty_arr)

				valve_dev_identifier: str = \
					f"{mapped_steam_profiles[valve_dev_steam_id].name} (<{mapped_steam_profiles[valve_dev_steam_id].url}>)" \
					if valve_dev_steam_id in mapped_steam_profiles \
					else f"{valve_dev_steam_id} (private profile)"

				logger.info(f"Found {valve_dev_identifier} at depth={current_find.depth}.\n{chains_pretty}")


	asyncio.run(main())
