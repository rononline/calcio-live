"""Knockout bracket processing for elimination-phase competitions.

ESPN exposes KO matches on the standard /scoreboard endpoint, distinguished by
notes like "1st Leg" / "2nd Leg - X advance Y-Z on aggregate". This module groups
them into ties (first + second leg) and rounds (Round of 16 / Quarterfinals / etc.).

Round names are English; the card translates them via i18n keys (round.*).
"""

import logging

_LOGGER = logging.getLogger(__name__)
import re


def _parse_aggregate(note_text):
    """Parse the 2nd-leg note: '2nd Leg - X advance Y-Z on aggregate'.
    Returns dict {winner_team, agg_for, agg_against, tied} or None.
    """
    if not note_text:
        return None
    if "Tied on aggregate" in note_text:
        return {"winner_team": None, "agg_for": None, "agg_against": None, "tied": True}
    m = re.search(r"2nd Leg\s*-\s*(.+?)\s+(?:advance|lead)\s+(\d+)\s*-\s*(\d+)\s+on aggregate", note_text)
    if m:
        return {
            "winner_team": m.group(1).strip(),
            "agg_for": int(m.group(2)),
            "agg_against": int(m.group(3)),
            "tied": False,
        }
    return None


def _safe_int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def process_bracket_data(data):
    """Extract the bracket from /scoreboard data for a KO phase.
    Returns {rounds: [{name, size, ties: [...]}], ties_count}.
    """
    out = {"rounds": [], "ties_count": 0}
    try:
        events = data.get("events", []) or []
        ties = {}  # key: frozenset(id1, id2) → tie dict

        for e in events:
            if not isinstance(e, dict):
                _LOGGER.warning("Skipping malformed bracket event (not a dict)")
                continue
            comps = e.get("competitions", []) or []
            if not comps:
                continue
            c = comps[0]
            notes = c.get("notes", []) or []
            note_text = ""
            if notes:
                note_text = notes[0].get("headline", "") or notes[0].get("text", "") or ""

            season = e.get("season") if isinstance(e.get("season"), dict) else {}
            slug = str(season.get("slug", "")).lower()

            slug_map = {
                "round-of-64": "Round of 64",
                "round-of-32": "Round of 32",
                "round-of-16": "Round of 16",
                "quarterfinals": "Quarterfinals",
                "semifinals": "Semifinals",
                "3rd-place-match": "Third Place",
                "final": "Final",
            }

            is_first_leg = "1st Leg" in note_text
            is_second_leg = "2nd Leg" in note_text
            is_single_ko = slug in slug_map
            is_final_single = is_single_ko or (
                not is_first_leg and not is_second_leg and "Final" in note_text
            )

            if not (is_first_leg or is_second_leg or is_final_single):
                continue

            competitors = c.get("competitors", []) or []
            home = next((x for x in competitors if x.get("homeAway") == "home"), None)
            away = next((x for x in competitors if x.get("homeAway") == "away"), None)
            if not home or not away:
                continue

            home_team = (home.get("team") or {}).get("displayName", "")
            away_team = (away.get("team") or {}).get("displayName", "")
            home_id = (home.get("team") or {}).get("id", "")
            away_id = (away.get("team") or {}).get("id", "")
            home_logo = (home.get("team") or {}).get("logo", "")
            away_logo = (away.get("team") or {}).get("logo", "")
            home_abbrev = (home.get("team") or {}).get("abbreviation", "")
            away_abbrev = (away.get("team") or {}).get("abbreviation", "")

            tie_key = frozenset([home_id, away_id])
            if tie_key not in ties:
                ties[tie_key] = {
                    "team_a": {"name": "", "logo": "", "abbrev": "", "id": ""},
                    "team_b": {"name": "", "logo": "", "abbrev": "", "id": ""},
                    "leg1": None,
                    "leg2": None,
                    "single": None,
                    "first_leg_date": None,
                    "winner_team": None,
                    "aggregate": None,
                    "tied": False,
                    "completed": False,
                }
            tie = ties[tie_key]

            # Only fields consumed by the Bracket card: per leg the card reads
            # home_team/away_team/home_score/away_score/state (logos/abbrev come from
            # team_a/team_b, not per leg). Per-leg logos/abbrev/status/venue/event_id
            # are unused ESPN raw fields — omitted to stay under the 16384-byte recorder limit.
            leg_payload = {
                "home_team": home_team,
                "home_score": _safe_int(home.get("score")),
                "away_team": away_team,
                "away_score": _safe_int(away.get("score")),
                "date": e.get("date", ""),
                "state": ((e.get("status") or {}).get("type") or {}).get("state", ""),
            }

            if is_first_leg:
                tie["leg1"] = leg_payload
                tie["first_leg_date"] = e.get("date", "")
                if not tie["team_a"]["name"]:
                    tie["team_a"] = {"name": home_team, "logo": home_logo, "abbrev": home_abbrev, "id": home_id}
                    tie["team_b"] = {"name": away_team, "logo": away_logo, "abbrev": away_abbrev, "id": away_id}
            elif is_second_leg:
                tie["leg2"] = leg_payload
                agg = _parse_aggregate(note_text)
                if agg:
                    tie["winner_team"] = agg.get("winner_team")
                    tie["aggregate"] = (
                        f"{agg.get('agg_for')}-{agg.get('agg_against')}"
                        if agg.get("agg_for") is not None else None
                    )
                    tie["tied"] = agg.get("tied", False)
                    tie["completed"] = leg_payload["state"] == "post"
                if not tie["team_a"]["name"]:
                    tie["team_a"] = {"name": away_team, "logo": away_logo, "abbrev": away_abbrev, "id": away_id}
                    tie["team_b"] = {"name": home_team, "logo": home_logo, "abbrev": home_abbrev, "id": home_id}

            elif is_final_single:
                tie["round_name"] = slug_map.get(slug, "Final")
                tie["single"] = leg_payload
                tie["first_leg_date"] = e.get("date", "")

                if not tie["team_a"]["name"]:
                    tie["team_a"] = {"name": home_team, "logo": home_logo, "abbrev": home_abbrev, "id": home_id}
                    tie["team_b"] = {"name": away_team, "logo": away_logo, "abbrev": away_abbrev, "id": away_id}

                # Determine winner if the match is completed
                hs, as_ = leg_payload["home_score"], leg_payload["away_score"]
                if leg_payload["state"] == "post" and hs is not None and as_ is not None:
                    tie["completed"] = True
                    if hs > as_:
                        tie["winner_team"] = home_team
                    elif as_ > hs:
                        tie["winner_team"] = away_team
                    else:
                        tie["tied"] = True

        # Sort ties by date of the 1st leg (or single-leg match)
        sorted_ties = sorted(
            ties.values(),
            key=lambda t: t.get("first_leg_date") or t.get("leg2", {}).get("date", "") if t.get("leg2") else "",
        )

        from collections import OrderedDict
        from datetime import datetime

        def parse_iso(s):
            if not s:
                return None
            try:
                return datetime.strptime(s[:10], "%Y-%m-%d")
            except Exception:
                return None

        # Single-leg tournaments (WK, Euros) set round_name via slug_map.
        # Two-leg competitions (UCL, Europa) do not — use date-based grouping instead.
        has_slug_rounds = any(tie.get("round_name") for tie in sorted_ties)

        if has_slug_rounds:
            # Group by explicit round name in chronological order.
            # This prevents rounds played close together (e.g. R32 then R16 with <7d gap)
            # from being incorrectly merged into one group.
            round_dict = OrderedDict()
            for tie in sorted_ties:
                rname = tie.get("round_name", "Unknown")
                if rname not in round_dict:
                    round_dict[rname] = []
                round_dict[rname].append(tie)

            for rname, ties_in_round in round_dict.items():
                size = 1
                while size < len(ties_in_round):
                    size *= 2
                for tie in ties_in_round:
                    tie.get("team_a", {}).pop("id", None)
                    tie.get("team_b", {}).pop("id", None)
                out["rounds"].append({
                    "name": rname,
                    "size": size,
                    "ties": ties_in_round,
                })

        else:
            # Date-based grouping for two-leg competitions (UCL, Europa League, etc.)
            groups = []
            current = []
            prev_date = None

            for tie in sorted_ties:
                d = parse_iso(tie.get("first_leg_date") or "")
                if prev_date is None or d is None or (d - prev_date).days <= 7:
                    current.append(tie)
                else:
                    groups.append(current)
                    current = [tie]
                if d is not None:
                    prev_date = d
            if current:
                groups.append(current)

            sized_rounds = []
            for g in groups:
                size = 1
                while size < len(g):
                    size *= 2
                sized_rounds.append({"size": size, "ties": g})

            canonical = {
                1: "Final",
                2: "Semifinals",
                4: "Quarterfinals",
                8: "Round of 16",
                16: "Round of 32",
                32: "Round of 64",
            }
            n = len(sized_rounds)
            labels = [None] * n

            if n > 0:
                expected = sized_rounds[-1]["size"]
                for idx in range(n - 1, -1, -1):
                    actual = sized_rounds[idx]["size"]
                    if actual == expected:
                        labels[idx] = canonical.get(actual, f"Round of {actual * 2}")
                        expected = actual * 2
                    elif idx + 1 < n and actual == sized_rounds[idx + 1]["size"]:
                        if actual == 8:
                            labels[idx] = "Knockout Playoffs"
                        elif actual == 16:
                            labels[idx] = "Preliminary Round"
                        else:
                            labels[idx] = canonical.get(actual, f"Round of {actual * 2}")
                        expected = actual * 2
                    else:
                        labels[idx] = canonical.get(actual, f"Round of {actual * 2}")
                        expected = actual * 2

            for idx, sr in enumerate(sized_rounds):
                for tie in sr["ties"]:
                    tie.get("team_a", {}).pop("id", None)
                    tie.get("team_b", {}).pop("id", None)
                out["rounds"].append({
                    "name": labels[idx],
                    "size": sr["size"],
                    "ties": sr["ties"],
                })

        out["ties_count"] = sum(len(r["ties"]) for r in out["rounds"])
    except Exception as e:
        _LOGGER.error(f"Error processing bracket data: {e}")
    return out
