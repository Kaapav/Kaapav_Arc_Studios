# NEON WOLVES — Manual Production

1. Lock all character turnarounds in `characters/`.
2. Create an episode: `python studio_manual_pipeline.py new-episode neon_wolves 1`.
3. Edit `episode.json`, including all eight `image_prompt` and narration fields.
4. Export prompts: `python studio_manual_pipeline.py prompts PATH_TO_EPISODE_JSON`.
5. Generate images manually and import them with the `import-image` command.
6. Validate: `python studio_manual_pipeline.py validate PATH_TO_EPISODE_JSON`.
7. Render and QC: `python studio_manual_pipeline.py render PATH_TO_EPISODE_JSON`.

This pipeline never uploads to YouTube.
