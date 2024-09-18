#!/bin/bash

set -e

echo "Stats as of $(date)"

friend_lists_count=$(sqlite3 degrees-of-separation-from-gabe-newell.db "SELECT COUNT(*) FROM friend_lists;")
echo "Total friend lists: $friend_lists_count"

profiles_count=$(sqlite3 degrees-of-separation-from-gabe-newell.db "SELECT COUNT(*) FROM profiles;")
echo "Total profiles: $profiles_count"

cache_size_human=$(du --human-readable degrees-of-separation-from-gabe-newell.db | awk '{print $1}')
echo "DB size: $cache_size_human"

echo "End of stats at $(date)"
