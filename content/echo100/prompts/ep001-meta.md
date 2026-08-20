# ECHO//100 Episode 1 - Meta motion production pack

Episode: `echo100-s01e001`  
Title: `The Message From Tomorrow`  
Target: eight vertical motion clips, about five seconds each

## Operating rule

For each scene, open Meta AI/Vibes, choose image-to-video, upload the listed
reference image, paste the matching `meta_prompt` from `episodes/ep001.json`,
generate one clip, and download it with the exact filename shown below.

Do not ask Meta to redraw the scene. The supplied image is the character and
composition lock; the prompt requests motion only. Reject any generation that
changes Kavi's face or clothes, Byte's shape, Mira's hologram design, or adds
unwanted characters, text, logos, distorted hands or duplicate limbs.

## Clip checklist

| Scene | Reference image | Output filename | Story beat |
|---|---|---|---|
| 01 | `assets/story/echo100/exec-87ab096a-0780-4743-b93b-55d6b38522eb.png` | `scene-01.mp4` | The dead phone plays Kavi's future voice |
| 02 | `assets/story/echo100/exec-87ab096a-0780-4743-b93b-55d6b38522eb.png` | `scene-02.mp4` | The warning says not to trust Byte |
| 03 | `assets/story/echo100/exec-89230522-4ba4-4bee-8de4-e38689900263.png` | `scene-03.mp4` | Mira scans the impossible recording |
| 04 | `assets/story/echo100/exec-89230522-4ba4-4bee-8de4-e38689900263.png` | `scene-04.mp4` | The date is one hundred years old |
| 05 | `assets/story/echo100/exec-8915310f-9232-413e-9a22-dd3bad7f366f.png` | `scene-05.mp4` | Null appears across the arcade screens |
| 06 | `assets/story/echo100/exec-89230522-4ba4-4bee-8de4-e38689900263.png` | `scene-06.mp4` | The red door becomes real |
| 07 | `assets/story/echo100/exec-cbbccb8c-b9a3-462d-af4c-7abf2be6bbc4.png` | `scene-07.mp4` | Future Kavi warns his past self |
| 08 | `assets/story/echo100/exec-cbbccb8c-b9a3-462d-af4c-7abf2be6bbc4.png` | `scene-08.mp4` | Null sees them; the escape begins |

## Copy-ready prompts

### Scene 01

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 cinematic shot. Kavi slowly raises the dead phone while a cyan waveform pulses above it; his eyes widen and Byte floats closer with a worried expression. Slow controlled camera push-in, subtle breathing, cloth and antenna movement, red and cyan arcade lights flicker naturally. Preserve the exact faces, clothing, robot design, proportions and environment. No dialogue, no lip-sync, no cuts, no new characters, no generated text, no logos, no morphing, no extra limbs.
```

### Scene 02

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 cinematic shot. The phone suddenly flashes a red warning glow; Kavi recoils slightly and turns toward Byte. Byte freezes in mid-air, its cyan eyes dim for one beat, then look frightened. Use a gentle rack focus from the phone to Byte and a slow red light sweep across the arcade. Preserve every character and costume exactly. No dialogue, no lip-sync, no cuts, no new objects, no generated text, no logos, no morphing, no extra limbs.
```

### Scene 03

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 cinematic shot. Mira rapidly scans her holographic tablet; cyan scan lines travel from the tablet across the glowing red door. Her calm face changes to disbelief. Kavi steps back defensively and Byte turns toward the door. Slow lateral camera move, hologram particles drift naturally. Preserve exact identities, outfits, colours and proportions. No dialogue, no cuts, no generated letters or numbers, no logos, no morphing, no extra limbs.
```

### Scene 04

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 cinematic reaction shot. A cyan data pulse races across Mira's tablet and abruptly turns red; Mira looks shocked, Kavi glances between her and the door, and Byte lowers nervously. The red door throbs once with light and releases tiny sparks. Slow camera push toward their faces. Preserve the exact characters and environment. No readable text, no dialogue, no cuts, no new characters, no logos, no morphing, no extra limbs.
```

### Scene 05

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 suspense shot. Arcade screens flicker red in sequence while Null slowly assembles from floating purple pixels behind them. Kavi turns toward the threat, Mira raises one protective hand, and Byte drops closer to the floor in fear. Add one controlled digital glitch pulse and a subtle handheld retreat. Preserve exact faces, outfits and designs. No dialogue, no cuts, no gore, no new characters, no generated text, no logos, no body distortion or extra limbs.
```

### Scene 06

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 cinematic reveal. The red door brightens from a thin outline into a solid impossible doorway, casting moving red light over Kavi, Byte and Mira. Byte slowly floats toward it as if recognising it; Kavi reaches out to stop him and Mira watches with concern. Slow dramatic camera push-in. Preserve exact characters, costumes and environment. No dialogue, no cuts, no generated text, no logos, no morphing, no extra limbs.
```

### Scene 07

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 cinematic shot. Kavi cautiously reaches toward the glowing doorway, then stops as his phone vibrates in his hand. Future Kavi raises one palm in warning; Byte spins toward him and the golden doorway sheds floating sparks. Null remains distant and slowly advances through purple haze. Gentle camera arc around present Kavi. Preserve exact identities and proportions. No dialogue, no cuts, no generated text, no logos, no morphing, no extra limbs.
```

### Scene 08

```text
Animate only the uploaded reference image as a 5-second vertical 9:16 cliffhanger. Future Kavi urgently gestures for present Kavi to run; present Kavi recoils from the doorway and Byte turns toward Null. Null glides one step closer as purple corruption spreads across the floor. Golden sparks accelerate and the camera rapidly but smoothly pulls backward, ending on Null's red eyes. Preserve exact characters and clothing. No dialogue, no cuts, no gore, no generated text, no logos, no morphing, no extra limbs.
```

## Download folder

Put the eight downloaded files together in:

`D:\Apps\YT-Auto\incoming\meta\echo100-s01e001\`

Attach the full folder with one command:

```powershell
.\.venv\Scripts\python.exe tools\ingest_meta_batch.py `
  content\echo100\episodes\ep001.json `
  incoming\meta\echo100-s01e001
```

The files are attached to the episode with `tools/ingest_motion.py`. After all
eight are attached, `story_main.py` creates the narration, captions, thumbnail
and final private YouTube draft. Meta supplies motion clips only; it
does not control the final edit or upload.
