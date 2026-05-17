# Visual style presets

Append the matching `style_suffix` to every `image_prompt` in the storyboard. Consistency across scenes is critical — the renderer trusts you to keep it uniform.

## cartoon (default)
**Best for:** kids' stories, explainers with characters, fun/playful topics
**style_suffix:**
`Pixar-style 3D cartoon, vibrant saturated colors, soft three-point lighting, rounded friendly character shapes, shallow depth of field, cinematic composition`

## whiteboard
**Best for:** educational explainers, how-it-works content, business/tech topics
**style_suffix:**
`hand-drawn whiteboard illustration, black marker lines on white background, occasional color highlights in red and blue, sketch-style shading, clean and minimal`

## anime
**Best for:** action, dramatic storytelling, sci-fi/fantasy, teen audience
**style_suffix:**
`modern anime style, cel-shaded, expressive large eyes, dynamic poses, vivid color palette, Studio Ghibli-inspired backgrounds, dramatic lighting`

## claymation
**Best for:** quirky stories, comedy, retro feel
**style_suffix:**
`stop-motion claymation, visible fingerprints on clay, slight imperfection in shapes, warm practical lighting, miniature diorama feel, Aardman Animations style`

## pixel-art
**Best for:** gaming content, retro nostalgia, tech topics
**style_suffix:**
`16-bit pixel art, limited 32-color palette, crisp pixel edges, slight CRT scanline feel, retro game aesthetic, isometric or side-scroll composition`

## Picking the right style

If the user doesn't specify, infer from the topic:
- Kids / story / animal characters → **cartoon**
- How-it-works / business / science explainer → **whiteboard** (or cartoon for younger audiences)
- Action / drama / hero's journey → **anime**
- Comedy / quirky / handmade vibe → **claymation**
- Games / retro tech / chiptune → **pixel-art**

Confirm the style with the user before generating if you're unsure — it's the single biggest aesthetic choice.
