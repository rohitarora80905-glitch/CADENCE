# Cadence Studio — How to Use It

*15 October 2026*

## Start it

Double-click `run_studio.bat` in the `cadence` folder, or run `python -m studio` there. The Studio opens at http://127.0.0.1:8000/.

The first start installs FastAPI, uvicorn and groq if they are missing. The compiler itself needs nothing but Python 3.10 or newer.

## The screen

- **Score** (left): the Cadence program you are editing, with Moods and Examples above it and diagnostics below.
- **Piano roll** (middle): the compiled music with a playhead, and the capture strip under it.
- **Composer** (right): the AI panel.
- **Keyboard** (bottom): 88 keys you can play, with its settings in the bar above the keys.
- **Top bar**: the Studio, Glass Box and The Core views; play, stop and loop; the time, tempo and key; Compile and Export.

The strip under the top bar lights one dot per compiler stage every time the score compiles. Click a dot to open that stage in the Glass Box.

## Write or pick music

Pick a **Mood** for a complete piano piece, or an **Example** from the compiler, then change anything you like. The score compiles as you type; switch **auto** off to compile only with Ctrl+Enter or the Compile button.

Errors and warnings appear under the editor and on their line numbers. Click one to jump to it.

The language fits in a few lines: `tempo 96 ;` and `key E minor ;` set the piece; notes are written `C4 Eb4 G4/8`, scale degrees `^1 ^5'`, rests `r/8`, chords `<C4 E4 G4>/4`; `repeat 2 of [ ... ]` repeats; `phrase name = ... ;` names a passage; `voice right on piano = ... ;` gives it an instrument; `play right | left ;` plays voices together. Every statement ends with ` ;`.

## Hear it

Press **Enter** or the gold button to play, **Esc** or the square to stop, and the loop button to repeat. Click anywhere on the piano roll to jump there; the zoom box above it shows the whole piece or 8 to 64 bars at a time. The keys light up in each voice's colour while it plays.

If you edit while it plays, a *new version ready* chip appears on the roll; stop, or click the chip, to switch to it.

**Export** in the top bar saves the `.mid` file for any media player, or the `.cad` source.

## Play the piano

Click or tap the keys. Clicking lower on a key plays louder; dragging across keys plays a glissando.

On the computer keyboard, A S D F G H J K L play the white keys from C and W E T Y U O P the black ones. Z and X move the octave down and up, Shift plays louder, and holding **Space** is the sustain pedal.

The bar above the keys sets the labels (note names, or the scale degrees of the compiled key), the sound (synth grand, a sampled grand that downloads once, electric piano, harpsichord), the volume and the room. Small dots on the keys mark the current scale; the larger dot is its root.

## Capture what you play

Turn on **capture** in the bar above the keys. Pick a note length (1, 2, 4, 8, 16, with an optional dot) and a mode: *melody* writes one token per key, *chord* gathers the keys you hold into one `<...>/4`. *Degrees* writes `^1 ^3 ^5` of the compiled key instead of letter names, and the chord palette inserts the diatonic chords of that key.

The tokens collect in the strip under the piano roll; click one to remove it. **Insert at cursor** drops them into the editor. **As phrase** wraps them in `phrase captured1 = [ ... ] ;` before the first voice, ready to use in a voice.

## Ask the composer

Click **Key** in the Composer panel and paste a Groq API key from https://console.groq.com/keys. It stays in your browser and is sent only to your own Studio server.

Then use the buttons: **Continue** adds what comes next, **Harmonise** adds a left hand, **Vary** writes a variation, **Mood...** recolours the piece to a mood you describe, **Explain** describes the piece in words, **Fix** repairs compile errors. Or type any request in the box.

Every proposal is compiled before you see it: a green badge means it compiles, a red one lists the errors. **Replace score** takes it, **Audition** plays it without touching your score, **Insert at cursor** adds it where you are.

**Karaoke...** builds a backing track for a song you name: the model gives only the chart (key, tempo, chords per bar, form) and the Studio arranges keys, bass, drums, pads and a riff in the song's style, bar-aligned and compiled, with no vocal. **Import MIDI** in the Score panel turns a `.mid` file you have into a program, one voice per part; delete the vocal voice from `play` for an exact backing.

**Full song...** reproduces a complete piece you name, from the first bar to the last, with no limit on length: a long piece arrives in several parts, each stitched on and compiled, and the panel shows the progress while it works. Use the roll's zoom (8 to 64 bars per screen) to read it; the roll scrolls to follow the playhead.

## Look inside the compiler

**Glass Box** (top bar) shows the current score at every stage: the tokens and the DFA, the parse tables and the syntax tree, the symbol table and attribute flow, the three-address code, every optimisation pass with its before-and-after counts, the data-flow iterations, the verifier, the channel allocation, the MIDI bytes and all the metrics.

**The Core** explains the six phases of the pipeline, shows live measurements from the showcase program, and lets you read every source file of the compiler and of the Studio in place.

## Keys at a glance

These work whenever the editor does not have the cursor.

| Key | Does |
| --- | --- |
| Enter | play / pause |
| Esc | stop |
| Ctrl + Enter | compile |
| Space (hold) | sustain pedal |
| A S D F G H J K L | white keys from C |
| W E T Y U O P | black keys |
| Z / X | octave down / up |
| Shift + key | louder |
