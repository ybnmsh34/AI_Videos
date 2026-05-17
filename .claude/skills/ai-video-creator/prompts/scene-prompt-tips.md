# Writing strong image and motion prompts

Image prompts feed Flux (text-to-image). Motion prompts feed Kling / Stable Video Diffusion (image-to-video). They have different sweet spots.

## Image prompts

**Structure:** SUBJECT, ACTION, SETTING, CAMERA, MOOD.

✅ Good:
> "A cheerful purple octopus named Otto, waving one tentacle, sitting on a coral reef, medium shot from front, warm afternoon sunlight filtering through water"

❌ Bad:
> "Octopus on reef" (no specificity — model fills in randomly)
> "An octopus that looks happy and is in the ocean and is purple and is waving and..." (run-on, model gets confused)

**Character consistency:** for multi-scene videos featuring the same character, repeat the character description verbatim in every scene's image prompt. Models don't have memory across calls. Example: always say "a cheerful purple octopus with large round eyes and a small yellow bowtie" — never abbreviate to "Otto" after scene 1.

**Avoid:**
- Hands doing complex things (still a weak spot)
- Text in the image (use `on_screen_text` overlay instead)
- "Realistic photo" mixed with "cartoon style" — pick one
- Negative descriptors ("not blue") — models ignore them; describe what you want positively

## Motion prompts

**Structure:** WHAT MOVES, HOW IT MOVES, CAMERA DIRECTION.

✅ Good:
> "Camera slowly dollies forward; the octopus's tentacles undulate gently; bubbles rise from the seafloor"

❌ Bad:
> "Lots of movement" (model produces chaotic warping)
> "The octopus does a backflip while juggling" (too complex; physics break)

**Keep it physical and small.** Image-to-video models excel at:
- Gentle camera moves (pan, dolly, slow zoom)
- Hair / fabric / water motion
- Subtle facial movement (blink, smile)
- Particles (dust, sparkles, bubbles)

They struggle with:
- Full-body locomotion (walking, running)
- Object interaction (picking up, holding)
- Multiple characters interacting
- Complex camera moves (orbit, whip pans)

**When in doubt, default to:** "slow zoom in, subtle ambient motion in the scene."

## Aspect ratio note

Flux uses dimensions inferred from the storyboard's `aspect_ratio`. You don't need to mention "vertical" or "9:16" in the prompt — the renderer sets it. But framing matters: for 9:16, describe vertical composition ("subject centered, tall composition, headroom above"); for 16:9 describe wide ("subject left-third, wide horizon").
