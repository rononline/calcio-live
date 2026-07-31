# Soccer Live archive contract v1

External archives can be connected to the Archive card or imported with the
`soccer_live.import_match_archive` service. The canonical envelope is:

```json
{
  "schema": "soccer_live.archive.v1",
  "version": 1,
  "matches": [
    {
      "date_iso": "2026-05-10",
      "home_team": "Feyenoord",
      "away_team": "AZ",
      "home_score": 1,
      "away_score": 1,
      "competition_name": "Eredivisie",
      "season": "2025/26"
    }
  ]
}
```

`date_iso`, `home_team` and `away_team` identify a match when no `event_id` or
`canonical_id` is available. Scores, competition, season, venue, logos and team
IDs are optional. Imports also accept a bare list and the Dutch legacy aliases
`datum`, `thuis`, `uit`, `uitslag`, `competitie`, `seizoen` and `stadion`. This
makes exports from feyod or a personal MySQL sensor usable without pretending
that a public provider owns the historical data.
