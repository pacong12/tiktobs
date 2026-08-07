# Custom Gift Alert Sounds

Place your custom audio sound file inside this folder if you want to override the default chime sound.

The overlay will search for files in this priority order:
1. `gift-alert.wav`
2. `gift-alert.mp3`

If none of those files are found in this directory, the overlay will automatically fall back to generating a synthesized arpeggio chime programmatically using the Web Audio API (meaning the overlay sound will always work 100% of the time without errors!).

### Formats supported:
- WAV
- MP3
