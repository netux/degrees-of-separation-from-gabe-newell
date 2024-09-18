# Degrees of Separation from Gabe Newell

Python script to find the degrees of separation from any user to any valve employee (including Gabe Newell).

The script goes over your friend's friends list, then your friend's friends friends list, and so on, until it finds a match from one of the one Steam users with a public profile and a [Valve Employee badge](https://steamdb.info/badge/11/) (or [Gabe Newell](https://steamcommunity.com/id/GabeLoganNewell/)).

It also keeps track of the friend lists found along the way, storing them in an SQLite database `degrees-of-separation-from-gabe-newell.db` on the same folder of the script.

Based on [this video by Coeus](https://youtu.be/ZokhvNPmNzs).

Requires Python 3.10+ with sqlite3.

## Usage

1. Create a virtual-env and activate it

    ```sh
    python -m venv .venv
    source ./.venv/bin/<activate script for your system>
    ```

2. Install dependencies

    ```sh
    pip install -r requirements.txt
    ```

3. Setup environment variables

    ```sh
    cp .env.sample .env
    # open .env in your favorite text editor and add your Steam API Key and Steam ID
    ```

    * Generate a Steam API Key [here](https://steamcommunity.com/dev/apikey).

    * Get your Steam ID [here](https://steamdb.info/calculator/)

4. Run `degrees-of-separation-from-gabe-newell.py`

    ```sh
    # See which options are available
    # ./degrees-of-separation-from-gabe-newell.py --help

    ./degrees-of-separation-from-gabe-newell.py --verbosity=debug --max_depth=3 --request_delay=2.5 --simultaneous_requests=1
    ```

    * You probably want to keep the request delay above 1 (second), and simulatenous requests at 1. Otherwise, you may hit the ratelimit at most a day or two.
    * Increasing max depth expontentially increases the amount of time the script takes to run.
      I recommend keeping it low to check more quickly if you have any devs in close proximity to you. And if not, then increase it as much as you'd like.

      The [six handshake rule](https://en.wikipedia.org/wiki/Six_degrees_of_separation) says that people are, at most, 6 degrees of separation from anyone else in the world. Increasing max depth above 6 is not necessary.
    * `verbosity=debug` is nice to see the progress so far, but depending on how fast you are going, it may actually slow you down. Consider using `verbosity=info`
