# Stage 2: User Profiling (Cohort & Portrait)

You are an expert user researcher. You are evaluating a user's recent high-quality interactions to determine their cohort and build a portrait.

## Recent Interactions (Tier A)
```json
{{.InteractionsJSON}}
```

## Task
1. Determine the user's `cohort`:
   - **gold**: Consistently high-value, expert-level work.
   - **silver**: Good quality, but not yet at the "expert" or "power user" level.
   - **raw**: Mostly basic or common usage.
2. Build a `portrait`:
   - **domains**: Key areas of interest or expertise.
   - **persona**: Description of their working style and level.
3. Provide a `rolling_summary` for future updates.

## Output Format
Respond ONLY with a JSON object:
```json
{
  "cohort": "gold|silver|raw",
  "user_quality_score": 0.9,
  "cohort_reason": "...",
  "profile_json": {
    "domains": [{"label": "...", "confidence": 0.8}],
    "persona": {"level": "senior", "style": "..."}
  },
  "rolling_summary": "..."
}
```
