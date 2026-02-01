# Dev Notes

## Video Duration Limits

**Replicate Kling**: 10s max per generation

**Direct Kling API**: 30s max (requires business approval)

## Workarounds for Longer Videos

1. **Extend Video API** - Generate 10s, then extend by 5s increments (up to 3 min total)
2. **Stitch clips** - Generate multiple clips, combine with ffmpeg/editing software
3. **Direct Kling API** - Once approved, supports 30s in one shot

## TODO

- [ ] Add "Extend Video" endpoint to chain clips automatically
- [ ] Get Kling direct API approved for cheaper rates + longer videos

## Quality Notes

- 0-30s: Quality stays consistent
- 30-60s: Subtle drift, lighting shifts
- 60-120s: Noticeable degradation, character morphing

Keep individual shots under 30s for best results.
